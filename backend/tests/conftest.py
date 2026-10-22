import os

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://recallops:recallops@127.0.0.1:55432/recallops_test",
)
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ.setdefault("SOURCE_REFRESH_SECONDS", "0")
# Routine tests must never spend real provider credits from the developer's .env.
os.environ["LLM_API_KEY"] = ""
from app.core.config import settings
from app.core.database import SessionLocal


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session
        session.rollback()


@pytest.fixture
def fixture_dir():
    return settings.fixture_dir
