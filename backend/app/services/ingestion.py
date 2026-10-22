import json
from datetime import datetime, timezone
import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import (
    Recall,
    RecallVersion,
    RecallTarget,
    SourceState,
    Store,
    InventoryLot,
    Incident,
    utcnow,
    SourceRefresh,
    SourceRejection,
)
from app.repositories.records import digest, enqueue, append_audit_event
from app.services.matching import parse_identification, gtin_key

DATASET_URL = "https://www.data.gouv.fr/datasets/rappelconso-v2-rappels-de-produits"
COVERAGE = "The GTIN-based dataset does not cover all recalls. Refreshes depend on the official publisher; ingestion time is not publication time. Bounded live imports scan the latest records, not the full historical catalog."


def parse_time(value: str | None) -> datetime:
    if not value:
        raise ValueError("Official publication timestamp is required.")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def ingest_records(
    db: Session,
    records: list[dict],
    origin: str = "snapshot",
    refresh_id: str | None = None,
) -> dict:
    db.execute(text("SELECT pg_advisory_xact_lock(4242001)"))
    created = 0
    skipped = 0
    errors = []
    changed = []
    for raw in records:
        try:
            with db.begin_nested():
                try:
                    if not isinstance(raw, dict) or not raw.get("id"):
                        raise ValueError("Missing stable official identifier.")
                    source_id = str(raw["id"])
                    if raw.get("date_modification"):
                        parse_time(raw["date_modification"])
                    published = parse_time(raw.get("date_publication"))
                    if not raw.get("lien_vers_la_fiche_rappel", "").startswith(
                        "https://rappel.conso.gouv.fr/"
                    ):
                        raise ValueError("Missing official RappelConso source URL.")
                    targets, warnings = parse_identification(
                        raw.get("identification_produits"), raw.get("gtin")
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    errors.append(str(exc))
                    if refresh_id:
                        db.add(
                            SourceRejection(
                                refresh_id=refresh_id,
                                reason=str(exc),
                                raw=raw if isinstance(raw, dict) else {"record": raw},
                            )
                        )
                    continue
                recall = db.scalar(select(Recall).where(Recall.source_id == source_id))
                if not recall:
                    recall = Recall(
                        source_id=source_id,
                        reference=str(raw.get("numero_fiche") or source_id),
                    )
                    db.add(recall)
                    db.flush()
                recall.last_seen_at = utcnow()
                # GTIN-sorted rows repeat the complete identification string. Exclude the row projection only.
                content_hash = digest({k: v for k, v in raw.items() if k != "gtin"})
                existing = db.scalar(
                    select(RecallVersion).where(
                        RecallVersion.recall_id == recall.id,
                        RecallVersion.content_hash == content_hash,
                    )
                )
                if existing:
                    skipped += 1
                    continue
                version = RecallVersion(
                    recall_id=recall.id,
                    content_hash=content_hash,
                    official_version=str(raw.get("numero_version", "unknown")),
                    product_name=raw.get("libelle")
                    or raw.get("modeles_ou_references")
                    or "Unnamed product",
                    brand=raw.get("marque_produit") or "",
                    category=raw.get("categorie_produit") or "",
                    published_at=published,
                    source_updated_at=(
                        parse_time(raw["date_modification"])
                        if raw.get("date_modification")
                        else None
                    ),
                    source_url=raw["lien_vers_la_fiche_rappel"],
                    reason=raw.get("motif_rappel") or "",
                    risk=raw.get("risques_encourus") or "",
                    raw=raw,
                    parse_warnings=warnings,
                )
                db.add(version)
                db.flush()
                for target in targets:
                    db.add(
                        RecallTarget(
                            recall_version_id=version.id,
                            gtin=gtin_key(target.gtin),
                            scope=target.model_dump(mode="json"),
                        )
                    )
                previous = (
                    db.get(RecallVersion, recall.current_version_id)
                    if recall.current_version_id
                    else None
                )

                # Historical imports never roll a newer official version backwards.
                def version_rank(v):
                    return (
                        int(v.official_version) if v.official_version.isdigit() else 0,
                        v.published_at,
                    )

                if not previous or version_rank(version) >= version_rank(previous):
                    recall.current_version_id = version.id
                    changed.append(recall.id)
                created += 1
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            reason = "Record rejected: " + type(exc).__name__
            errors.append(reason)
            if refresh_id:
                db.add(
                    SourceRejection(
                        refresh_id=refresh_id,
                        reason=reason,
                        raw=raw if isinstance(raw, dict) else {"record": raw},
                    )
                )
    db.flush()
    for recall_id in changed:
        discover_incidents(db, recall_id=recall_id, mode="live")
    append_audit_event(
        db,
        "source_ingested",
        {
            "message": f"{created} new immutable versions from {origin}; {skipped} duplicates skipped.",
            "origin": origin,
            "created": created,
            "skipped": skipped,
            "errors": errors,
        },
    )
    return {"created": created, "skipped": skipped, "errors": errors, "origin": origin}


def discover_incidents(
    db: Session,
    recall_id: str | None = None,
    store_id: str | None = None,
    mode: str = "live",
) -> list[Incident]:
    stores = db.scalars(
        select(Store).where(
            Store.active.is_(True),
            Store.mode == mode,
            *([Store.id == store_id] if store_id else []),
        )
    ).all()
    recalls = db.scalars(
        select(Recall).where(
            ~Recall.source_id.startswith("benchmark:"),
            *([Recall.id == recall_id] if recall_id else []),
        )
    ).all()
    discovered = []
    for store in stores:
        inventory = db.scalars(
            select(InventoryLot).where(InventoryLot.store_id == store.id)
        ).all()
        gtins = {gtin_key(i.gtin) for i in inventory}
        for recall in recalls:
            targets = db.scalars(
                select(RecallTarget).where(
                    RecallTarget.recall_version_id == recall.current_version_id
                )
            ).all()
            incident = db.scalar(
                select(Incident).where(
                    Incident.store_id == store.id, Incident.recall_id == recall.id
                )
            )
            if not incident and not any(t.gtin in gtins for t in targets):
                continue
            if not incident:
                incident = Incident(store_id=store.id, recall_id=recall.id)
                db.add(incident)
                db.flush()
            inventory_hash = digest(
                [
                    (i.id, i.lot, i.quantity, str(i.expires_on), i.updated_at)
                    for i in inventory
                ]
            )
            enqueue(
                db,
                f"recall:{recall.current_version_id}:{store.id}:{inventory_hash}",
                "recall_or_inventory_changed",
                incident.id,
                store.id,
                {"recall_version_id": recall.current_version_id},
            )
            discovered.append(incident)
    return discovered


def _sync_source(
    db: Session, source: str, start_offset: int, refresh: SourceRefresh
) -> dict:
    scans = []
    state = db.get(SourceState, "rappelconso")
    if not state:
        state = SourceState(id="rappelconso")
        db.add(state)
        db.flush()
    state.last_attempt = utcnow()
    live_error = None
    origin = source
    if source == "live":
        try:
            records = []
            with httpx.Client(timeout=25, follow_redirects=True) as client:
                for offset in range(
                    start_offset,
                    min(start_offset + settings.source_max_records, 10000),
                    100,
                ):
                    response = client.get(
                        settings.source_url,
                        params={
                            "limit": min(
                                100,
                                settings.source_max_records - (offset - start_offset),
                            ),
                            "offset": offset,
                            "order_by": "date_publication desc",
                        },
                    )
                    response.raise_for_status()
                    result = response.json()
                    if not isinstance(result.get("results"), list):
                        raise ValueError(
                            "Unexpected official API schema: results array missing."
                        )
                    scans.append(
                        {
                            "query": "latest",
                            "offset": offset,
                            "received": len(result["results"]),
                            "total_count": result.get("total_count"),
                        }
                    )
                    records.extend(result["results"])
                    if len(result["results"]) < 100:
                        break
                # Revisit tracked recalls and inventory identifiers even when publication is old.
                tracked_ids = list(
                    db.scalars(
                        select(Recall.source_id)
                        .join(Incident, Incident.recall_id == Recall.id)
                        .join(Store, Store.id == Incident.store_id)
                        .where(Store.mode == "live", Store.active.is_(True))
                    )
                )
                inventory_gtins = list(
                    db.scalars(
                        select(InventoryLot.gtin)
                        .join(Store, Store.id == InventoryLot.store_id)
                        .where(Store.mode == "live", Store.active.is_(True))
                    )
                )
                for field, values in [("id", tracked_ids), ("gtin", inventory_gtins)]:
                    numeric = sorted({str(int(v)) for v in values if v.isdigit()})
                    for index in range(0, len(numeric), 25):
                        where = (
                            field
                            + " in ("
                            + ",".join(numeric[index : index + 25])
                            + ")"
                        )
                        for offset in range(0, settings.source_max_records, 100):
                            response = client.get(
                                settings.source_url,
                                params={"limit": 100, "offset": offset, "where": where},
                            )
                            response.raise_for_status()
                            result = response.json()
                            if not isinstance(result.get("results"), list):
                                raise ValueError(
                                    "Unexpected tracked-recall API response."
                                )
                            scans.append(
                                {
                                    "query": where,
                                    "offset": offset,
                                    "received": len(result["results"]),
                                    "total_count": result.get("total_count"),
                                }
                            )
                            records.extend(result["results"])
                            if len(result["results"]) < 100:
                                break
            if not records:
                raise ValueError("Official API returned no records.")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            live_error = f"Official API unavailable ({type(exc).__name__}); loaded archived fixture fallback."
            origin = "fixture_fallback"
    if source != "live" or live_error:
        records = json.loads(
            (settings.fixture_dir / "official_snapshot.json").read_text()
        )
    result = ingest_records(db, records, origin, refresh.id)
    state.last_error = live_error
    if source == "live" and not live_error:
        state.last_successful_sync = utcnow()
    state.details = {
        "origin": origin,
        "records_received": len(records),
        "coverage": COVERAGE,
        **result,
    }
    by_query = {}
    for scan in scans:
        by_query[scan["query"]] = scan
    truncated = any(
        scan["total_count"] is not None
        and scan["offset"] + scan["received"] < scan["total_count"]
        for scan in by_query.values()
    )
    next_offset = min(start_offset + settings.source_max_records, 10000)
    refresh.status = (
        "fallback"
        if live_error
        else "partial" if result["errors"] or truncated else "completed"
    )
    refresh.finished_at = utcnow()
    refresh.details = {
        **state.details,
        "scans": scans,
        "start_offset": start_offset,
        "truncated": truncated,
        "next_offset": next_offset if truncated and next_offset < 10000 else None,
        "error": live_error,
        "withdrawal_policy": "Absence from a bounded scan never withdraws a recall or releases stock.",
    }
    db.commit()
    return {
        "refresh_id": refresh.id,
        **result,
        "message": live_error
        or f"Imported {result['created']} new versions; skipped {result['skipped']} duplicates. Source: {origin}.",
    }


def sync_source(db: Session, source: str = "live", start_offset: int = 0) -> dict:
    refresh = SourceRefresh(
        source=source, status="running", details={"start_offset": start_offset}
    )
    db.add(refresh)
    db.commit()
    refresh_id = refresh.id
    try:
        return _sync_source(db, source, start_offset, refresh)
    except Exception as exc:
        db.rollback()
        refresh = db.get(SourceRefresh, refresh_id)
        refresh.status = "failed"
        refresh.finished_at = utcnow()
        refresh.details = {
            "start_offset": start_offset,
            "error_type": type(exc).__name__,
        }
        db.commit()
        raise
