"""Run migrations and tests against a separate database using Compose credentials."""

import os
import subprocess
import sys
from pathlib import Path
import psycopg
from sqlalchemy.engine import make_url

root = Path("/verify")
sys.path.insert(0, str(root / "backend"))
from app.core.config import settings

url = make_url(settings.db_url)
admin = url.set(drivername="postgresql").render_as_string(hide_password=False)
test_url = url.set(database="recallops_test").render_as_string(hide_password=False)
with psycopg.connect(admin, autocommit=True) as connection:
    # Serialize suites that deliberately reset the shared test replay workspace.
    connection.execute("SELECT pg_advisory_lock(4242099)")
    if not connection.execute(
        "SELECT 1 FROM pg_database WHERE datname='recallops_test'"
    ).fetchone():
        connection.execute("CREATE DATABASE recallops_test")
    env = {
        **os.environ,
        "DATABASE_URL": test_url,
        "PYTHONPATH": str(root / "backend"),
        "LLM_API_KEY": "",
        "OPENAI_API_KEY": "",
        "OPERATOR_TOKEN": "",
        "ENVIRONMENT": "development",
        "PUBLIC_DEMO": "false",
        "WORKER_ENABLED": "false",
        "SOURCE_REFRESH_SECONDS": "0",
        "MUTATION_LIMIT_PER_MINUTE": "10000",
    }
    subprocess.run(
        ["alembic", "-c", str(root / "backend/alembic.ini"), "upgrade", "head"],
        env=env,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(root / "backend/tests"),
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        env=env,
        check=True,
    )
