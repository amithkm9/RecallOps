"""Isolated PDF text extraction. Limits protect the web worker from hostile PDFs."""

import io
import json
import resource
import sys


def main():
    # macOS does not implement a usable RLIMIT_AS for Python's existing virtual
    # address space. Linux production workers retain the strict memory cap;
    # local macOS extraction remains CPU/time/input/page limited.
    if sys.platform != "darwin":
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        cap = 256 * 1024 * 1024
        if hard != resource.RLIM_INFINITY:
            cap = min(cap, hard)
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    from pypdf import PdfReader

    content = sys.stdin.buffer.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("Document too large")
    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted or len(reader.pages) > 20:
        raise ValueError("Encrypted document or too many pages")
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "")[:15000]
        pages.append({"page": number, "text": text})
    print(
        json.dumps(
            {
                "pages": pages,
                "text_status": (
                    "extracted_unverified"
                    if any(p["text"].strip() for p in pages)
                    else "needs_ocr"
                ),
                "scope_verified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
