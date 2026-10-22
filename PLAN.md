# RecallOps — implementation status and remaining plan

Last reviewed: **2026-10-22**. This file is the source of truth for completion; an unchecked item is not being claimed as built or verified.

## Investigator extension — current implementation

The user approved parallel implementation of the competition extension. Its current checklist, verification records, and external dependencies are maintained in [investigator-status.md](docs/investigator-status.md). The historical checklist below describes the original MVP and remediation milestones; it is not the full inventory of the new investigator features.

Implemented additions: immutable delivery claims and explicit stock association; bounded evidence retrieval; targeted answers; readable decisions/progress; evidence revision and attributed resolution; frozen evidence experiments; validated retrieval hints; comparative evaluation and external-label import; new replay and unresolved companion; editable pitch; pilot plan; app-only Aiven manifest and static deployment checks.

Deployment is required by the supplied competition brief but is not provisioned: no Aiven account/project/service configuration is available in this workspace. Real customer validation and independent labels remain external work. Synthetic results do not satisfy those gates.

## Readiness decision

### Active remediation sequence

- [x] 1–2. Validate model citations; generate operational summaries/drafts exclusively from persisted facts, including actual hold state; adversarial regression tests.
- [x] 3–4. Flag clock anomalies; persist refresh history, quarantine failures, expose scan limits and backfill controls.
- [x] 5. Failed-event inspection/retry, stale-version protection and crash/concurrency regression tests.
- [x] 6. Independent-label import contract, reproducible evaluation provenance, missed-hold/review burden and latency percentiles.
- [x] 7–9. Named/scoped credentials, authenticated ordered inventory intake, reviewer assignment/closure and auditable access.
- [x] 10. Bounded official-document ingestion, conservative scope handling and provenance.
- [x] 11. Operational health/rate limits, backup/restore rehearsal, deployment preflight and end-to-end verification.
- [ ] External acceptance: independently supplied labels, real retailer/supplier credentials and documents, and hosted deployment remain external dependencies; synthetic tests cannot satisfy them.

**Current user preference: run locally without cloud provisioning.** Aiven deployment is optional and does not block running or demonstrating the application. Retain the existing deployment files for future hosting; do not require cloud credentials during local startup.

**Working local hackathon MVP: yes. Production-ready or fully deployed: no.** The core customer journey, real official data, PostgreSQL persistence, LangGraph investigation, controlled holds, decision revision and interactive UI work. Further features and external validation are listed below rather than hidden behind a blanket “done.”

Current local application: **http://localhost:8088**. Default on a fresh setup: port 8080. Existing machine port conflicts are handled by `.env`; PostgreSQL is on loopback port 55432.

## 1. Confirmed data

- [x] Verify official source and Explore API 2.1 endpoint, rather than guess the schema.
- [x] Verify dataset `rappelconso-v2-gtin-trie` through the government catalog.
- [x] Import real live data: 1,000 rows → 518 new immutable versions, 482 duplicates skipped, no ingestion errors in that run.
- [x] Preserve four genuine archived records and provenance metadata with SHA-256.
- [x] Re-fetch demo source ID `17010`; archived raw JSON matches the current official API response exactly.
- [x] Recompute archive checksum; it matches the recorded provenance.
- [x] Initial verification stored 522 official recalls locally, including the four archived fixture records; exclude synthetic evaluation sources from this count.
- [x] Keep official data separate from fictional inventory/supplier events.
- [x] Display incomplete GTIN coverage, publication time, ingestion time and last successful refresh.
- [x] Keep source-modification time null when the API does not supply it.

Evidence: [data verification](docs/data-verification.json), [source contract](docs/data-source.md), [archive provenance](data/fixtures/provenance.json).

The demo is official recall **2024-12-0201**, smoked salmon, GTIN **3760099533007**, lot **24326020**, expiry **2024-12-20**. The **18 known-lot units, 24 unknown-lot units, warehouse update and supplier correction are synthetic**. It is a historical scenario, not current store stock.

## 2. Implemented end-to-end workflow

1. **Ingest:** fetch official records or import an archived JSON snapshot. On network failure use the labeled local fixture fallback.
2. **Version:** validate identifiers, preserve raw source and URLs, parse GTIN/lot/date tuples, deduplicate stable IDs/content hashes, append immutable versions.
3. **Inventory:** validate CSV rows, preserve identifiers as strings, persist product/lot/date/quantity/supplier records, report row-level errors.
4. **Detect:** find matching active-store GTINs and existing incidents changed by updated recall evidence; enqueue idempotent PostgreSQL events.
5. **Investigate:** LangGraph loads the pinned recall version and stock, retrieves prior decisions and supplier evidence, and runs deterministic GTIN/lot/date checks.
6. **Resolve uncertainty:** retrieve more stored evidence; optionally use an OpenAI-compatible model for investigation planning and wording. Without credentials, label deterministic fallback honestly.
7. **Respond:** exact verified match → internal hold; complete exclusion → unaffected; missing/contradictory scope → human review; existing holds remain protective.
8. **Persist:** save decisions, relational evidence links, tool trace, node state, action outcomes, timestamps, latency and audit history.
9. **Present:** stream progress to the UI; expose real records in incident details, the graph and replay comparisons.
10. **Reconsider:** new inventory, supplier or official-version events trigger investigation again. Only an authorized human with a reason can release a hold. Communications remain drafts.

