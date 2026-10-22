import json
import sys

sys.path.insert(0, "backend")
from app.core.database import SessionLocal
from app.services.evaluation import run_evaluation
from app.repositories.records import record

with SessionLocal() as db:
    print(json.dumps(record(run_evaluation(db)), indent=2))
