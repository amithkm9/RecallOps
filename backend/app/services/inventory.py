import csv
import io
from datetime import date
from pydantic import BaseModel, Field, field_validator, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.models import Store, InventoryLot
from app.repositories.records import append_audit_event
from app.services.matching import normalize_gtin, lot_key
from app.services.ingestion import discover_incidents


class InventoryRow(BaseModel):
    sku: str = Field(min_length=1, max_length=120)
    product_name: str = Field(min_length=1, max_length=500)
    gtin: str
    lot: str | None = Field(default=None, max_length=300)
    quantity: int = Field(ge=0, le=10000000)
    supplier: str = Field(default="", max_length=300)
    expires_on: date | None = None

    @field_validator("gtin")
    @classmethod
    def valid_gtin(cls, value):
        result = normalize_gtin(value)
        if not result:
            raise ValueError(
                "GTIN must be an 8, 12, 13 or 14 digit string; scientific notation is invalid."
            )
        return result

    @field_validator("lot", "expires_on", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        return value or None


def active_store(db: Session, mode: str) -> Store:
    store = db.scalar(
        select(Store)
        .where(Store.mode == mode, Store.active.is_(True))
        .order_by(Store.created_at.desc())
    )
    if not store:
        store = Store(
            name="Marché Saint-Martin" if mode == "live" else "Marché Demo · Fictional",
            mode=mode,
        )
        db.add(store)
        db.flush()
    return store


def import_csv(
    db: Session, content: bytes, mode: str, store_id: str | None = None
) -> dict:
    if len(content) > 2_000_000:
        raise ValueError("CSV exceeds the 2 MB upload limit.")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as exc:
        raise ValueError("Use a UTF-8 CSV file.") from exc
    required = {
        "sku",
        "product_name",
        "gtin",
        "lot",
        "quantity",
        "supplier",
        "expires_on",
    }
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError(
            "Missing CSV columns: "
            + ", ".join(sorted(required - set(reader.fieldnames or [])))
        )
    db.execute(text("SELECT pg_advisory_xact_lock(4242002)"))
    store = db.get(Store, store_id) if store_id else active_store(db, mode)
    if not store or store.mode != mode or not store.active:
        raise ValueError("Choose an active store in this mode.")
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,2))"),
        {"key": store.id},
    )
    imported = 0
    errors = []
    for number, row in enumerate(reader, 2):
        if number > 10001:
            errors.append({"row": number, "message": "Maximum 10,000 rows per import."})
            break
        try:
            item = InventoryRow.model_validate(
                {k: v.strip() if isinstance(v, str) else v for k, v in row.items() if k}
            )
            existing = db.scalar(
                select(InventoryLot).where(
                    InventoryLot.store_id == store.id,
                    InventoryLot.sku == item.sku,
                    InventoryLot.lot_key == lot_key(item.lot),
                )
            )
            if existing:
                # Repeated identical imports are idempotent. Do not erase held quantity via CSV.
                from app.models import InventoryHold

                held = db.scalars(
                    select(InventoryHold).where(
                        InventoryHold.inventory_lot_id == existing.id,
                        InventoryHold.status == "active",
                    )
                ).all()
                if held and (
                    existing.gtin != item.gtin
                    or existing.expires_on != item.expires_on
                    or item.quantity < max(h.quantity for h in held)
                ):
                    raise ValueError(
                        "Cannot change identity or reduce quantity below an active hold. Resolve the hold through review first."
                    )
                for key, value in item.model_dump().items():
                    setattr(existing, key, value)
            else:
                db.add(
                    InventoryLot(
                        store_id=store.id,
                        lot_key=lot_key(item.lot),
                        **item.model_dump(),
                    )
                )
            db.flush()
            imported += 1
        except (ValidationError, ValueError) as exc:
            errors.append({"row": number, "message": str(exc)})
    db.flush()
    discover_incidents(db, store_id=store.id, mode=mode)
    append_audit_event(
        db,
        "inventory_imported",
        {
            "message": f"{imported} inventory rows imported; {len(errors)} rejected.",
            "synthetic": mode == "replay",
        },
        store_id=store.id,
        actor="operator",
    )
    db.commit()
    return {"imported": imported, "errors": errors}
