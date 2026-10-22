# Evaluation and its limits

## Investigator comparison

The original 22-case suite is retained. Before this extension, a fresh original baseline was captured in [investigator-baseline.json](investigator-baseline.json). The new [offline verification record](investigator-offline-verification.json) contains a separate 12-case comparison across the original workflow, fixed retrieval, adaptive retrieval, and adaptive retrieval without memory. Each method receives equivalent synthetic stock/source/claim inputs; seven explicit shipment confirmations are supplied fixture inputs, not autonomous agent discoveries.

In the recorded run, original-workflow exact verdict accuracy was 6/12 and fixed/adaptive variants were 12/12. Total executed tool calls were 134 (original), 202 (fixed), 152 (adaptive with memory), and 132 (adaptive without memory). The adaptive variants requested seven further operator interventions versus nine for the original. Those counts are requested questions, not measured operator time. Confirmed-route memory was actually retrieved but added overhead without changing verdict accuracy in this suite. Do not claim a learning benefit.

These comparisons disable model calls. They show the effect of evidence retrieval and deterministic verification on development-authored scenarios, not an independently established model advantage. The model functional check, when successful, is stored separately in `investigator-verification.json` with provider metadata. A successful provider trace is still not general accuracy evidence.

The UI can import a bounded independently supplied dataset using [investigator-import-example.json](../data/fixtures/investigator-import-example.json). Source, labeler, content hash, and development/held-out declarations are retained; independence and holdout integrity are not automatically certified. Keep independent evaluation cases out of implementation tuning. Imported label metadata is available only to administrators; public result views select the built-in synthetic suite.

Metrics include exact verdict accuracy, resolved/review rates, incorrect exclusions/hold classifications, all executed tool calls, additional retrieval calls, requested operator interventions, preconfirmed human setup inputs, p50/p95 processing latency, provider calls and token usage. No dollar costs or customer time savings are invented. All methods execute the persisted workflow; the old name/GTIN microbenchmarks below have different timing scope.

## Original scope-verification benchmark

The checked-in benchmark contains 22 fixed synthetic cases whose expected labels are supplied explicitly rather than computed by the matcher. They cover exact matches, unaffected lots, missing lots/dates, all-lots recalls, multiple targets, similar names, leading zeros, date limits, malformed scope and supplier conflicts. A separate persisted sequence measures two revisions: review → affected and affected → conflict while preserving a hold.

Three methods execute on the same cases:

1. Product-name baseline: case-insensitive SequenceMatcher score at least 0.5 implies a hold.
2. GTIN-only baseline: canonical GTIN equality implies a hold.
3. RecallOps: actual PostgreSQL-backed LangGraph execution and deterministic verification tools.

Calculations: precision = TP/(TP+FP); recall = TP/(TP+FN); F1 is their harmonic mean. False-hold rate = false holds / cases not labeled affected. Review accuracy = correctly requested reviews / ambiguous cases. Conflict counts as a review outcome. RecallOps timing is event creation through persisted decision; baseline timing is in-process matching, so timing columns are not an equal-cost systems comparison.

Last recorded run before final packaging: product-name precision 33.3%, recall 60%, F1 42.9%; GTIN-only precision 50%, recall 100%, F1 66.7%; RecallOps precision/recall/F1 100% on these fixtures, with no false holds and both revision transitions correct. Read `last-benchmark.json` for exact timestamps, measurements, individual predictions and run IDs.

These results demonstrate expected policy behavior on a small development suite. They do not establish production accuracy: labels were authored alongside the implementation, the data is synthetic, and there is no independent external annotator, held-out evaluation, confidence interval or store pilot yet. Real-provider functional journeys are recorded separately in `remediation-live-results.json`; they are not an independent accuracy benchmark. The standard benchmark deliberately disables model calls.

Next benchmark: independently annotate 100–200 real recall/inventory cases; include complex scope strings and adversarial supplier documents; split development/held-out cases; measure missed affected stock, unnecessary holds, review workload, conflict handling, p50/p95 latency, model failures and cost.

Run in the UI under Evaluation Lab, or `backend/.venv/bin/python scripts/benchmark.py`. This persists synthetic evaluation records; do not run it against a customer production database.

The UI also imports separately labeled JSON through `POST /api/evaluation/labeled`, recording a content hash, declared source/labeler/split and original labels. See [the import example](../data/fixtures/benchmark-import-example.json). Self-reported independence is never marked verified. Results now include confusion counts, missed-hold rate, review burden and p50/p95 latency.
