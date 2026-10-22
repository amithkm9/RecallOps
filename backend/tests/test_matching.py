import json
from datetime import date
from pathlib import Path
import pytest
from app.schemas.matching import Stock
from app.services.matching import (
    check_lot_constraints,
    normalize_gtin,
    parse_identification,
)

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "data/fixtures/benchmark.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_independent_labels(case):
    targets, warnings = parse_identification(case["scope"], case.get("fallback_gtin"))
    stock = Stock.model_validate(
        {k: v for k, v in case.items() if k in Stock.model_fields}
    )
    result = check_lot_constraints(
        stock,
        targets,
        [case["supplier_lot"]] if case.get("supplier_lot") else [],
        any(w.startswith("Unrecognized GTIN") for w in warnings),
    )
    assert result.verdict == case["expected"]


@pytest.mark.parametrize(
    "value", [3.760099533007e12, "3.760099533007e12", "NaN", "123", "ABC", None, True]
)
def test_identifiers_never_float(value):
    assert normalize_gtin(value) is None


def test_encoded_gtin_preserves_leading_zero():
    targets, warnings = parse_identification(
        "04056489840961$c2411120027$date de durabilité minimale$2026-05-13$",
        4056489840961,
    )
    assert targets[0].gtin == "04056489840961"
    assert not warnings


def test_unknown_format_does_not_invent_scope():
    targets, warnings = parse_identification("3760099533007$A1", "3760099533007")
    assert warnings and not targets[0].parseable


def test_official_fixture_parses(fixture_dir):
    records = json.loads((fixture_dir / "official_snapshot.json").read_text())
    for record in records:
        targets, warnings = parse_identification(
            record["identification_produits"], record["gtin"]
        )
        assert targets
        assert not warnings


def test_multiple_gtin_date_scope_keeps_pairing():
    targets, _ = parse_identification(
        "3760099533007$A1$date limite de consommation$2024-12-20$|3261430001372$B2$date limite de consommation$2025-12-26$"
    )
    assert (
        check_lot_constraints(
            Stock(gtin="3760099533007", lot="B2", expires_on=date(2025, 12, 26)),
            targets,
        ).verdict
        == "unaffected"
    )


def test_conflict_does_not_become_match():
    targets, _ = parse_identification("3760099533007$A1$non concerné$$")
    result = check_lot_constraints(
        Stock(gtin="3760099533007", lot="A1"), targets, ["B2"]
    )
    assert result.verdict == "conflict"
