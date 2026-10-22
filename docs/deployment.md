# Aiven deployment handoff

**The deployment configuration is prepared. No Aiven deployment URL, provisioned service, or hosted verification is claimed.** Completing the competition's hosting requirement needs an Aiven account/project, repository access, a managed PostgreSQL service, and deployment configuration.

The root Dockerfile builds the React assets and serves them from FastAPI on port 8080. Startup applies migrations under a database advisory lock before starting one API process and its embedded worker. The app stores documents, claims, decisions, and queued work in PostgreSQL.

## Static preflight

Run from the repository root:

```bash
python3 scripts/deployment_check.py
```

This checks files, entrypoint wiring, and declared environment names. It reads no `.env`, prints no secrets, contacts no services, and provisions nothing. A passing result is not proof of hosted readiness.

## Runtime setup

Use `compose.aiven.yaml` when scanning the repository in Aiven Runtime. It defines the application using the root Dockerfile and an HTTP port. It intentionally declares no database service. Connect an existing managed PostgreSQL service in the Console and expose its connection string as `DATABASE_URL`. Set operator credentials before deployment. Review the selected plan, region, and cost in the Console.

Aiven supports Compose manifests and builds application images from repository Dockerfiles. The app-only manifest follows that structure. Selecting this manifest does not itself create a managed database. See [Aiven Compose manifests](https://aiven.io/docs/products/runtime/manifest-files/compose-files) and [service connections](https://aiven.io/docs/products/runtime/connect-services-to-apps).

Select the GitHub account, repository, branch, and manifest in Runtime. Check the scanned configuration before deploying. Repository pushes do not automatically deploy new commits; use Runtime's redeploy action for updates. See the [official deployment guide](https://aiven.io/docs/products/runtime/deploy-apps).

`docs/aiven-application.json` remains an alternative API-request template with placeholders, not a provisioning script. Do not send it unchanged. The current Console manifest path avoids assuming a valid plan identifier, project, database name, or repository connection.

## Server configuration

| Variable | Required configuration |
|---|---|
| `DATABASE_URL` | Existing PostgreSQL integration or verified connection URL; store credentials securely |
| `ENVIRONMENT` | `production` |
| `OPERATOR_TOKEN` | Long random runtime secret; use named scoped credentials after initial setup |
| `DEMO_ENABLED` | `true` for the competition demonstration |
| `PUBLIC_DEMO` | `true` for a dedicated fictional showcase database; `false` for restricted customer environments |
| `WORKER_ENABLED` | `true` |
| `SOURCE_REFRESH_SECONDS` | `3600`, or an explicitly chosen operational interval |
| `SOURCE_MAX_RECORDS` | `1000`; scanning is bounded and not a complete-coverage guarantee |
| `PORT` | `8080` |
| `ALLOWED_ORIGINS` | Explicit approved cross-origin mutation origins only if needed |
| `LLM_API_KEY` | Optional runtime secret; omit for labelled deterministic fallback |
| `LLM_BASE_URL`, `LLM_MODEL` | Provider configuration if using the optional model |

No secret belongs in frontend build variables, the Compose manifest, source control, or the Docker image. Public viewers cannot upload delivery documents, validate claims, answer operator questions, resolve reviews, or release holds. Use an operator credential for the full investigator demonstration. Keep real store data out of the showcase database.

## PostgreSQL TLS

The application accepts PostgreSQL connection URLs. Use certificate verification for the actual managed endpoint. Aiven documents `verify-full` connections with its project CA and describes when downloaded certificates and rotation updates are required. See [PostgreSQL Python connections](https://aiven.io/docs/products/postgresql/howto/connect-python) and [certificate requirements](https://aiven.io/docs/platform/concepts/tls-ssl-certificates).

Where the service requires a project CA, make its public certificate available inside the deployed container, for example `/app/certs/aiven-ca.pem`, and configure:

```text
postgresql://USER:URL_ENCODED_PASSWORD@SERVICE_HOST:PORT/DB?sslmode=verify-full&sslrootcert=/app/certs/aiven-ca.pem
```

This image contains no project-specific certificate because no project configuration was supplied. Add only the public CA to the deployment build or a supported mounted file. Never embed database passwords or client private keys. Do not assume an environment default overrides an explicit `sslmode` in an integration URL. Verify the final connection configuration in the deployed environment.

## Hosted acceptance checklist

Complete and retain a record of each check after the app is actually deployed:

1. Startup migrations finish and `/api/health` returns a successful database check.
2. The public HTTPS URL serves the current build. Record the deployed commit and image/version.
3. Unauthorized live reads and protected mutations fail. A scoped operator can access only assigned stores.
4. The investigator demo exposes two unconfirmed delivery candidates and a separate unresolved case.
5. Confirming the correct fictional delivery queues reassessment and records the 24-unit hold.
6. A conflicting supplier statement preserves the hold. Review resolution remains separate from release.
7. A saved-run evidence simulation changes no operational hold, inventory row, or event queue.
8. Source freshness, scan limits, and fallback mode are visible. Model mode matches the provider configuration.
9. Restart the app and confirm source bytes, decisions, holds, and review history persist. Exercise queued-work recovery in a separate staging workspace.
10. Verify database backups and a restore exercise, external monitoring, service limits, and HTTPS behavior before a customer pilot.

Record the actual URL only after the checks pass. `make e2e` and synthetic database tests belong in isolated local/staging environments, not a customer database. See [operations](operations.md), [investigator demonstration](investigator-demo.md), and [pilot proposal](pilot-plan.md).

Official documentation checked on 2026-10-22. Account availability and successful deployment remain unverified.
