# RecallOps Investigator guide

RecallOps checks whether a shop's stock matches an official recall. The investigator searches available evidence when a batch or date is missing, asks the operator to confirm the shipment association, and records the reason for each decision. A hold is an internal application record. Staff still handle physical stock and checkout controls.

## Start locally

1. Copy `.env.example` to `.env` if you do not already have a local configuration. Preserve existing secrets and settings.
2. Preserve the current `.env`. Claim validation, direct answers, review resolution, and hold release require an authorized operator even in local development. A named scoped credential can provide this without changing the environment file; follow the steps below. For a protected deployment, configure a bootstrap `OPERATOR_TOKEN` through runtime secrets.
3. Run `docker compose up -d --build` from the repository root.
4. Open the local port configured by `APP_PORT` (default `http://localhost:8080`). If a bootstrap operator token is already configured, enter it in **Data & settings**.
5. Start the investigator demonstration from the replay view. The classic three-stage replay remains available separately.

The optional model uses `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL`. Without a configured model, the application labels its planner as deterministic fallback. The initial investigator demonstration disables model calls explicitly. Later live/operator-triggered work can use a configured provider. A model connection test establishes connectivity, not investigation quality.

### Operator access in the existing local setup

If local development has no `OPERATOR_TOKEN`, its administration setup is open, while evidence confirmation still requires an operator credential. Use the built-in setup screen:

1. Start the investigator demo first so its fictional store exists.
2. Open **Data & settings → Operations & access → Access & stores**.
3. Enter a credential name, select role **operator**, and select the investigator demonstration store.
4. Choose **Create scoped credential**. Copy the returned token immediately; the application will not show it again.
5. Enter and save that token in the operator-token field in **Data & settings**, then return to the incident.

This preserves the environment file and grants access only to the selected store. The second unresolved demo uses a separate store; a credential scoped only to the main demo cannot inspect it. Use an administrator credential for the complete two-store presentation. Starting a new replay or running comparison benchmarks also requires administrator access. A production installation must first authenticate its bootstrap administrator; the open local setup path is not available there.

## Ordinary operator journey

1. **Import stock.** Use the inventory CSV sample and retain the store's stock identifiers. Keep separate shipments as separate inventory groups when their batch evidence differs.
2. **Refresh recalls.** Synchronize official data and inspect the last successful refresh, fallback status, and scan limit. A bounded scan does not establish complete recall coverage.
3. **Open the incident.** The investigator shows a conclusion, execution steps, unresolved questions, and source evidence.
4. **Add delivery evidence.** Upload a UTF-8 CSV or a text PDF. Original bytes stay attached to the incident, with a SHA-256 digest and exact row/page locator. Imported fields are unconfirmed claims.
5. **Confirm association.** Inspect the source and the actual shipment reference. Choose the stock group the delivery describes, enter a reason, and accept or reject the claim. The SKU, barcode, and complete quantity must match for acceptance. A shared barcode alone never proves the shipment association.
6. **Wait for reassessment.** The queue triggers another run. Accepted evidence can fill a missing batch/date in the investigation's effective stock view. It does not overwrite the warehouse inventory record. Disagreement with warehouse or other accepted evidence produces conflict.
7. **Answer a targeted question when needed.** Record a physical batch observation, date when relevant, source reference, and reason. This creates attributed operator evidence and a validated claim. It does not silently replace contradictory evidence.
8. **Review the result.** An affected verdict may create an internal hold. Conflicts preserve existing holds. Rejected evidence or a new unaffected result does not automatically release an existing hold.
9. **Record review resolution.** Cite supporting evidence from the latest completed investigation or current accepted claims. A stale run, changed recall version, pending work, or failed work blocks resolution until reassessment. Resolution records what the operator reviewed. It is not a safety clearance or hold release.
10. **Release separately if authorized.** The existing hold-release workflow requires an operator and a reason. New evidence reopens investigation review while preserving history.

## Delivery CSV

```csv
delivery_id,sku,gtin,lot,quantity,expires_on,reference
D-104,SALMON-DELIVERY,3760099533007,24326020,24,2024-12-20,Fictional receiving reference D-104
```