Detailed architecture and boundaries: [architecture.md](docs/architecture.md).

## 3. Completed implementation checklist

### Frontend and product design
- [x] Responsive teal/sage command center, navigation, loading/error/empty states.
- [x] Dashboard with backend-derived counts, actual activity and simulation entry.
- [x] Search/filter incidents and open a persisted detail workspace.
- [x] Search/paginate inventory, download sample CSV, import and show row errors.
- [x] Incident decisions, raw source, tool trace, evidence, draft and human review controls.
- [x] Time Machine: persist and replay initial review → 24-unit hold → conflict with hold preserved.
- [x] Historical decisions side by side; stage selection and changes explained.
- [x] Clickable graph: official recall, GTIN, target, stock, evidence, decision and hold records.
- [x] Evaluation Lab with measured comparison and case-level results.
- [x] Data/settings page, mode switch, service status and session token input.
- [x] Desktop and mobile browser journey tests; screenshots reviewed.

### Backend, data and safety
- [x] FastAPI/Pydantic API, SQLAlchemy, PostgreSQL and Alembic migrations.
- [x] All requested core tables plus decision-evidence, replay and source-status tables.
- [x] Database provenance immutability and required decision evidence.
- [x] Live API, historical snapshot script and offline replay.
- [x] Conservative GTIN/lot/date matching with leading-zero preservation and unsupported-scope review.
- [x] Stateful LangGraph execution and validated, store-scoped tools.
- [x] PostgreSQL outbox, duplicate suppression, bounded retries and serialized processing.
- [x] Idempotent holds and preservation after supplier conflict or official scope revision.
- [x] Operator-authorized release with recorded reason; no automatic release.
- [x] Protected mutations/business reads and public-demo isolation checks.
- [x] SSE progress and consistent API error responses.
- [x] Configurable model client with explicit no-key/provider-error fallback.

### Verification and delivery
- [x] **71 backend tests pass**, including imports, constraints, immutability, source changes, duplicates, authorization, fallback, supplier intake and safety invariants (2026-10-22 live-integration rehearsal).
- [x] **4 frontend component tests pass.**
- [x] **9 isolated Chromium end-to-end tests pass** on the rebuilt app, including a real provider connection, supplier reassessment, full replay/graph/inventory journey, filters and responsive navigation (2026-10-22).
- [x] Real 22-case synthetic benchmark plus 2 stateful revision transitions executes through the persisted workflow.
- [x] React strict TypeScript production build passes.
- [x] Multistage Docker image builds; app and PostgreSQL containers report healthy.
- [x] Updated frontend dependency installation reported zero npm advisories at verification time.
- [x] Local setup, environment example, API, architecture, source, benchmark and demo documentation.
- [x] Aiven Runtime request template and PostgreSQL TLS/deployment instructions prepared.

## 4. Remaining work, in priority order

### P0 — local demonstration validation
- [x] **Separate model suggestions from operator responses.** New run summaries and copyable supplier drafts are generated from recorded decisions and explicit hold state. Model suggestions remain in the execution trace, including for historical runs. A regression test proves misleading model prose cannot alter holds or enter the operator draft.
- [x] **Real model-provider connection and functional investigation test.** The configured API key successfully called `gpt-4.1-mini-2025-04-14`. Five captured real-provider workflows passed with persisted request IDs, usage and tool traces. Live government ingestion and a second newly fetched recall were tested through CSV import, the background worker and supplier intake. All 27 integration checks passed; see [live test report](docs/live-test-report.md) and [captured results](docs/live-test-results.json).
- [x] **Model narrative grounding.** Operational responses use recorded decisions, actual per-lot holds and relational evidence citations. Invalid model references are flagged/quarantined; model prose never becomes an operational claim. Adversarial tests and the 37-check live regression passed. See [remediation report](docs/remediation-report.md).
- [ ] **Demo rehearsal on the presentation machine.** Run the three-minute script with networking disabled for replay; confirm fonts/layout, stage reset and a saved benchmark. Acceptance: repeatable demonstration within three minutes.

