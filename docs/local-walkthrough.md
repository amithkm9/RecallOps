# Run RecallOps locally and follow an investigation

Aiven and GitHub are not needed for local operation. Docker Compose supplies PostgreSQL and the application. Keep cloud configuration only for an optional future deployment.

## 1. Start the application

Open Docker Desktop, then run from the RecallOps project directory:

```sh
docker compose up -d --build
```

Preserve your existing `.env`; do not overwrite model credentials by copying the example over it. On a fresh checkout without `.env`, copy `.env.example` first. Builds download dependencies and images, so the first setup needs internet.

Open http://localhost:8088 on this development machine (`APP_PORT=8088`). A fresh default configuration uses http://localhost:8080. `/api/health` should return `status: ok` and `database: postgresql`.

No separate frontend or Python install is needed for this Docker path. Migrations run automatically, and PostgreSQL data persists in the Docker volume.

## 2. Check optional model configuration

The server reads `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL`. After changing `.env`, apply the values to the container:

```sh
docker compose up -d --force-recreate app
```

Check Data & settings. A configured provider enables model-assisted planning and wording; actual successful use is shown in an investigation's trace. Missing credentials or provider failure triggers a labeled deterministic fallback. Never assume model configuration means a successful model call.

For a fully offline replay, use deterministic fallback. A configured remote model may time out before fallback if the machine is offline.

## 3. Run the recorded customer journey

1. Select **Replay demo mode**.
2. Click **Run incident simulation**. The backend loads the genuine archived salmon recall and fictional inventory.
3. The first investigation examines 18 units in a known different lot and 24 units with missing lot information. Result: known lot unaffected; unknown stock needs review; no initial hold.
4. Click **Inject next evidence**. A fictional warehouse scan identifies the unknown 24 units as recalled lot `24326020`. The backend reopens the incident and creates one 24-unit internal hold.
5. Click **Inject next evidence** again. Fictional supplier evidence disputes the warehouse lot. Result: conflict and human review; the protective hold stays active.
6. Select the three timeline stages to compare stored decisions and tool calls.
7. Open the incident and **Explore evidence graph**. Click a source, target, inventory lot, evidence record, decision or hold to see actual persisted data.
8. Open **Evaluation Lab → Run benchmark** for a measured comparison with name-only and GTIN-only matching.
9. Click **Reset & start new replay** to repeat. The previous demo history is retained in an archived demo workspace.

Official recall facts are real and historical. The store, quantities, warehouse scans and supplier messages in replay are fictional. An internal hold does not change a real checkout system.

## 4. Use live data with your inventory

1. Switch to **Live data mode**.
2. Open **Inventory → Sample CSV** to get the expected columns. The supplied sample is fictional; replace it with your own data when testing a real inventory export.
3. Upload the CSV. Valid rows persist; invalid rows report their line number and reason. Keep GTIN and lot columns as text when editing in a spreadsheet.
4. Open **Data & settings → Sync official data**. Internet access is required. If the official API is unavailable, the UI reports archived-fixture fallback rather than claiming a live refresh.
5. The worker investigates relevant matches automatically. Open **Incidents** to inspect decisions and evidence. No matching inventory can correctly mean no new incident.
6. Use **Investigate again** to request another recorded investigation.

Current limitation: arbitrary live supplier-evidence upload and supplier-system connections are not implemented yet; the supplier contradiction input is currently part of the controlled replay.

## 5. Human review

To record human review or release a hold, configure a strong `OPERATOR_TOKEN` in `.env`, recreate the app container, and enter that token in **Data & settings**. Open the incident, enter a reason, then choose the review action. Releasing a hold is an explicit operator decision. Supplier notifications are drafts only and are not sent.

## 6. Stop and resume

```sh
docker compose stop
# Later:
docker compose up -d
```

Stopping does not delete the stored inventory, evidence or decisions. Avoid `docker compose down -v` unless you deliberately want to delete the database volume.
