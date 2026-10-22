# Remediation results — 2026-10-22

Implemented the code changes behind the eleven reviewed issue areas, with explicit external acceptance boundaries. The app remains available locally on port 8088. No cloud service was provisioned or deployed.

| Area | Implemented and verified | Remaining boundary |
| --- | --- | --- |
| 1. False hold claims in model wording | Operational drafts and summaries use persisted facts; actual per-lot hold state is rendered explicitly. Real-provider regression passed. | Free model suggestions remain unverified trace content. |
| 2. Evidence references | Typed evidence mappings, validated model citation IDs, quarantine flags, operational references from decision-evidence links. | No claim that arbitrary model prose has been semantically proven. |
| 3. Clock discrepancy | Source-clock warnings separate from scope warnings; original timestamps preserved. | Publisher clocks cannot be corrected by this app. |
| 4. Ingestion history | Refresh table, rejected raw records, scan trace, pagination/backfill control, truncation and conservative withdrawal policy. | Bounded ingestion is not the complete recall catalog. |
| 5. Recovery | Failed-event list/retry, audit reasons, sanitized errors, stale-version supersession and store serialization. | Native checkpoint-level continuation and exhaustive multi-replica chaos testing remain outside this pass. |
| 6. Evaluation | External label import, provenance/hash, retained disagreements, missed holds/review burden/p50/p95. | An independent reviewer must still supply real held-out labels. |
| 7. Authentication | Named hashed credentials, roles/store boundaries, revocation, production startup guard, scope tests. | SSO/user lifecycle and public hosting remain unimplemented/unverified. |
| 8. Business intake | Scoped ordered/idempotent stock-event API plus supplier corrections. Concurrent ordering tested. | Real vendor credentials, mappings and records are still needed. |
| 9. Human review | Ownership, acknowledgement, guarded closure/reopening, named audit actors, immutable supplier correction chains. | Customer-specific operational procedures need validation. |
| 10. Attachments/scopes | Safe official PDF retrieval/archive, bounded extraction, checksum download and review labels. | OCR and automatic interpretation of arbitrary complex prose are not claimed. |
| 11. Operations | Heartbeat/alerts endpoint and UI, body/origin/rate guards, backup/restore scripts, restore drill, preflight and small HTTP load check. | Hosted HTTPS, offsite backups, external monitoring delivery and sustained production capacity require deployment validation. |

## Results actually obtained

- **71 backend tests passed** in isolated PostgreSQL, including adversarial model output, crashes after action commit, stale versions, concurrent inventory events, access boundaries and review lifecycle.
- **4 component tests passed.**
- **9 isolated Chromium browser tests passed**, including real provider connection, full workflow, supplier evidence, source/recovery UI and invalid benchmark feedback.
- **37 live integration assertions passed**, with real government ingestion and real `gpt-4.1-mini` workflows. The new assertions validate operational draft evidence IDs and recorded hold state. Latest ingestion: 1,000 rows, zero new versions, 1,000 deduplicated, zero errors; source origin was live. [Captured run](remediation-live-results.json).
- **Official PDF download and extraction passed:** 267,289 bytes, one extracted page, preserved-download SHA-256 matches. Extracted text stays unverified. [PDF result](remediation-document.json).
- **22-case development benchmark + two revision transitions** completed through PostgreSQL/LangGraph without model charges. RecallOps p50 21.094 ms, p95 51.021 ms; missed-hold rate 0 on these fixtures; review burden 36.36%. These are development-suite measurements, not independent production accuracy. [Benchmark](last-benchmark.json).
- **Backup restored successfully to a separate database**, with 284 decisions, 88 active holds, six provenance triggers and zero orphan evidence links. [Restore record](remediation-restore.json).
- **120/120 HTTP reads succeeded at concurrency 8**, p50 34.29 ms and p95 66.63 ms on the local machine. This is a small smoke load, not sustained production capacity. [Load result](remediation-load.json).
- Strict TypeScript/Vite build, multistage Docker build and schema migration 0003 passed.

The live test's warehouse and supplier changes were fictional. Government records and model calls were real. No supplier email or POS action occurred.

## Failures discovered and corrected during this work

1. The initial migration used PostgreSQL's reserved `window` identifier without quoting. Renamed it `bucket_window`; migration and suite passed afterward.
2. A missing `Event` import affected the new review-closure branch. Added it and tested both rejected and successful closure.
3. Initially treating every attached product-list link as incomplete scope incorrectly changed the archived demo's explicit excluded lot to review. Removed that blanket assumption. Explicit structured scope remains authoritative; genuinely unparseable scope stays reviewable.
4. PDF extraction initially failed inside the deployed app because Uvicorn's module path was not inherited by the child process. Passed an explicit backend module path and added a different-working-directory regression. The first failure remains recorded in [the initial PDF result](remediation-document-initial.json); the repeat live download/extraction passed.

Current production preflight intentionally reports `ready: false`: local development mode is active and no production bootstrap token is configured. Local access remains loopback-only. This is an explicit deployment prerequisite, not a claim that the app is already safe to expose publicly.

See [operating instructions](operations.md) and [PLAN.md](../PLAN.md) for the remaining external acceptance gates.
