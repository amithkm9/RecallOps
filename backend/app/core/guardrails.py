"""Cross-process mutation budget and role checks; no credentials in bucket keys."""

import time
from hashlib import sha256
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import identity
from app.models import RequestBudget


def check_request(
    method: str,
    path: str,
    authorization: str | None,
    origin: str | None,
    own_origin: str,
    client_host: str,
):
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if (
        origin
        and origin != own_origin
        and origin not in settings.allowed_origins.split(",")
    ):
        raise HTTPException(403, "Cross-origin mutations are not allowed.")
    person = identity(authorization)
    if person and person.role == "viewer":
        raise HTTPException(403, "Read-only credentials cannot change data.")
    if (
        person
        and person.role == "integration"
        and not (
            path.endswith("/inventory-events") or path.endswith("/supplier-evidence")
        )
    ):
        raise HTTPException(
            403,
            "Integration credentials may submit scoped inventory or supplier events only.",
        )
    minute = int(time.time() // 60)
    key = sha256((authorization or client_host).encode()).hexdigest()
    with SessionLocal() as db:
        count = db.scalar(
            insert(RequestBudget)
            .values(key=key, bucket_window=minute, count=1)
            .on_conflict_do_update(
                index_elements=["key", "bucket_window"],
                set_={"count": RequestBudget.count + 1},
            )
            .returning(RequestBudget.count)
        )
        db.execute(
            delete(RequestBudget).where(RequestBudget.bucket_window < minute - 2)
        )
        db.commit()
    if count > settings.mutation_limit_per_minute:
        raise HTTPException(
            429, "Mutation rate limit reached. Retry in the next minute."
        )
