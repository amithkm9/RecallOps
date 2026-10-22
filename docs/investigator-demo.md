# Investigator demonstration script

This demonstration uses a real historical French recall, reference `2024-12-0201`, and explicitly fictional stock, delivery documents, and supplier statements. It demonstrates changing evidence. It does not show a current recall affecting a real shop.

## Preparation

- Start the current application and PostgreSQL. Configure an operator token and enter it in Data & settings.
- Use a dedicated fictional replay workspace. Keep live customer data out of public demonstrations.
- Start the investigator demo. The API equivalent is `POST /api/investigator/demo`.
- Note both returned IDs: `incident_id` and `unresolved_incident_id`.
- The initial run uses deterministic planning with no model-provider call. Describe the actual mode shown on screen. If separately demonstrating model planning, disclose it and use the recorded trace from that run.

## The five-minute story

### 0:00 — The customer problem

Say: “A grocery operator receives a recall that applies to one batch. The same barcode can appear on other batches. The operator needs to find the relevant stock and investigate missing batch information.”

Show the historical official source and its batch `24326020`. Show the 18 units with a different known batch and the 24 units with no recorded batch.

### 0:40 — The agent investigates the gap

Open the investigator. Show the actual retrieval steps, result counts, and stopping reason.

Two fictional delivery records match the same stock SKU and barcode:

| Delivery | Batch | Quantity | Meaning in this scenario |
|---|---|---:|---|
| D-104 | 24326020 | 24 | The receipt for the stock being checked |
| D-105 | OTHER-DELIVERY | 24 | Another shipment of the same product |

Say: “A matching barcode gives us candidates. The system cannot infer which shipment these packets belong to.”

Open the source excerpt and download the source if needed. The records are unconfirmed, so neither should independently clear stock or trigger a batch-specific hold.

### 1:30 — One precise operator answer

For the demonstration, identify D-104 as the correct shipment using the fictional receiving reference. Select the 24-unit group, accept D-104, and enter: “Checked the fictional receiving reference D-104 against this stock group.” Reject D-105 for this group with a reason identifying it as another shipment.

Wait for reassessment. Show the validated association, the accepted claim and its source row, and the effective stock batch. The warehouse inventory row remains unchanged.

Expected outcome: the 24 units match the recalled batch and date, and RecallOps records an internal hold. The 18 units remain outside this recall's scope.

### 2:15 — The evidence causes the decision

Open the evidence experiment for the completed run. Compare a selection without the accepted delivery evidence to one with it. Use the selectable IDs provided for that run. Explain the result visible on screen.

Say: “The saved stock and recall stay the same. This experiment changes the available evidence. It cannot alter a live hold.”

Do not imply the simulation can include a document that arrived after its saved run.

### 3:00 — A contradictory statement

Use the existing supplier-evidence form to add an explicitly fictional statement saying this stock has batch `OTHER-DELIVERY`. Wait for the new investigation.

Expected outcome: conflict and targeted human review. The existing 24-unit hold stays active. Show the supporting records and the decision history.

Say: “A new statement does not automatically overrule the warehouse or a confirmed delivery. The operator sees exactly where the evidence disagrees.”

A review-resolution note can document quarantine handling and the unresolved discrepancy using the latest run's evidence. It does not declare the product safe or release the hold. Leave the protective hold active for the demonstration.

### 3:50 — The case that remains unresolved

Open the second incident returned by the demo. It has seven fictional units with no batch and no matching delivery evidence.

Show the agent's stopping reason and question. Say: “There is not enough evidence here. The system asks for the physical batch or a delivery reference instead of inventing an answer.”

### 4:20 — Evidence of performance

Open the latest investigator comparison or run the deterministic comparison with administrator access. Compare the current workflow, fixed retrieval, and adaptive retrieval using the displayed dataset and measures.

Report actual results, including ties, unresolved cases, or disadvantages. These are synthetic scenarios with developer-authored labels. They are not independent customer validation, and deterministic retrieval results are not model-quality results. Only mention provider timing/cost where a provider run actually recorded it.

### 4:50 — First users

Show `recallops-pitch.pptx`. Say: “Our first pilot would work with grocery operators who already export stock and delivery records. We would compare historical-case investigation time and decision correctness before asking them to rely on it in their operations.”

## Reliable fallback

If live official synchronization fails, show the archived-source disclosure and proceed with the historical demonstration. If the model is unavailable, show the fallback mode. If hosting is not ready, call the run local and do not imply it is deployed on Aiven. Retain actual run IDs and evidence history for follow-up inspection.

## Expected state checklist

- Two delivery candidates appear and require association confirmation.
- Accepted D-104 establishes the batch only after explicit operator action.
- The confirmed 24-unit match creates a hold.
- The evidence experiment changes no operational records.
- Supplier disagreement produces conflict and preserves the hold.
- The second case remains unresolved with a concrete question.
- No live customer outcome, hosted deployment, or model advantage is claimed without evidence.
