import io
import json
import subprocess
import sys
import pytest
from pypdf import PdfWriter
from app.services.documents import validated_url
from app.services.evaluation import metrics, run_evaluation
from app.core.config import settings


def test_attachment_urls_cannot_be_arbitrary_or_private():
    field = "lien_vers_affichette_pdf"
    for url in [
        "http://rappel.conso.gouv.fr/test",
        "https://localhost/doc.pdf",
        "https://rappel.conso.gouv.fr.evil.test/doc",
        "https://user@rappel.conso.gouv.fr/a",
        "https://rappel.conso.gouv.fr:8443/a",
    ]:
        with pytest.raises(ValueError):
            validated_url({field: url}, field)
    assert validated_url(
        {field: "https://rappel.conso.gouv.fr/affichettepdf/17010/interne"}, field
    ).startswith("https://")


def test_pdf_without_text_is_marked_for_review(tmp_path, monkeypatch):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    content = io.BytesIO()
    writer.write(content)
    from app.services.documents import extract_pdf

    monkeypatch.chdir(tmp_path)
    data = extract_pdf(content.getvalue())
    assert data["text_status"] == "needs_ocr" and data["scope_verified"] is False


def test_metrics_measure_missed_holds_review_burden_and_percentiles():
    result = metrics(
        "test",
        ["affected", "review", "unaffected", "review"],
        [{"expected": x} for x in ["affected", "affected", "unaffected", "review"]],
        [10, 20, 30, 40],
    )
    assert result["missed_hold_rate"] == 0.5
    assert result["review_request_rate"] == 0.5
    assert result["p50_latency_ms"] == 25
    assert result["p95_latency_ms"] == pytest.approx(38.5)


def test_external_labels_preserved_and_evaluation_does_not_call_model(
    db, fixture_dir, monkeypatch
):
    import httpx

    monkeypatch.setattr(settings, "llm_api_key", "configured-but-do-not-spend")
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *a, **kw: pytest.fail("Deterministic benchmark must not call model"),
    )
    cases = json.loads((fixture_dir / "benchmark.json").read_text())[:3]
    cases[0][
        "expected"
    ] = "unaffected"  # Intentionally disagrees with matcher; labels must not be rewritten.
    run = run_evaluation(
        db,
        cases,
        {
            "source": "Separately supplied test labels",
            "labeler": "Test reviewer",
            "split": "held_out",
        },
    )
    assert run.cases[0]["expected"] == "unaffected"
    assert run.results[-1]["precision"] == 0
    provenance = next(c for c in run.cases if c["name"] == "Dataset provenance")
    assert (
        len(provenance["sha256"]) == 64
        and provenance["independent_review_verified"] is False
    )
