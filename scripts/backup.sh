#!/usr/bin/env bash
# Local Compose backup. The archive contains business data; keep it private.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p backups
backup_name="recallops-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -U recallops -d recallops --format=custom -f /tmp/recallops-backup.dump
docker compose cp db:/tmp/recallops-backup.dump "backups/$backup_name"
chmod 600 "backups/$backup_name"
echo "Backup saved to backups/$backup_name"
