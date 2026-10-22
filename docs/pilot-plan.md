# RecallOps first-user pilot proposal

**Status: a proposed route to first users. No outreach, customer commitments, adoption results, or willingness-to-pay evidence are claimed.**

## Customer and hypothesis

The initial user is a grocery operator responsible for checking recalled batches, with inventory CSV exports and delivery records available. The hypothesis is that finding and associating evidence is a substantial part of the work and that RecallOps can reduce investigation effort while preserving correct decisions and review boundaries.

The first pilot should assess that hypothesis before building checkout integrations or broad document automation.

## Recruitment proposal

Seek three to five operators through founder-led conversations or introductions from a local retailer association. Start with operators who can provide authorized, de-identified historical stock and delivery examples. A shop that cannot export batch-level stock may still inform discovery but is not an ideal first operational integration.

No messages have been sent. The following is an interview guide for a future conversation:

1. Walk through the last recall investigation you handled. Which records did you check, and where did you find them?
2. When the barcode matched but batch information was missing, how did you resolve it?
3. How did you distinguish separate deliveries of the same product?
4. Which steps consumed the most time? What was the consequence of an unresolved case?
5. Who authorizes a hold or release, and how is that decision recorded today?
6. Would you permit a supervised historical-case comparison using a limited, de-identified export?

Avoid pitching claimed time savings before observing the workflow.

## Pilot scope

Use historical cases in a separate environment. Retain each source's provenance and agreed retention period. Limit document support to inventory/delivery CSV and text PDFs that the parser can interpret. The operator retains authority over real stock handling. The system's internal hold does not change a real till or warehouse system.

For each case, have the operator establish the expected stock association and supported conclusion before comparing systems. Record who labelled the case and which sources they checked. Keep evaluation cases separate from the examples used to tune parsing or prompts.

## Study procedure

1. Record the current manual investigation using the operator's usual tools, including time spent locating information and any unresolved questions.
2. Run RecallOps with the same starting stock, recall version, and available documents. Do not grant it information the manual condition lacked.
3. Alternate case order where possible to reduce learning effects. Record prior familiarity with each case.
4. Have a separate reviewer assess the decision and cited evidence where feasible. Report when only the original operator reviewed it.
5. Inspect disagreements, especially an unsupported exclusion, wrong shipment association, or hold release assumption. Classify errors before changing the product.
6. Repeat a small fresh set after fixes. Preserve the original result rather than replacing it with the improved run.

## Measures and proposed decision gates

| Measure | What to record | Proposed gate, not an achieved result |
|---|---|---|
| Decision correctness | Supported affected/unaffected/review/conflict result | No unsupported stock exclusion in the pilot sample |
| Shipment association | Correct link between source and physical stock group | Every accepted association has reviewer-supported evidence |
| Operator effort | Active minutes and interventions per case | Lower median effort on comparable cases without worse correctness |
| Unresolved handling | Correct refusal and specific question | Missing or contradictory evidence remains visibly unresolved |
| Reliability | Lost work, duplicate holds, recovery after restart | No duplicated hold or lost decision history in exercised cases |
| Operating cost | Provider usage and observed runtime per case | Report actual cost basis before proposing pricing |
| Adoption | Willingness to repeat the workflow with a new case | Operators choose to continue a supervised trial |

A small pilot cannot establish population-level safety or guaranteed accuracy. Publish its sample size, scope, reviewer independence, and remaining errors next to any claimed benefit.

## Commercial hypothesis

Explore a paid pilot or per-store subscription only after identifying who owns the budget and what value they observed. Pricing is undecided. Ask what the current process costs in staff time and which integration requirements would prevent adoption. Separate willingness to try a demonstration from willingness to pay.

## Before using customer data

Complete actual hosting, access scoping, verified database TLS, backup recovery, and external monitoring checks. Agree on data access, retention, and permitted use with the participant. Collect only records needed for the case. Keep public demo workspaces separate. Record deployment URL, commit, environment, and reviewer attribution.

The pitch slide states the customer hypothesis, product mechanism, and this proposed pilot route. It intentionally contains no invented market size, savings percentage, customer logo, or deployed-hosting claim.
