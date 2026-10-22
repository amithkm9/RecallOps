# Operating the revised local application

The current implementation is a local, tested pilot foundation. The default Compose service is bound to loopback. Aiven remains optional. Hosted deployment, real retailer accounts and independently reviewed labels have not been supplied or verified.

## Model grounding and safety

The model chooses allowlisted retrieval tools. Its free-text suggestions are preserved as unverified trace data and never used as operator summaries, stock-match proof, or copyable supplier drafts. Structured citations must reference supplied evidence IDs; invalid references quarantine the narrative and invalid structured citations revert to the safe retrieval plan. Operational drafts are rendered from persisted decisions, actual active holds and relational evidence links. This controls the observed false-hold wording and incorrect citation problems without pretending unrestricted model prose is factually verified.

## Source operations

Open **Data & settings → Operations & access → Source history**. Each refresh records timestamps, source/fallback origin, received/new/duplicate counts, query pages, truncation and errors. **Inspect refresh** shows rejected original records. **Scan next page** advances the bounded historical scan. The API limits a page window to the Explore endpoint's first 10,000 rows; use the historical snapshot importer for larger archives. A bounded scan is never described as full coverage, and missing records never withdraw a recall or release stock.

Incident details flag official publication/modification times more than five minutes ahead of their collection timestamp. Raw official times remain unchanged; clock warnings do not become lot-scope evidence.

Compose now passes `SOURCE_REFRESH_SECONDS`, `SOURCE_MAX_RECORDS`, `WORKER_ENABLED`, `PUBLIC_DEMO`, `ENVIRONMENT`, `ALLOWED_ORIGINS` and `MUTATION_LIMIT_PER_MINUTE` into the app. Set refresh seconds to zero for manual-only ingestion, then recreate the app. The first automatic refresh still waits for the configured interval, allowing offline startup.

## Recovery and monitoring

**Worker recovery** displays queued/processing/failed events, attempts, sanitized failure types and the worker heartbeat. An authorized operator can retry a failed event with a reason. Retries preserve committed decisions and holds. Stale official-version deliveries in live mode are superseded by an event for the current version; stock update sequence numbers reject old or conflicting deliveries. PostgreSQL advisory locks serialize mutations and investigations for each store.

`GET /api/operations/health` is administrator-protected. It reports failures, pending counts, oldest pending age, worker heartbeat and actionable alerts. External monitoring should alert on a non-`ok` result, network errors, or absent heartbeat; no external notification integration is configured or sent by this implementation. `/api/health` remains the simple PostgreSQL/container liveness endpoint.

## Named access and store boundaries

Before public hosting, set `ENVIRONMENT=production` and an `OPERATOR_TOKEN` with at least 32 randomly generated characters through the host's secret manager. Production startup rejects a short bootstrap token or absent authentication unless explicitly configured as an isolated public demo. Enter the bootstrap token under Data & settings.

Under **Access & stores**, create named credentials. The raw token is shown once and only its SHA-256 digest is stored. Save it securely, then hide it. Credentials can be revoked. Roles:

- **admin:** global administration, source sync, credential management and evaluation.
- **operator:** reads, investigations, supplier evidence and human review within assigned stores.
- **integration:** scoped inventory/supplier event submission; no hold release or administrative mutations.
- **viewer:** scoped reads; all mutations rejected.

Scopes apply to inventory, incidents, evidence, history, dashboards and SSE. Non-admin replay creation/reset is blocked because it replaces the active demo workspace. Access is bearer-token based; SSO, password recovery, session management and organizational membership are not implemented. Do not equate scoped service credentials with a complete enterprise identity system.

Cross-origin mutations are rejected unless the origin matches the application or `ALLOWED_ORIGINS`. PostgreSQL-backed mutation budgets default to 120 per credential/client bucket per minute. Request bodies are bounded to 2.1 MB, including chunked uploads. CSV retains its stricter 2 MB validation. Deploy behind HTTPS and a reverse proxy with appropriate network-level limits.

## Ordered inventory integration

