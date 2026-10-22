# RecallOps Investigator implementation status

Reviewed 2026-10-22. This records the approved parallel build, separating implemented software from external deployment and customer-validation work.

| Planned item | Delivered result | Status |
|---|---|---|
| Customer and job | Grocery operator, shipment association, batch-specific recall investigation; operator guide and pitch | Implemented positioning; customer demand unvalidated |
| Before-change baseline | Fresh original 22-case baseline retained in `investigator-baseline.json` | Recorded |
| Stock/delivery association | CSV imports; SKU, GTIN, full quantity and explicit operator association; candidates never establish shipment identity | Implemented and tested |
| Traceable evidence claims | Original bytes, SHA-256, row/page excerpts, append-only acceptance/rejection and attribution | Implemented and tested |
| Bounded investigator | Available scoped actions, optional model selection, no repeated action keys, call/time/context bounds, labelled fallback, durable progress | Implemented and tested |
| Document reading | Real labelled text-PDF extraction through isolated worker; ambiguous repeated batches and scans require review | Implemented and tested; arbitrary OCR not included |
| Targeted operator question | Candidate delivery choice or sourced physical label observation; reassessment follows | Implemented and tested |
| Readable investigation | Conclusions, open gaps, source age, actual tool results, progress, model mode and stop reason | Implemented and browser-tested |
| Decision changes | Before/after conclusions linked to saved evidence; original warehouse record retained | Implemented and tested |
| Human review | Attributed resolution guarded by reviewed run, current live recall version and settled work; release remains separate | Implemented and tested |
| Freshness/recovery | Existing refresh/rejection/retry controls reused; persisted-decision retry now finishes frozen outcome | Implemented and regression-tested |
| Comparative evaluation | Original/fixed/adaptive/memory removal, genuine confirmed historical hints, total tools and human setup costs | Implemented and measured on 12 synthetic cases |
| External-label intake | Bounded JSON schema, source/labeler/hash/split declarations, private imported metadata | Implemented; independent labels not supplied |
| Aiven hosting | App-only manifest, deployment guide and credential-free static checker | Prepared, not deployed; account/service configuration missing |
| Pitch and first users | One editable slide, five-minute demo, supervised pilot recruitment and measurement plan | Artifacts delivered; no customer outreach performed |
| Evidence experiment | Frozen source/stock/accepted-claim snapshots; source+validation dependencies; no operational changes | Implemented and tested |
| Reusable memory | Store-scoped confirmed retrieval routes; stale/rejected hints excluded; previous batch facts not reused | Implemented; no learning/accuracy improvement established |

## Verification

- Full backend regression run: **120 passed**, including real PDF extraction, permissions, provenance, scoped evidence experiments, repeated comparison locks, holds, retry snapshots, model response contracts and baseline behavior.
- Frontend production build: passed.
- Frontend component/unit tests: **12 passed**.
- New real Chrome end-to-end tests: **4 passed**, covering confirmation → hold → experiment → resolution → evidence revision, comparative evaluation, external labels, and original replay regression. Desktop/mobile screenshots were visually inspected.
- Static deployment checks: passed with no secrets loaded and no services provisioned.
- `investigator-offline-verification.json`: five functional invariants passed, plus persisted four-method comparison.
- `investigator-verification.json`: real `gpt-4.1-mini-2025-04-14` selected `search_delivery_records`; one successful provider call (968 input / 47 output tokens), all five functional checks passed. An earlier malformed action response was diagnosed and the prompt contract corrected without weakening schema validation.
- Local application rebuilt and health-checked at `http://localhost:8088`; eleven investigator routes available. Both real text-PDF tests also passed inside the Linux application container.
- `investigator-app-comparison.json`: offline comparison populated in the local application's Evaluation Lab; no provider calls or live business data were used.

All test/provider cases use fictional business data. The official archived replay recall remains genuine and historical. The dedicated browser database is separate from both the local application and unit-test databases.

## Measured limits

On the 12 development-authored scenarios, the original workflow returned six exact expected verdicts; fixed and adaptive retrieval returned twelve. Fixed retrieval used 202 total tool calls, adaptive with memory 152, and adaptive without memory 132. Seven shipment confirmations were provided as fixture inputs for each method. The adaptive and fixed variants still requested seven operator interventions. This is not an independent accuracy estimate or measured staff time saved.

Memory hints were genuinely retrieved, but they increased tool use without improving accuracy on these cases. The offline comparison disables model calls; it cannot establish model superiority. A real-provider functional check proves only the specific tested path.

PDF support is intentionally restricted to labelled text records. Shipment splitting, OCR, automatic external supplier/POS actions, broad production capacity, and an independently validated customer pilot remain outside this delivered MVP. Review resolution records a human disposition and never implies a product was cleared or a hold released.

## Start and demonstrate

1. Run `docker compose up -d --build` and open the configured app port (8088 on this machine).
2. Choose replay mode and **Start investigator demo**.
3. Configure operator access using the existing local named-credential controls or an existing token; follow [the guide](investigator-guide.md).
4. Follow [the demo script](investigator-demo.md). The main case starts with two candidate deliveries; the companion has no usable delivery evidence.
5. Open Evaluation Lab for the new comparison and its provenance; use [the pitch slide](recallops-pitch.pptx) and [pilot plan](pilot-plan.md).

The remaining external steps are Aiven account/service configuration and deployment verification, independent evaluation labels, and authorized retailer pilot participation. None is represented as completed by synthetic tests.
