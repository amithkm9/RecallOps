#!/usr/bin/env bash
# Restores to a fresh, separate database. Never overwrites the application database.
set -euo pipefail
cd "$(dirname "$0")/.."
backup_file="${1:?Usage: bash scripts/restore_drill.sh backups/filename.dump}"
test_database="recallops_restore_$(date -u +%Y%m%d%H%M%S)"
docker compose cp "$backup_file" db:/tmp/recallops-restore.dump
docker compose exec -T db createdb -U recallops "$test_database"
docker compose exec -T db pg_restore -U recallops --exit-on-error --no-owner -d "$test_database" /tmp/recallops-restore.dump
docker compose exec -T db psql -U recallops -d "$test_database" -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version' -c 'SELECT count(*) AS decisions FROM decisions' -c 'SELECT count(*) AS orphan_evidence_links FROM decision_evidence de LEFT JOIN evidence e ON e.id=de.evidence_id WHERE e.id IS NULL'
echo "Restore completed in $test_database. Retained for inspection; production was not modified."
