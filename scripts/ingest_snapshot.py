"""Import an official Explore API JSON export, preserving immutable versions."""

import argparse
import json
import sys

sys.path.insert(0, "backend")
from app.core.database import SessionLocal
from app.services.ingestion import ingest_records

parser = argparse.ArgumentParser()
parser.add_argument("file", help="Official JSON export or Explore API response")
args = parser.parse_args()
with open(args.file) as source:
    data = json.load(source)
records = data.get("results", []) if isinstance(data, dict) else data
if not isinstance(records, list):
    raise ValueError("Expected a JSON list or results array.")
with SessionLocal() as db:
    result = ingest_records(db, records, "historical_snapshot")
    db.commit()
print(json.dumps(result, indent=2))
