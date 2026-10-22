"""Credential-free static deployment checks. Never reads .env or opens a socket.

This validates repository wiring, not hosting, actual credentials, or service health.
"""

import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    required = [
        "Dockerfile",
        "compose.aiven.yaml",
        ".dockerignore",
        "scripts/start.sh",
        "backend/alembic.ini",
        "backend/app/main.py",
        "frontend/package-lock.json",
        "data/fixtures/official_snapshot.json",
    ]
    checks = {f"file:{name}": (root / name).is_file() for name in required}
    docker = (root / "Dockerfile").read_text() if checks["file:Dockerfile"] else ""
    manifest = (
        (root / "compose.aiven.yaml").read_text()
        if checks["file:compose.aiven.yaml"]
        else ""
    )
    start = (
        (root / "scripts/start.sh").read_text()
        if checks["file:scripts/start.sh"]
        else ""
    )
    config = ast.parse((root / "backend/app/core/config.py").read_text())
    known = {
        node.target.id.upper()
        for node in ast.walk(config)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    names = []
    in_env = False
    for line in manifest.splitlines():
        stripped = line.strip()
        if stripped == "environment:":
            in_env = True
            continue
        if (
            in_env
            and line.startswith("      ")
            and ":" in stripped
            and not stripped.startswith("#")
        ):
            names.append(stripped.split(":", 1)[0])
    # PORT belongs to the entrypoint rather than Pydantic settings.
    unknown = sorted(set(names) - known - {"PORT"})
    checks.update(
        {
            "runtime_exposes_8080": "EXPOSE 8080" in docker,
            "runtime_nonroot_user": "USER recallops" in docker,
            "runtime_healthcheck": "HEALTHCHECK" in docker and "/api/health" in docker,
            "runtime_starts_migrations": "alembic" in start or "migrate.py" in start,
            "manifest_uses_root_dockerfile": "dockerfile: Dockerfile" in manifest,
            "manifest_production_mode": "ENVIRONMENT: production" in manifest,
            "manifest_public_fictional_demo": 'PUBLIC_DEMO: "true"' in manifest,
            "manifest_has_no_new_database": "image: postgres" not in manifest,
            "manifest_has_no_embedded_secrets": not any(
                f"{name}:" in manifest
                for name in [
                    "DATABASE_URL",
                    "OPERATOR_TOKEN",
                    "LLM_API_KEY",
                    "OPENAI_API_KEY",
                ]
            ),
            "manifest_env_names_known": bool(names) and not unknown,
        }
    )
    return {
        "checks": checks,
        "static_checks_pass": all(checks.values()),
        "unknown_environment_names": unknown,
        "deployment_status": "not_verified",
        "required_external_configuration": [
            "GitHub repository access",
            "Aiven Runtime project and app",
            "Existing managed PostgreSQL integration as DATABASE_URL",
            "Operator secret",
            "Verified database TLS and CA where required",
            "HTTPS URL and restart/persistence checks",
        ],
        "note": "Reads repository files only. Does not load .env, print secrets, connect to services, provision resources, or establish hosted readiness.",
    }


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["static_checks_pass"] else 1)
