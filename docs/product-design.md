# RecallOps product and experience guide

## What the product does

RecallOps helps grocery teams investigate official product recalls against their stock. Its core customer question is: “Which units should we hold, what proves that decision, and what should we do next?”

The current application imports French RappelConso records and inventory CSVs, verifies GTIN/lot/date scope, records investigations, creates internal holds, and preserves evidence and decision history. Missing information requires review. Conflicting supplier evidence preserves an existing hold. Supplier messages are drafts; the application has no point-of-sale connection.

The primary user is a store or inventory operator. A safety manager needs an overview of unresolved cases, held units, and review decisions. An auditor or technical reviewer needs source provenance and the investigation history. These are inferred product roles, not implemented account roles or validated interview findings.

## How the project is organized

| Area | Implementation | Responsibility |
| --- | --- | --- |
| Application shell | `frontend/src/App.tsx` | Routes, navigation, workspace mode, authenticated event updates |
| Operational pages | `frontend/src/pages.tsx` | Overview, incident register, inventory import/search, settings |
| Investigation | `frontend/src/investigation.tsx` | Decisions, review and release, evidence, replay, evaluation |
| Provenance | `frontend/src/evidence-graph.tsx` | Interactive source-to-decision graph using React Flow |
| Shared UI | `frontend/src/components/` | Panels, tables, states, badges, buttons |
| Data layer | `frontend/src/api.ts` | TypeScript API contracts, authentication, React Query, dates |
| Design system | `frontend/src/styles.css` | Tokens, responsive layouts, visual hierarchy, interaction states |
| HTTP API | `backend/app/api/routes.py` | Dashboard, incidents, inventory, recalls, replay, review, evaluation, event stream |
| Decision policy | `backend/app/services/matching.py` | Conservative deterministic identifier, lot, and date checks |
| Investigation workflow | `backend/app/agents/` | Tool-driven workflow and optional language-model assistance |
| Persistence | `backend/app/models/`, `repositories/`, `alembic/` | PostgreSQL records, versions, holds, evidence, audit history |
| Background work | `backend/app/services/events.py` | Event processing, retries, investigation execution |
| Demonstration and tests | `data/fixtures/`, `scripts/`, `backend/tests/`, `frontend/e2e/` | Archived source, synthetic scenario, benchmarks and validation |

The frontend is React 19 + TypeScript + Vite. React Query manages API state; React Router manages routes; Recharts renders outcomes and evaluation; React Flow renders evidence. The backend uses FastAPI, SQLAlchemy, PostgreSQL and LangGraph. Model assistance is optional; deterministic matching controls stock actions.

## Customer journeys

1. **Start a workspace:** configure access if required, synchronize recall records, download the inventory template, then validate and import stock. Demo mode provides a separate fictional store scenario.
2. **Triage:** use the overview to identify review work and units on hold. Metric links open the relevant incident view; review includes both missing and conflicting evidence.
3. **Investigate:** open the product case, read the official recall and latest conclusions. Switch to evidence and execution when the decision needs explanation; follow the graph to inspect contributing records.
4. **Respond:** record review notes, inspect an active hold, and explicitly confirm a release. The backend still enforces operator authorization. Copy a supplier draft for further handling.
5. **Revisit:** inspect activity history or replay how new evidence changed an earlier decision.

## Redesign implemented

- Deep teal navigation, warm neutral surfaces, sage accents, a coherent spacing scale, stronger headings, and semantic status colors.
- Navigation grouped into workspace, intelligence, and management. Replay education is separated from day-to-day operational navigation.
- A visual source → verify → respond workflow establishes the product purpose. Live mode leads to priority review; replay mode leads to the simulation.
- Clickable operational metrics, a compact recent investigation queue with filters, next-step links, and a direct review callout.
- An honest “assessed lots” label includes uncertain outcomes; “recorded hold actions” describes the actual backend count.
- Incident sections prioritize decision and response. Technical evidence and execution, and activity history, have separate views.
- Inventory import has a clear upload area, labeled search, search-specific empty states, and download failure feedback.
- Workspace selection persists for the browser session. Switching mode returns to the overview to avoid displaying a case from the previous workspace under the new mode label.
- Mobile navigation has a backdrop, keyboard containment, Escape handling, and focus return. A skip link, visible focus indicators, reduced-motion support, and text-based status labels improve accessibility.
- Chart values and all counts remain connected to API records. No decorative trend numbers or fabricated success percentages were added.
- Event-stream heartbeats no longer invalidate every query. Real data events refresh records; saving a session token reconnects the stream with the new credentials.

## Design principles for further work

Make the next action obvious. Put uncertainty and evidence beside the decision. Use red and amber for operational meaning, not decoration. Keep source credibility, data age, and demo boundaries visible. Prefer readable customer language; disclose raw records and execution details when requested. Keep actions and counts truthful to backend semantics.

## Remaining product gaps

These require further product and backend work; the redesign does not imply they already exist. Supplier statement intake and provider diagnostics have since been added; see [feature verification](feature-validation.md).

| Priority | Gap | Customer benefit | Work needed |
| --- | --- | --- | --- |
| Next | First-run onboarding and workspace readiness | Know whether source data, stock and authorization are ready | Persistent setup state and a guided checklist |
| Next | Assignments, due dates and escalation | Managers can coordinate a queue | Ownership model, permissions, deadlines and notification policy |
| Next | Broader plain-language evidence inspection | Operators can compare lots without reading JSON | Supplier summaries are implemented; other evidence types still need comparisons and source previews |
| Next | Search and pagination at scale | Keep large incident registers responsive | Server-side pagination, stable sorting, filter counts and debounced search |
| Next | Review usability validation | Verify that urgency and release semantics are understood | Sessions with store operators and safety managers, including keyboard and screen-reader use |
| Later | Exportable case report | Share a defensible decision record | Report generation with provenance, review notes and version history |
| Later | Multi-store workspace management | Managers can prioritize across stores | Workspace membership, store selection, roles and scoped access |
| Later | POS/warehouse integrations | Reduce manual stock handling | Integration contracts, authorization, reconciliation and failure recovery |

Measure time to locate the next case, time to explain why stock is held, import completion and error recovery, and review-note completion. Establish a baseline before claiming the redesign improves these outcomes. Automated layout checks do not constitute a full accessibility audit.

## Run and inspect

The Python environment is `backend/.venv`; activate it with `source backend/.venv/bin/activate`.

The redesigned frontend can run against the existing local backend:

```sh
cd frontend
API_PROXY_TARGET=http://127.0.0.1:8088 npm run dev -- --port 5173
```

The default proxy remains port 8080. Set `API_PROXY_TARGET` for a different backend. Rebuild or restart a container deployment to serve the new compiled assets; the development preview does not change a running container image.

```sh
cd frontend
npm run build
npm test
BASE_URL=http://127.0.0.1:5173 PLAYWRIGHT_CHANNEL=chrome npm run e2e
```

`PLAYWRIGHT_CHANNEL` is optional; tests otherwise use Playwright Chromium. Browser checks cover the recorded recall journey, priority links, filter recovery, workspace persistence, keyboard navigation, and responsive pages. Preview images are saved under `docs/screenshots/`.