Create a store with admin `POST /api/stores` (`{"name":"Your store"}`), then issue an integration credential scoped to its returned ID. Submit absolute stock snapshots through:

```http
POST /api/stores/{store_id}/inventory-events
Authorization: Bearer <scoped integration token>
Content-Type: application/json

{
  "external_id": "warehouse-stock-record-123",
  "sequence": 1,
  "stock": {
    "sku": "YOUR-SKU",
    "product_name": "Your inventory description",
    "gtin": "3760099533007",
    "lot": "YOUR-LOT",
    "quantity": 24,
    "supplier": "Your supplier",
    "expires_on": "2026-12-20"
  }
}
```

The example inventory is fictional. A retry with identical sequence/content returns the same receipt; conflicting content for that sequence or a lower sequence returns 409. Increase sequence for each change to the same external stock record. Do not mix CSV and API ownership of the same stock identity without coordinating updates. Held stock cannot have its identity rewritten or quantity reduced below the hold. Report a contradiction as supplier evidence for human review instead. This is a working generic intake contract; vendor-specific POS/warehouse adapters still require real credentials and field mappings.

## Review ownership and corrections

**Assign to me** records the named operator. Acknowledgement, explicit release, closure and reopening all require a reason. Closure requires the latest completed run, its contributing evidence, no outstanding/failed events, no active holds and no affected/uncertain decisions. New evidence automatically reopens a closed review. A supplier correction can explicitly supersede an earlier statement from the same supplier for the same stock; both remain immutable in history. A correction alone never releases a hold.

## Official attachments

Open **Evidence & execution → Official attachments**. Retrieval accepts only recognized document fields from the stored official record and allowlisted HTTPS hosts; redirects and arbitrary/private URLs are not followed. PDFs are limited to 2 MB and 20 pages. Text extraction runs in a child process with CPU, memory and wall-clock limits. Scans without text are marked `needs_ocr`; unsupported/failed documents remain for human review. Extracted text never replaces the deterministic structured recall scope or establishes an exclusion. Every PDF is archived with source/version, checksum and original bytes, and can be downloaded after incident authorization.

The parser follows [pypdf's text extraction API](https://pypdf.readthedocs.io/en/6.21.1/user/extract-text.html). Text extraction is not OCR or proof of scope correctness. The live poster for official recall 17010 was downloaded, checksum-verified and its one page extracted after correcting the child-process module path.

## Independent evaluation intake

Evaluation Lab accepts JSON with `source`, `labeler`, `split` and 2–200 cases. See [the import example](../data/fixtures/benchmark-import-example.json). Each case supplies its expected label before execution; disagreements are preserved. The run saves a dataset SHA-256, declared labeler/split, predictions, raw confusion counts, missed-hold rate, review burden and p50/p95 latency. A declaration of `held_out` is not proof of independence. The standard suite and uploaded evaluations disable model calls, avoiding accidental provider costs. Real-model functional checks are separate.

## Backups, retention and preflight

```sh
bash scripts/backup.sh
bash scripts/restore_drill.sh backups/<backup-file>.dump
PYTHONPATH=backend backend/.venv/bin/python scripts/preflight.py
```

Backups are private local files excluded from Git. The restore drill always creates a separate database and leaves it for inspection; it never restores over the app database. Encrypt/copy backups off the host and schedule them using your hosting provider before a customer pilot. The verified local restore retained schema 0003, 284 decisions, 88 active holds (including synthetic evaluation/demo data), all six immutable-provenance triggers and zero orphan evidence links.

Retention defaults to retaining all safety provenance and business history; no automatic purge of recalls, evidence, decisions, holds or audit records is implemented. Request-rate counters older than two minutes are removed. Define customer retention and backup expiry requirements before any deletion policy is introduced.

The preflight checks production mode, strong bootstrap authentication, database TLS for nonlocal databases, migrations and worker configuration without displaying secrets. The current local development environment correctly fails the two production-only checks; it is not configured for public exposure. A successful preflight would still not prove a hosted rollout, offsite recovery, independent evaluation or real-business integration.
