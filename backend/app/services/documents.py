"""Fetch only document URLs supplied by the pinned official source record."""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
import httpx
from sqlalchemy.orm import Session
from app.models import Incident, Recall, RecallVersion, utcnow
from app.repositories.records import add_evidence, enqueue, record

FIELDS = {
    "lien_vers_affichette_pdf",
    "lien_vers_la_liste_des_produits",
    "lien_vers_la_liste_des_distributeurs",
}
HOSTS = {"rappel.conso.gouv.fr", "data.economie.gouv.fr"}


def extract_pdf(content: bytes) -> dict:
    # Uvicorn --app-dir affects its sys.path, not child-process PYTHONPATH.
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin"),
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.services.pdf_worker"],
            input=content,
            capture_output=True,
            timeout=8,
            check=True,
            env=env,
        )
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError):
        return {
            "pages": [],
            "text_status": "extraction_failed",
            "scope_verified": False,
        }


def validated_url(raw: dict, field: str) -> str:
    if field not in FIELDS or not isinstance(raw.get(field), str):
        raise ValueError("No official attachment URL is available for this field.")
    url = raw[field]
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in HOSTS
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Attachment host is not allowlisted. Review the official link manually."
        )
    return url


def fetch_document(db: Session, incident: Incident, field: str) -> dict:
    recall = db.get(Recall, incident.recall_id)
    version = db.get(RecallVersion, recall.current_version_id)
    url = validated_url(version.raw, field)
    # No automatic redirects: an official redirect must be independently allowlisted.
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks, length = [], 0
            for chunk in response.iter_bytes():
                length += len(chunk)
                if length > 2_000_000:
                    raise ValueError(
                        "Official attachment exceeds the 2 MB limit; review manually."
                    )
                chunks.append(chunk)
            content = b"".join(chunks)
    if not content.startswith(b"%PDF-"):
        raise ValueError(
            "Only PDF attachments are supported; this document needs manual review."
        )
    extracted = extract_pdf(content)
    evidence = add_evidence(
        db,
        incident.id,
        "official_document",
        "Official attachment · " + field,
        {
            "field": field,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "content_base64": base64.b64encode(content).decode(),
            **extracted,
        },
        recall_version_id=version.id,
        source_url=url,
        synthetic=False,
    )
    event = enqueue(
        db,
        f"document:{evidence.id}",
        "official_document_received",
        incident.id,
        incident.store_id,
        {"recall_version_id": version.id, "evidence_id": evidence.id},
    )
    db.commit()
    return {
        "evidence_id": evidence.id,
        "event_id": event.id,
        "text_status": extracted["text_status"],
        "scope_verified": False,
    }
