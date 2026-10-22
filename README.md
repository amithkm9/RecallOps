# RecallOps — Autonomous Product Safety Command Center

A working grocery recall investigation application for Future Founders: Data-Centric Agents. Genuine French government recall records enter PostgreSQL; a LangGraph workflow verifies store inventory, creates controlled internal holds, and revises decisions as evidence changes.

**Current status:** the local end-to-end replay works. This is a hackathon MVP, not a production-certified safety service. See [PLAN.md](PLAN.md) for verified completion, remaining work and release gates. No Aiven deployment has been performed.

## Run locally

**Aiven, GitHub and cloud accounts are not required for local use.** Docker Compose starts both the application and PostgreSQL on your computer. Aiven is an optional deployment destination. Follow [the local walkthrough](docs/local-walkthrough.md) for the complete operator journey.

First-time image/dependency downloads and live API/model calls need internet. The archived replay and deterministic investigation work offline once installed.

```sh
cp .env.example .env   # only if you do not already have a local .env
# Optional: set OPERATOR_TOKEN to a long random value for authorized human reviews.
docker compose up -d --build
```

Open http://localhost:8080 and select **Run incident simulation**. On the current development machine, `.env` uses `APP_PORT=8088` because port 8080 is occupied: http://localhost:8088. PostgreSQL is published on loopback port 55432. Container-to-container traffic uses port 5432. Data survives container restarts in `postgres_data`.

Reset a demonstration with **Reset & start new replay**. This archives the prior demo workspace instead of deleting its evidence. It does not reset live store data.

### Source development

Prerequisites: Python 3.12+, Node 22+, Docker with Compose.

```sh
docker compose up -d db
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
make migrate
make dev
# In a second terminal:
npm --prefix frontend run dev
```

Vite proxies `/api` to the host backend on port 8080. Stop the Compose app if you want to reuse that port. The Python app serves `frontend/dist` when it exists. Production builds serve both UI and API from one container.

## What works

- React/TypeScript, Tailwind, shadcn-style Radix button, Lucide, TanStack Query, Recharts and React Flow interface.
- Dashboard, incident search/detail, paginated inventory, CSV validation and import, evidence graph, Time Machine, Evaluation Lab and settings.
- Verified Explore API 2.1 ingestion, JSON snapshot import, offline fixture fallback, stable IDs, content hashes and immutable versions.
- PostgreSQL models and Alembic migrations, including database-enforced append-only evidence and decision/evidence relationships.
- Actual LangGraph execution with store-scoped tools, recorded inputs/outputs, per-node state and audit events.
- Deterministic lot/date checks, idempotent holds, conflict escalation and token-authorized human release.
- Database outbox with retries, duplicate suppression, advisory locks and SSE progress.
- Optional OpenAI-compatible planner and draft wording; honest deterministic fallback without a model key.
- Repeatable archived-record replay using fictional stock and supplier evidence.
- Measured synthetic benchmark and automated backend, component and browser tests.

## Data and workflow

See [data-source.md](docs/data-source.md) for verified fields, provenance, reuse attribution and coverage limits, and [architecture.md](docs/architecture.md) for the event and safety workflow.

The demo uses official recall **2024-12-0201**, source ID **17010**, GTIN **3760099533007**, lot **24326020**, use-by date **2024-12-20**. This is a historical demonstration, not a statement that this stock is currently for sale. Store quantities, inventory and supplier messages are fictional.

Live source synchronization is available under **Data & settings**. The initial scan is bounded by `SOURCE_MAX_RECORDS`; tracked live recalls and inventory identifiers are also queried. This is not a full-catalog completeness guarantee. A failed API request loads the archived fixture and explicitly reports fallback; it does not update the last-successful-live-sync timestamp.

Historical import:

```sh
backend/.venv/bin/python scripts/ingest_snapshot.py data/fixtures/official_snapshot.json
```

## Configuration

Copy `.env.example` for the full list. Never commit populated secrets.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL psycopg URL; normal `postgres://` and `postgresql://` URLs are accepted |
| `ENVIRONMENT` | `development` locally; `production` when deployed |
| `OPERATOR_TOKEN` | Bearer token for protected access and all human reviews/releases |
| `DEMO_ENABLED` | Enable controlled historical replay |
| `PUBLIC_DEMO` | Restrict unauthenticated access to fictional demo data; use a separate demo deployment/database |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Optional compatible chat-completions provider, server-side only |
| `SOURCE_REFRESH_SECONDS` | Automatic refresh interval; `0` disables the scheduler |
| `SOURCE_MAX_RECORDS` | Per-query scan cap; default 1000 |
| `WORKER_ENABLED` | Run the PostgreSQL event worker with the API |
| `PORT` | Container listener, default 8080 |
| `APP_PORT`, `POSTGRES_PORT` | Local Compose published ports |

In development without a token, normal local operations work, but human release still requires an operator token. Set the token on the server, restart the app, then enter it in **Data & settings**. Production refuses to start without a token unless `PUBLIC_DEMO=true` is explicit. This MVP uses one operator credential, not enterprise user/role management.

## Tests and benchmark

```sh
make e2e                         # PostgreSQL/API journey, isolated backend test DB, component tests
make e2e RUN_BROWSER_TESTS=1 BASE_URL=http://localhost:8080 INSTALL_TEST_BROWSER=1
backend/.venv/bin/python scripts/benchmark.py
RECALLOPS_URL=http://localhost:8080 backend/.venv/bin/python scripts/demo.py
```

`make e2e` adds demonstration/benchmark records to the local application database. Backend pytest cases use a separate `recallops_test` database. Never run this test command against a production database. The application connection needs local database-creation permission for that test setup.

Latest recorded backend run: **48 passed**. Component run: **4 passed**. The latest **2 isolated Chromium end-to-end tests pass**, covering the full operator journey and mobile navigation. Benchmark results are actual measurements in [last-benchmark.json](docs/last-benchmark.json), with interpretation in [evaluation.md](docs/evaluation.md).

## Repository

```text
frontend/                 React/Vite UI, components and browser tests
backend/app/api/          Versioned JSON API and SSE
backend/app/models/       SQLAlchemy PostgreSQL models
backend/app/schemas/      Pydantic contracts
backend/app/services/     Ingestion, matching, inventory, replay, outbox, evaluation
backend/app/agents/       LangGraph workflow, tools, optional model planner
backend/app/core/         Configuration, database, authorization
backend/app/repositories/ Database serialization and views
backend/alembic/          Schema and provenance migrations
backend/tests/            Safety, persistence, ingestion and API tests
data/fixtures/            Official snapshot, provenance and synthetic labels
scripts/                  Startup, ingestion, replay, benchmark and verification
docs/                     Workflow, data, deployment, API, evaluation and pitch
```

Deployment preparation: [Aiven guide](docs/deployment.md) and [API request template](docs/aiven-application.json). Demo presentation: [three-minute walkthrough](docs/demo.md).

## Material limitations

No POS integration or external notifications are sent. There is no supplier API connector or document/PDF extraction yet; supplier evidence in the showcase is a labeled replay event. Complex lot expressions conservatively require review. A new event reruns the graph with durable state and idempotent actions; native LangGraph checkpoint-level resume is not implemented. Live provider behavior has not been verified with a real LLM key. The benchmark is small, synthetic and authored alongside the system, not an independently audited or held-out production evaluation. Enterprise tenancy, individual identities, rate limits, retention, monitoring and load testing remain future work. Aiven provisioning and paid services require separate authorization and credentials.
