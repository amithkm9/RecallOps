# Three-minute judge walkthrough

Before presenting: start Compose, open the local application, ensure Replay Demo Mode is selected, run the benchmark once, and use Reset & start new replay for a clean scenario. No government API or model key is needed for replay. Say explicitly whether the current engine is deterministic or LLM-assisted.

**0:00–0:30 — Problem and source**

“Small grocery teams need to know exactly which stock a recall affects. Product-name matching overblocks stock; GTIN-only matching still ignores batches.” Show Data & settings and the official source link. Distinguish publication time from ingestion time. Explain that GTIN coverage is incomplete.

**0:30–1:00 — Initial investigation**

Click Run incident simulation. Explain that the salmon recall is historical and real; the store is fictional. Show 18 units in a known different lot and 24 with missing lot information. The system leaves the known different lot unaffected and asks for review of unknown stock. Open one persisted tool result.

**1:00–1:35 — Warehouse evidence**

Click Inject next evidence. The warehouse scan identifies the 24 units as the recalled lot. Show the revised decision and one 24-unit internal hold. Clarify that it is an application hold, not an executed checkout-system block.

**1:35–2:10 — Contradiction**

Inject the supplier correction. Compare the previous affected decision with the current conflict decision. The hold remains and human investigation is requested. Click the affected and conflict stages to show stored history rather than an animation.

**2:10–2:35 — Defensible provenance**

Open the incident and Evidence Graph. Click an official target, evidence record, decision and hold. Show their real stored fields. Show the human review control and supplier draft. No message has been sent, and release needs authorization plus a reason.

**2:35–3:00 — Evidence it works**

Open Evaluation Lab. Show the measured baseline comparison, case count, run time and one case. Explain that this is a 22-case synthetic development benchmark; it demonstrates safety rules rather than general production accuracy. End with the observable value: relevant stock isolated, irrelevant stock spared, uncertainty visible, and every revision traceable.

Suggested next validation: a grocery pilot using independently labeled real batch data and measured review workload. Business pricing and return-on-investment claims are hypotheses until validated with customers.
