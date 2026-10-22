import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, OperationalError
from app.api.routes import router
from app.api.investigator import router as investigator_router
from app.api.investigator_experiments import router as experiments_router
from app.api.operations import router as operations_router
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.events import process_next
from app.services.ingestion import sync_source

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def worker():
    from time import monotonic

    heartbeat_at = 0
    while True:
        try:
            if monotonic() - heartbeat_at > 30:

                def heartbeat():
                    from sqlalchemy.dialects.postgresql import insert
                    from app.models import SourceState, utcnow

                    with SessionLocal() as db:
                        db.execute(
                            insert(SourceState)
                            .values(id="worker", last_attempt=utcnow(), details={})
                            .on_conflict_do_update(
                                index_elements=["id"], set_={"last_attempt": utcnow()}
                            )
                        )
                        db.commit()

                await asyncio.to_thread(heartbeat)
                heartbeat_at = monotonic()
            worked = await asyncio.to_thread(process_next)
        except Exception:
            log.exception("Outbox attempt failed; persisted retry policy applies.")
            worked = False
        await asyncio.sleep(0.1 if worked else 1)


async def refresh():
    # Delay initial refresh so offline demo startup never depends on the government API.
    while True:
        await asyncio.sleep(settings.source_refresh_seconds)
        try:

            def sync():
                with SessionLocal() as db:
                    sync_source(db, "live")

            await asyncio.to_thread(sync)
        except Exception:
            log.exception("Scheduled source refresh failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if (
        settings.environment != "development"
        and settings.operator_token
        and len(settings.operator_token) < 32
    ):
        raise RuntimeError(
            "Production OPERATOR_TOKEN must contain at least 32 characters."
        )
    if (
        settings.environment != "development"
        and not settings.operator_token
        and not settings.public_demo
    ):
        raise RuntimeError(
            "Production requires OPERATOR_TOKEN or explicitly isolated PUBLIC_DEMO=true."
        )
    tasks = []
    if settings.worker_enabled:
        tasks.append(asyncio.create_task(worker()))
    if settings.source_refresh_seconds > 0 and not settings.public_demo:
        tasks.append(asyncio.create_task(refresh()))
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="RecallOps",
    version="1.0.0",
    description="Evidence-grounded product safety command center. API v1 is available at /api and /api/v1.",
    lifespan=lifespan,
)
app.include_router(router, prefix="/api")
app.include_router(router, prefix="/api/v1", include_in_schema=False)
app.include_router(investigator_router, prefix="/api")
app.include_router(investigator_router, prefix="/api/v1", include_in_schema=False)
app.include_router(experiments_router, prefix="/api")
app.include_router(experiments_router, prefix="/api/v1", include_in_schema=False)
app.include_router(operations_router, prefix="/api")
app.include_router(operations_router, prefix="/api/v1", include_in_schema=False)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": str(exc.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "; ".join(
                    f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
                ),
            }
        },
    )


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_input", "message": str(exc)}},
    )


@app.exception_handler(IntegrityError)
async def constraint_error(request, exc):
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "conflict",
                "message": "This operation conflicts with an existing record or a database safety constraint.",
            }
        },
    )


@app.exception_handler(OperationalError)
async def database_error(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "PostgreSQL is unavailable. Check the server database configuration.",
            }
        },
    )


@app.exception_handler(Exception)
async def internal_error(request, exc):
    log.exception("Request failed", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "The request could not complete. Inspect server logs and the persisted event status.",
            }
        },
    )


@app.middleware("http")
async def response_headers(request: Request, call_next):
    if request.url.path.startswith("/api"):
        from app.core.guardrails import check_request

        try:
            await asyncio.to_thread(
                check_request,
                request.method,
                request.url.path,
                request.headers.get("authorization"),
                request.headers.get("origin"),
                str(request.base_url).rstrip("/"),
                request.client.host if request.client else "unknown",
            )
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.status_code, "message": exc.detail}},
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


dist = settings.frontend_dist
from app.core.body_limit import BodyLimitMiddleware

app.add_middleware(BodyLimitMiddleware)
if not dist.exists():
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if not dist.exists():
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if (dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API route not found.")
    if (dist / "index.html").is_file():
        return FileResponse(dist / "index.html")
    return JSONResponse(
        {
            "message": "RecallOps API is ready. Start Vite on port 5173 or build frontend/dist."
        }
    )
