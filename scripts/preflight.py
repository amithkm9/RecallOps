"""Report deployment readiness without printing secrets or provisioning services."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy.engine import make_url
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine

url = make_url(settings.db_url)
checks = {
    "postgresql": url.drivername.startswith("postgresql"),
    "production_mode": settings.environment == "production",
    "strong_bootstrap_token": len(settings.operator_token) >= 32,
    "verified_database_tls": url.host in {"db", "localhost", "127.0.0.1"}
    or url.query.get("sslmode") == "verify-full",
    "worker_enabled": settings.worker_enabled,
    "bounded_source_scan": 0 < settings.source_max_records <= 1000,
}
try:
    with engine.connect() as connection:
        checks["migrations_current"] = (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
        )
except Exception:
    checks["migrations_current"] = False
print(
    json.dumps(
        {
            "checks": checks,
            "ready": all(checks.values()),
            "note": "Does not verify hosting, backups, retailer credentials, external alerts or legal/commercial readiness.",
        },
        indent=2,
    )
)
sys.exit(0 if all(checks.values()) else 1)
