#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://recallops:recallops@127.0.0.1:55432/recallops}"
if [ "${BROWSER_ONLY:-0}" != "1" ]; then
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/python scripts/smoke.py
backend/.venv/bin/python scripts/test_database.py
(cd frontend && npm test)
fi
if [ "${RUN_BROWSER_TESTS:-0}" = "1" ]; then
  if [ "${INSTALL_TEST_BROWSER:-0}" = "1" ]; then
    (cd frontend && npx playwright install chromium)
  fi
  (cd frontend && BASE_URL="${BASE_URL:-http://127.0.0.1:8088}" npm run e2e)
fi
