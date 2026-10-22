# API contract

OpenAPI documentation: `/docs`; JSON schema: `/openapi.json`. The primary compatibility routes are `/api/...`; equivalent versioned paths are `/api/v1/...`. Responses use Pydantic schemas. Errors have `{"error":{"code":...,"message":"..."}}`.

Investigator delivery imports, claim validation/revision, targeted answers, review resolution, downloads, frozen experiments, demonstration, and comparative evaluation are documented in the [investigator API guide](investigator-guide.md#api-reference). `POST /api/investigator/evaluation` optionally accepts `dataset` using [this external-label example](../data/fixtures/investigator-import-example.json). Imported comparison metadata is administrator-only; public readers see only the built-in synthetic suite. Concurrent comparisons return 409 instead of queueing behind a long-held lock.

| Operation | Route |
|---|---|
| Health/config | `GET /api/health`, `GET /api/settings` |
| Dashboard | `GET /api/dashboard?mode=replay` |
| Source data | `GET /api/recalls`, `GET /api/recalls/{id}` |
| Synchronize | `POST /api/recalls/sync` with `{"source":"live"}` or `snapshot` |
| Inventory | `GET /api/inventory?mode=live&search=&page=1` |
| CSV | `GET /api/inventory/sample`; multipart `POST /api/inventory/import` with `file` and `mode` |
| Incidents | `GET /api/incidents?mode=replay&status=&search=` |
| Incident workspace | `GET /api/incidents/{id}` |
| Model connection | `POST /api/settings/model-check`; one real request using fictional data; reports model, latency, provider usage and safe error details |
| Supplier statement | `POST /api/incidents/{id}/supplier-evidence`; records evidence and queues reassessment; returns HTTP 202 with evidence/event IDs |
| Investigation | `POST /api/incidents/{id}/investigate` with optional `idempotency_key` |
| Provenance | `GET /api/incidents/{id}/evidence`, `GET /api/incidents/{id}/history` |
| Human decision | `POST /api/incidents/{id}/review` with `action`, `reason`, optional `hold_id` |
| Replay | `POST /api/demo/seed`, `POST /api/demo/replay/start` |
| Replay advance | `POST /api/demo/replay/next` with `replay_id` and `expected_step` |
| Replay retrieval | `GET /api/demo/replay/latest`, `GET /api/demo/replay/{id}` |
| Evaluation | `POST /api/evaluation/run`, `GET /api/evaluation/latest` |
| Progress | `GET /api/events/stream` as Server-Sent Events |

Send `Authorization: Bearer <OPERATOR_TOKEN>` for protected operations. All human review actions require a valid configured token, including in development. Production read/write access is authenticated except controlled public-demo routes. The UI stores the token only in sessionStorage; model credentials remain server-side.

A manual investigation request enqueues an event; the worker executes it. SSE emits stored audit transitions with event IDs and supports `Last-Event-ID`. Replay injection waits for the same processing path to finish for deterministic playback. Repeating the same `expected_step` does not advance a replay twice.

CSV columns: `sku,product_name,gtin,lot,quantity,supplier,expires_on`. UTF-8, 2 MB maximum, 10,000 rows maximum. Valid rows import; rejected rows report line numbers and errors. Inventory identity is store + SKU + normalized lot. Repeated identical imports do not create duplicate lots. Held stock cannot be reduced below the active hold or silently change product identity through CSV.

Supplier statements require `inventory_lot_id`, `supplier`, `lot`, `reference`, and `notes`; `source_url` is an optional HTTP(S) provenance link, not fetched content. The lot must belong to this incident’s store and be relevant to the recall. Identical normalized submissions return the same evidence/event IDs. Replay submissions remain synthetic. Public-demo submissions require operator authorization; ordinary development follows the existing local-access policy. Statements never overwrite warehouse identity or release a hold.

## Operational and integration additions (schema 0003)

- `GET /api/operations/refreshes`, `GET /api/operations/refreshes/{id}/rejections`: administrator source history/quarantine. Sync accepts `start_offset` (100-row increments, up to 9900).
- `GET /api/operations/events`, `POST /api/operations/events/{id}/retry` with a reason: scoped event recovery.
- `GET /api/operations/health`: administrator heartbeat, queue health and alerts.
- `GET/POST /api/operations/credentials`, `POST /api/operations/credentials/{id}/revoke`: administrator named/scoped credentials; token shown once.
- `GET/POST /api/stores`, `POST /api/stores/{id}/inventory-events`: scoped ordered inventory snapshots.
- Review actions additionally support `assign`, `close`, `reopen`; closure requires `expected_run_id` and contributing `evidence_ids`.
- Supplier evidence optionally includes `supersedes_evidence_id`; original statements remain immutable.
- `POST /api/incidents/{id}/documents` with an official attachment field; protected `GET /api/incidents/{id}/documents/{evidence_id}` downloads preserved bytes.
- `POST /api/evaluation/labeled`: validated externally labeled JSON, provenance and measured metrics.

All additions also have `/api/v1` aliases. See [operating instructions](operations.md) for payloads, roles, limits and boundaries.
