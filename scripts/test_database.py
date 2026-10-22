"""Create an isolated local test database; never truncate the application database."""

import os
import subprocess
import psycopg
from psycopg import sql

url = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://recallops:recallops@127.0.0.1:55432/recallops"
).replace("postgresql+psycopg://", "postgresql://")
base, _, query = url.partition("?")
test_url = base.rsplit("/", 1)[0] + "/recallops_test" + ("?" + query if query else "")
with psycopg.connect(url, autocommit=True) as conn:
    if not conn.execute(
        "SELECT 1 FROM pg_database WHERE datname=%s", ("recallops_test",)
    ).fetchone():
        conn.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier("recallops_test"))
        )
env = {**os.environ, "DATABASE_URL": test_url}
subprocess.run(
    ["backend/.venv/bin/alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
    env=env,
    check=True,
)
subprocess.run(
    ["backend/.venv/bin/python", "-m", "pytest", "backend/tests", "-q"],
    env=env,
    check=True,
)
