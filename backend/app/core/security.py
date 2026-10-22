"""Bearer credentials with named roles and explicit store scope; secrets stay server-side."""

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from fastapi import Header, HTTPException
from sqlalchemy import select
from app.core.config import settings


@dataclass(frozen=True)
class Principal:
    name: str
    role: str
    store_ids: tuple[str, ...] | None


def identity(authorization: str | None) -> Principal | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    supplied = authorization[7:]
    if settings.operator_token and compare_digest(supplied, settings.operator_token):
        return Principal("bootstrap_operator", "admin", None)
    from app.core.database import SessionLocal
    from app.models import AccessCredential

    with SessionLocal() as db:
        credential = db.scalar(
            select(AccessCredential).where(
                AccessCredential.token_hash == sha256(supplied.encode()).hexdigest(),
                AccessCredential.active.is_(True),
            )
        )
        if credential:
            return Principal(
                credential.name,
                credential.role,
                None if credential.role == "admin" else tuple(credential.store_ids),
            )
    return None


def is_operator(authorization: str | None) -> bool:
    person = identity(authorization)
    return bool(person and person.role in {"admin", "operator"})


def authorize(
    mode: str = "live", authorization: str | None = None, strict: bool = False
):
    person = identity(authorization)
    if person and (not strict or person.role in {"admin", "operator"}):
        return
    if strict:
        raise HTTPException(
            403,
            "This action requires an authorized operator token. Configure OPERATOR_TOKEN or a named operator credential.",
        )
    if authorization:
        raise HTTPException(401, "Invalid or revoked access credential.")
    if settings.public_demo:
        if mode == "replay":
            return
        raise HTTPException(
            403, "Public demo access is restricted to fictional replay data."
        )
    if settings.environment == "development" and not settings.operator_token:
        return
    raise HTTPException(
        401, "An operator token is required. Enter it in Data & settings."
    )


def store_scope(authorization: str | None) -> tuple[str, ...] | None:
    person = identity(authorization)
    return person.store_ids if person else None


def require_store(store_id: str, authorization: str | None):
    ids = store_scope(authorization)
    if ids is not None and store_id not in ids:
        raise HTTPException(403, "This credential cannot access that store.")


def require_admin(authorization: str | None):
    authorize(authorization=authorization)
    person = identity(authorization)
    if person and person.role != "admin":
        raise HTTPException(403, "Administrator access is required.")


def actor_name(authorization: str | None) -> str:
    person = identity(authorization)
    return person.name if person else "local_development_operator"


def operator(authorization: str | None = Header(default=None)):
    authorize(authorization=authorization, strict=True)
