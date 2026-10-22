#!/bin/sh
set -eu
cd /app
alembic -c backend/alembic.ini upgrade head
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "${PORT:-8080}" --workers 1