### Optional cloud deployment — only when hosting is requested
- [ ] **Aiven staging deployment (optional for local use).** Connect the GitHub repository and existing PostgreSQL, supply a project CA/verified TLS URL and secrets, deploy, migrate and rerun the journey after restart. Acceptance: verified hosted URL, persistent data, working auth/health/SSE. Requires account access and explicit approval for any paid provisioning.

### P1 — make the live investigation useful beyond the controlled replay
- [x] **Supplier-evidence intake form/API.** Operator-submitted evidence has source metadata, inventory-lot association, deduplication and an outbox event. Verified the real HTTP endpoint/background worker with synthetic supplier statements: contradictions preserve holds. Isolated database tests cover live-mode behavior and authorization. No real supplier account or connector has been tested.
- [x] **Supplementary official documents.** Official PDF archive, HTTPS host/field allowlist, bounded child-process extraction, SHA-256/download verification and UI are implemented. Real recall 17010 poster extraction passed. Text remains unverified and never silently establishes a lot exclusion; OCR/complex prose require review.
- [x] **Ingestion operations.** Refresh history, raw rejected-record quarantine, query/page trace, truncation/backfill controls and source-clock flags are implemented. Bounded scans never infer withdrawal or release stock. Full-catalog coverage is not claimed.
- [x] **Worker recovery operations.** Failed-event/retry UI, sanitized errors, audit reasons, stale-source supersession and store locks are implemented. Injected crashes after action commit and concurrent stock sequence tests preserve holds. Native checkpoint continuation and exhaustive multi-replica chaos testing remain future work.
- [ ] **Broader independent evaluation.** Have a separate reviewer label 100–200 representative cases; hold some out from development. Acceptance: report quality, missed holds, review burden, p50/p95 latency and revision success without tuning on held-out labels.
- [x] **Named reviewers and resolved review states.** Named scoped credentials, ownership, acknowledgement, current-run/evidence-based closure, reopening and immutable supplier correction chains are implemented and tested.

### P2 — before a customer production pilot
- [x] Named hashed credentials with admin/operator/integration/viewer roles and explicit store isolation, including SSE. Enterprise SSO and full user lifecycle remain future work.
- [x] PostgreSQL-backed mutation limits, bounded request bodies including chunked uploads, origin checks and role guards. Internet-scale abuse protection still requires hosted reverse-proxy/network validation.
- [x] Private backup scripts, verified isolated restore, worker heartbeat/alerts UI/API and documented retain-all provenance policy. Offsite backup scheduling and external alert delivery await hosting.
- [x] Local 120-request concurrency smoke load and concurrent intake/stale-version regression tests. Sustained production load and exhaustive multi-replica ordering tests remain deployment gates.
- [ ] Supplier/POS connectors only with scoped credentials and explicit action approval.
- [ ] Notification approval/send lifecycle, delivery status and audit. Current drafts are intentionally unsent.
- [ ] Native LangGraph checkpoint resume if exact node-level recovery is needed; current recovery reruns the persisted workflow idempotently.
- [ ] Expand beyond the GTIN-only dataset and assess checksum/date/complex-lot edge cases.

## 5. Evaluation interpretation

The latest recorded synthetic fixture run reports RecallOps precision/recall/F1 of 100%, zero false holds, correct ambiguity review and 2/2 revisions. Baseline results and timings are in [last-benchmark.json](docs/last-benchmark.json). **These are small development-suite results, not production accuracy or independent validation.** Baseline matching latency and full workflow latency also measure different amounts of work.

## 6. Remaining external acceptance and later product work

1. Obtain 100–200 separately reviewed recall/inventory cases; import them through Evaluation Lab. Do not relabel development fixtures as independent evidence.
2. Connect an authorized retailer export/webhook and genuine supplier documents to the new scoped intake contracts. A vendor-specific connector requires its API contract and credentials.
3. Before public hosting, set production mode, a strong bootstrap token, HTTPS and verified PostgreSQL TLS; run the preflight and staged end-to-end checks. The current loopback development environment deliberately remains open for local demonstration.
4. Configure offsite scheduled backups and external monitoring; validate sustained load and multi-replica fault recovery on the target host.
5. Optional further work: enterprise SSO/user lifecycle, OCR/complex scope interpretation, native graph checkpoint resume, and an approved notification send lifecycle. None is silently claimed complete.
6. Rehearse the local offline demonstration on the actual presentation machine; optional Aiven deployment still requires account access and paid-service authorization.

Detailed per-issue outcomes and measurements: [remediation report](docs/remediation-report.md). Operator/API/backup instructions: [operations guide](docs/operations.md).

Do not provision billed services, claim a deployed URL, describe a model call as real without a trace, or treat synthetic store data as government evidence.
