"""Exercise actual PDF bytes through the isolated parser, not a mocked extractor."""

import io
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from app.services.investigator_evidence import parse_pdf


def delivery_pdf(extra=""):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    lines = [
        "delivery_id: D-104",
        "sku: SALMON-DELIVERY",
        "gtin: 3760099533007",
        "lot: 24326020",
        "quantity: 24",
        "expires_on: 2024-12-20",
        "reference: Fictional receiving record",
    ]
    if extra:
        lines.append(extra)
    stream = DecodedStreamObject()
    stream.set_data(
        (
            "BT /F1 12 Tf 40 790 Td "
            + " 0 -18 Td ".join(f"({line}) Tj" for line in lines)
            + " ET"
        ).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_real_labelled_delivery_pdf_keeps_page_and_source_excerpt():
    claims, errors, status, pages = parse_pdf(delivery_pdf())
    assert len(claims) == 1 and not errors
    assert claims[0]["lot"] == "24326020"
    assert claims[0]["quantity"] == 24
    assert claims[0]["locator"] == "PDF page 1"
    assert "Fictional receiving record" in claims[0]["excerpt"]
    assert status == "extracted_unverified"


def test_real_pdf_repeated_batch_needs_human_review():
    claims, errors, status, pages = parse_pdf(delivery_pdf("lot: ANOTHER-BATCH"))
    assert not claims and errors
