"""Conservative scope interpretation. Names and LLM text never prove a match."""

import html
import re
import unicodedata
from datetime import date
from app.schemas.matching import Stock, Target, Verification


def normalize_gtin(value: object) -> str | None:
    # A float has already lost identity information; never repair one silently.
    if isinstance(value, float) or isinstance(value, bool):
        return None
    text = str(value).strip() if value is not None else ""
    return text if re.fullmatch(r"(?:\d{8}|\d{12,14})", text, flags=re.ASCII) else None


def gtin_key(value: str) -> str:
    return value.zfill(14)


def lot_key(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def parse_identification(
    raw: object, fallback_gtin: object = None
) -> tuple[list[Target], list[str]]:
    warnings: list[str] = []
    targets: list[Target] = []
    if not isinstance(raw, str):
        raw = ""
    for row in html.unescape(raw).split("|"):
        if not row.strip():
            continue
        parts = row.split("$")
        gtin = normalize_gtin(parts[0])
        if not gtin:
            warnings.append(f"Unrecognized GTIN in scope: {row[:120]}")
            continue
        target = Target(gtin=gtin, raw=row)
        if len(parts) != 5:
            target.parseable = False
            target.warning = "Expected five encoded scope fields."
        else:
            lot, kind, start, end = [p.strip() for p in parts[1:]]
            target.all_lots = lot_key(lot) in {
                "tous les lots",
                "tous lots",
                "all lots",
                "tous",
            }
            # Whitespace, ranges, prose, wildcards and prefix descriptions are intentionally unsupported.
            if lot and not target.all_lots:
                tokens = re.split(r"\s*[,;]\s*", lot)
                if all(re.fullmatch(r"[A-Za-z0-9._/-]+", t) for t in tokens):
                    target.lots = tokens
                else:
                    target.parseable = False
                    target.warning = "Lot expression needs human interpretation."
            if kind and kind.casefold() != "non concerné":
                target.date_type = kind
                if kind.casefold() not in {
                    "date limite de consommation",
                    "date de durabilité minimale",
                    "date de consommation recommandée",
                }:
                    target.parseable = False
                    target.warning = "Unknown date constraint type."
                try:
                    target.date_start = date.fromisoformat(start) if start else None
                    target.date_end = (
                        date.fromisoformat(end) if end else target.date_start
                    )
                    if not target.date_start or (
                        target.date_end and target.date_end < target.date_start
                    ):
                        raise ValueError("missing or reversed date")
                except ValueError:
                    target.parseable = False
                    target.warning = "Invalid or missing scope date."
            elif start or end:
                target.parseable = False
                target.warning = "Date values without an interpretable date type."
            if not lot and not target.date_start:
                target.parseable = False
                target.warning = (
                    "Empty lot scope does not establish an all-lots recall."
                )
        if target.warning:
            warnings.append(target.warning)
        targets.append(target)
    fallback = normalize_gtin(fallback_gtin)
    if fallback and not any(gtin_key(t.gtin) == gtin_key(fallback) for t in targets):
        targets.append(
            Target(
                gtin=fallback,
                parseable=False,
                raw=str(raw),
                warning="Missing encoded scope for source GTIN.",
            )
        )
        warnings.append("Missing encoded scope for source GTIN.")
    if not targets:
        warnings.append("No usable product identifiers; manual source review required.")
    return targets, warnings


def check_lot_constraints(
    stock: Stock,
    targets: list[Target],
    supplier_lots: list[str] | None = None,
    scope_incomplete: bool = False,
) -> Verification:
    gtin = normalize_gtin(stock.gtin)
    if not gtin:
        return Verification(
            verdict="review",
            explanation="Inventory identifier is malformed; review the original label.",
        )
    relevant = [t for t in targets if gtin_key(t.gtin) == gtin_key(gtin)]
    if not relevant:
        return Verification(
            verdict="review" if scope_incomplete else "unaffected",
            explanation="Official scope is incomplete."
            if scope_incomplete
            else "GTIN is absent from the complete recall scope.",
        )
    if (
        supplier_lots
        and stock.lot
        and any(lot_key(lot) != lot_key(stock.lot) for lot in supplier_lots)
    ):
        return Verification(
            verdict="conflict",
            matched_gtin=True,
            explanation="Supplier evidence contradicts the warehouse lot. Preserve any existing hold and request human investigation.",
            checks=["GTIN matched", "Contradictory lot evidence"],
        )
    unresolved = scope_incomplete
    for target in relevant:
        if not target.parseable:
            unresolved = True
            continue
        if not stock.lot and not target.all_lots:
            unresolved = True
            continue
        lot_matches = (
            target.all_lots
            or not target.lots
            or any(lot_key(stock.lot) == lot_key(lot) for lot in target.lots)
        )
        if not lot_matches:
            continue
        if target.date_start:
            if not stock.expires_on:
                unresolved = True
                continue
            if (
                not target.date_start
                <= stock.expires_on
                <= (target.date_end or target.date_start)
            ):
                continue
        return Verification(
            verdict="affected",
            matched_gtin=True,
            explanation="GTIN and explicit lot/date constraints match official recall scope.",
            checks=["GTIN matched", "Lot scope matched", "Date constraints satisfied"],
        )
    if unresolved:
        return Verification(
            verdict="review",
            matched_gtin=True,
            explanation="Missing lot/date information or unparseable official scope prevents a definitive conclusion. Request human review.",
            checks=["GTIN matched", "Scope verification incomplete"],
        )
    return Verification(
        verdict="unaffected",
        matched_gtin=True,
        explanation="GTIN matches, but the known lot/date is outside every parsed affected target.",
        checks=["GTIN matched", "Known lot/date excluded by complete scope"],
    )
