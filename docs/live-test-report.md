# Real-service integration rehearsal — 2026-10-22

**Result: 28 functional integration checks passed, including persistence after an application restart.** The government API, configured OpenAI-compatible provider, local PostgreSQL, real HTTP API, background worker, LangGraph and SSE were exercised. Inventory and supplier statements were explicitly fictional. No Aiven deployment, real retailer connection, POS action or external notification occurred.

## What was actually tested

- Rebuilt the app so the configured `openai_api_key` alias reached its container. No credentials appear in this report or the browser.
- The live RappelConso sync received 1,000 rows: **3 new immutable versions, 997 duplicates skipped, zero ingestion errors**. The response origin was `live`, not fixture fallback.
- Re-fetched official recall **17010** and compared its raw content against the stored historical scenario, ignoring only the GTIN row projection. They matched.
- Executed the historical scenario with real provider calls: known nonaffected lot → no hold; missing lot → review; warehouse confirmation → one 24-unit hold; supplier contradiction → conflict with the same hold preserved.
- Repeated an event and confirmed no duplicate run or hold. An unauthorized release request was rejected.
- Fetched a second recall directly from the current official API, **23907**, “onigiri saumon teriyaki 120g,” GTIN **3523680535589**, lot **293**, expiry **2026-10-26**. Uploaded three fictional inventory rows through CSV: 7 matching units, 9 units from an excluded lot, 3 units with no lot. The background worker correctly held 7, excluded 9, and requested review for 3.
- Submitted a fictional contradictory supplier statement through the actual supplier-evidence endpoint. Repeated submission returned the same evidence/event IDs. The worker reopened the case and preserved the seven-unit hold; SSE delivered a stored workflow transition.
- Restarted the app and retrieved all five captured runs and both active holds (24 and 7 units) from PostgreSQL. Health and frontend returned successfully; the model remained enabled.

The additional official source is [RappelConso record 23907](https://rappel.conso.gouv.fr/fiche-rappel/23907/interne). Its raw publication value was `2026-10-22T10:06:12+00:00`, ahead of the test collection clock (`09:52 UTC`). This value is preserved as supplied; it does not establish that source publication and ingestion clocks agree. The test proves retrieval and processing, not the publisher's delivery latency or full catalog coverage.

## Measured model execution

All five captured workflows used **gpt-4.1-mini-2025-04-14**, with actual provider request IDs and usage recorded. Event-to-decision timings were **2.54, 3.25, 2.21, 6.21 and 3.72 seconds**. The five captured calls consumed **6,352 reported tokens**. This excludes separate diagnostic/browser calls and other automatic runs; it is not a billing total or performance benchmark.

See [machine-readable evidence](live-test-results.json) for versions, decisions, evidence references, tool names, provider metadata and assertions. The fresh-source case remains inspectable at [the saved local incident](http://localhost:8088/incidents/f77705f1-2c6c-4789-9925-f87011b196b1). Browser testing started another replay afterward, so this prior case may no longer appear in the active replay-store dashboard; its immutable history is retained.

## Additional checks actually run

| Check | Result |
| --- | --- |
| Backend tests in isolated `recallops_test` PostgreSQL database | 54 passed |
| Frontend component tests | 4 passed |
| Isolated Chromium browser tests, real provider enabled | 7 passed in 14.5 seconds |
| Strict TypeScript / Vite production build | Passed during Docker build |
| Application restart and database persistence | Passed |

The host-side `make test` invocation was blocked by local network sandbox access. The backend suite was therefore run inside the app container against the separate test database. Pytest emitted one harmless cache-directory permission warning. The first Compose replacement encountered a transient container-name conflict during overlapping recreation; subsequent verification found the rebuilt container running, and the full integration and browser suites ran against it.

## Issues found and remaining boundaries

**Model prose is not fully grounded yet.** In the initial scenario, a model draft implied that review-only stock already had a hold. Some explanations called inventory identifiers “evidence IDs.” These are real observed wording errors, retained in the report. Deterministic decisions, evidence links and actual holds stayed correct, and the UI labels model wording unverified. Drafts still require human review. Add explicit hold state, typed evidence mappings and citation validation before treating the generated narrative as reliable.

The 28 functional checks do not score narrative factuality or establish production accuracy. Real store inventory, authentic supplier statements, customer authorization, hosted deployment, sustained load and independent benchmark labels remain untested. Local development currently has no operator token configured; production access control is not established by this local rehearsal.

## Repeat the integration rehearsal

This explicitly uses the configured model API key and can incur provider charges. It creates a new fictional replay store, archives the previous active replay store, and adds fictional test inventory. It does not overwrite official recall records.

```sh
docker compose cp scripts/live_integration.py app:/tmp/live_integration.py
docker compose exec -T -e PYTHONPATH=/app/backend app python /tmp/live_integration.py /tmp/live-test-results.json
docker compose cp app:/tmp/live-test-results.json docs/live-test-results.json
```

The reusable script runs 27 checks; the 28th check in this saved report was an additional restart/persistence verification. A future source schema or scope change can legitimately cause the rehearsal to fail rather than inventing a compatible government record.

For the browser suite with a real provider:

```sh
make e2e RUN_BROWSER_TESTS=1 BROWSER_ONLY=1 RUN_LIVE_PROVIDER_TESTS=1 PLAYWRIGHT_BROWSERS_PATH=/tmp/recallops-playwright
```

Install the isolated test browser first if needed using `INSTALL_TEST_BROWSER=1` on that command.
