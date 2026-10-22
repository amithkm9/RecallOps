# Supplier evidence and live verification

Implemented and verified locally on 2026-10-22. App: http://localhost:8088.

## What was added

**Supplier statement intake.** Open an incident → Evidence & execution → Add supplier evidence. Choose the inventory lot, supplier name, stated lot, document/message reference, and notes. An optional HTTP(S) link records provenance; the application does not fetch or verify the linked document. Save & reassess appends immutable evidence, queues a new investigation, and reports progress. Duplicate submissions reuse the evidence and event. Supplier statements do not overwrite warehouse stock or release holds. The evidence view includes a readable supplier/lot/reference summary.

**Model connection check.** Data & settings → Test model connection makes one real request with fictional data through the same planner used by investigations. It reports success/failure, model, latency and check time. The backend records provider request IDs and usage without logging credentials. Authentication, quota, model/request and connectivity errors produce safe messages.

**Configuration compatibility.** The supplied lowercase `openai_api_key` was not previously passed into the app. Configuration now accepts `LLM_API_KEY` and `OPENAI_API_KEY` case-insensitively; Docker Compose explicitly supports both uppercase names and lowercase `openai_api_key`. Credentials remain on the server. Routine unit and smoke tests disable external model calls; live checks are explicit.

**Factual operator responses.** Live testing exposed model wording that could imply a hold on review-only stock. New summaries and copyable drafts now use recorded decisions and actual hold state, while model suggestions stay in the planner trace/state. The UI also separates model prose in older saved runs from the main response. Planning context now includes typed evidence mappings and active holds. This reduces exposure to unsupported suggestions; it is not a claim that model prose is fully grounded or citations are automatically validated.

The existing provider integration uses JSON mode plus Pydantic validation. JSON mode does not by itself guarantee a matching schema; see [official OpenAI structured output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat).

## Verification performed

- Production TypeScript/Vite build and local Docker rebuild passed.
- 57 backend tests passed in the separate `recallops_test` database, including supplier intake, access control, idempotency, hold preservation, provider failures and misleading model prose.
- Four frontend component tests passed.
- Seven browser tests passed with real provider calls enabled, including supplier submission and Settings diagnostics.
- API smoke checks and the 22-case synthetic benchmark passed. The benchmark remains a small development suite, not a production accuracy estimate.
- Real `gpt-4.1-mini` requests returned validated plans and provider metadata.
- A live official-source refresh returned 1,000 duplicate rows, zero record errors, and `origin=live`; no archived fallback was used in this check.
- A fetched official recall was matched to three explicitly fictional units in replay mode. The background worker created a hold. A fictional supplier contradiction triggered a second real model-assisted investigation and preserved the same three-unit hold. Repeated submission returned the same evidence/event IDs.

The captured source and workflow identifiers, model metadata, and results are in [live-verification.json](live-verification.json). Additional contemporaneous integration evidence is in [live-test-report.md](live-test-report.md); that report includes a separate fresh-food case and restart/persistence checks. Historical reports retain their original observations.

The test case is [available locally](http://localhost:8088/incidents/15e44dd6-db0a-478e-b3bb-77965e348d8b). Resetting the demo archives an active replay workspace; direct links to recorded cases remain available. The official recall is real; stock quantities and supplier claims in these checks are fictional. No supplier messages were sent.

## Repeat the check

The live check uses the configured API key, incurs provider usage, synchronizes the official source, and adds clearly labeled test stock to the active replay workspace. It does not import fictional stock into live-mode business inventory.

```sh
backend/.venv/bin/python scripts/verify_live.py --url http://127.0.0.1:8088
```

Routine local validation:

```sh
make e2e
cd frontend
RUN_LIVE_PROVIDER_TESTS=1 BASE_URL=http://127.0.0.1:8088 PLAYWRIGHT_CHANNEL=chrome npm run e2e -- --workers=1
```

The browser command explicitly enables the connection-check test. Browser investigations also use the server's configured model, if enabled. For an entirely offline test, run against a server without a model key.

## Next product investments

1. Case ownership and review deadlines, so a safety manager can coordinate action across operators.
2. Source-refresh history and failed-event recovery, so incomplete data and stalled work are visible.
3. Authorized real retailer inventory and authentic supplier records to validate the workflow with actual customers.

Current limits include shared operator credentials, no supplier or POS connector, append-only supplier statements without a supersession workflow, and no validation that a submitted source link proves the claim. Conflicting statements continue to require human review.