`expires_on` is optional. The other fields are required. Quantities must be positive integers. Barcodes remain strings to preserve leading zeroes. Imports accept up to 2 MB and 500 rows. Invalid rows produce explicit errors; valid rows remain inspectable. Importing identical bytes again does not duplicate evidence or investigation work, even with a different filename.

A delivery covering only part of an inventory group cannot establish the batch of the whole group. Split the inventory appropriately or correct the source before confirming association.

## Text PDFs

The first implementation extracts explicitly labelled records, with one unambiguous record per page:

```text
delivery_id: D-104
sku: SALMON-DELIVERY
gtin: 3760099533007
lot: 24326020
quantity: 24
expires_on: 2024-12-20
reference: Fictional receiving reference D-104
```

Repeated batch fields, missing required fields, scans, encrypted PDFs, or unsupported layouts remain unresolved. Extraction is limited to 20 pages and a bounded worker process. Document text cannot instruct the agent to create or release a hold. Download the original to review it, or record a sourced operator observation.

## Evidence experiments and memory

**What changed the answer?** uses a saved run's stock and recall snapshot. Select evidence from that run and recompute the result. This isolated simulation never creates or releases operational holds. Evidence added after the saved run is not retroactively available to it.

Retrieval memory records where a confirmed document was previously found for this store and SKU. It can guide a later search. It does not transfer yesterday's batch or safety conclusion to today's stock. Measured memory comparisons belong in the evaluation results; the existence of stored history alone is not evidence of learning.

## API reference

Paths below use `/api`. Equivalent versioned routes are under `/api/v1`. Send `Authorization: Bearer <operator token>` to operator actions. Do not put real tokens in shared examples or screenshots.

| Method and path | Input or result |
|---|---|
| `GET /incidents/{id}/investigator` | Documents, claims, stock, questions, current run, resolutions, limitations |
| `POST /incidents/{id}/investigator/deliveries` | Multipart `file`; returns source ID, claim count, row errors, queued event |
| `POST /incidents/{id}/investigator/claims/{claim_id}/validate` | JSON `inventory_lot_id`, `accept`, `reason` |
| `POST /incidents/{id}/investigator/answers` | JSON `inventory_lot_id`, `lot`, optional `expires_on`, `reference`, `reason` |
| `POST /incidents/{id}/investigator/resolve` | JSON `expected_run_id`, `evidence_ids`, `reason` |
| `GET /incidents/{id}/investigator/documents/{evidence_id}` | Original source bytes, restricted to this incident |
| `GET /incidents/{id}/investigator/simulation-options` | Available run snapshot and selectable evidence |
| `POST /incidents/{id}/investigator/simulate` | JSON `run_id`, `evidence_ids`; isolated recomputation |
| `POST /investigator/demo` | Historical recall, fictional inventory and two candidate deliveries, plus a second unresolved case |
| `POST /investigator/evaluation` | JSON `include_model`, `include_memory`; administrator access |
| `GET /investigator/evaluation/latest` | Latest persisted synthetic comparison, if one exists |

Open `/docs` for the generated request schemas. Use an existing incident ID and returned evidence IDs rather than fabricated identifiers.

## Troubleshooting

- **403 on acceptance:** configure and enter an operator token or use a named operator credential scoped to the store. Public viewers cannot confirm evidence.
- **Claim stays unconfirmed:** uploading is not validation. Inspect the source and explicitly confirm the association.
- **Quantity mismatch:** the document does not cover the complete selected inventory group. Do not round or infer the missing coverage.
- **Conflict after an answer:** the new observation disagrees with retained evidence. Review and explicitly reject unsupported claims or correct the original source through its supported workflow.
- **Resolution returns 409:** work or the official version changed. Refresh, finish or recover outstanding events, and review the new run.
- **A hold remains:** review resolution and simulation do not release holds. Use the separate release action after authorized review.
- **PDF yields no claims:** inspect the original and use a labelled record or a sourced operator observation. OCR and arbitrary document understanding are outside this version's support.
