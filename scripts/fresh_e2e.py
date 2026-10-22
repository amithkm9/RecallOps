"""Create an isolated, empty deployment and test real HTTP workflows from scratch.

Run: python3 scripts/fresh_e2e.py
Requires Docker Compose and installed frontend test dependencies. No browser,
customer database, local .env, external model, or live recall API is used.
Containers are stopped afterward; their isolated volume is retained for inspection.
"""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class FreshRun:
    def __init__(self, output):
        self.output = output
        self.directory = Path(tempfile.mkdtemp(prefix="recallops-fresh-"))
        self.project = "recallops-fresh-" + secrets.token_hex(4)
        self.password = secrets.token_hex(24)
        self.bootstrap = secrets.token_urlsafe(40)
        self.env = {
            **os.environ,
            "FRESH_DB_PASSWORD": self.password,
            "FRESH_BOOTSTRAP_TOKEN": "",
            "FRESH_ENVIRONMENT": "development",
        }
        self.token = None
        self.base = ""
        self.report = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "project": self.project,
            "transport": "Real HTTP API; frontend unit tests and production build; no browser",
            "isolation": "New Compose project, network, PostgreSQL container and volume",
            "checks": [],
            "limitations": [
                "Archived official recall data and fictional business records only.",
                "External model requests and live official API synchronization disabled.",
                "Browser rendering/clicks and Aiven deployment are not exercised.",
                "Crash injection is exercised by backend regression tests on a separate test database.",
            ],
        }
        config = {
            "services": {
                "db": {
                    "image": "postgres:16-alpine",
                    "environment": {
                        "POSTGRES_USER": "recallops",
                        "POSTGRES_PASSWORD": "${FRESH_DB_PASSWORD}",
                        "POSTGRES_DB": "recallops",
                    },
                    "volumes": ["fresh_data:/var/lib/postgresql/data"],
                    "healthcheck": {
                        "test": ["CMD-SHELL", "pg_isready -U recallops -d recallops"],
                        "interval": "2s", "timeout": "3s", "retries": 30,
                    },
                },
                "app": {
                    "build": {"context": str(ROOT)},
                    "ports": ["127.0.0.1::8080"],
                    "environment": {
                        "DATABASE_URL": "postgresql+psycopg://recallops:${FRESH_DB_PASSWORD}@db:5432/recallops",
                        "ENVIRONMENT": "${FRESH_ENVIRONMENT}",
                        "OPERATOR_TOKEN": "${FRESH_BOOTSTRAP_TOKEN}",
                        "LLM_API_KEY": "", "OPENAI_API_KEY": "",
                        "DEMO_ENABLED": "true", "PUBLIC_DEMO": "false",
                        "WORKER_ENABLED": "true", "SOURCE_REFRESH_SECONDS": "0",
                        "MUTATION_LIMIT_PER_MINUTE": "10000",
                    },
                    "depends_on": {"db": {"condition": "service_healthy"}},
                },
            },
            "volumes": {"fresh_data": {}},
        }
        self.manifest = self.directory / "compose.json"
        self.manifest.write_text(json.dumps(config, indent=2))

    def command(self, args, timeout=600):
        result = subprocess.run(args, cwd=ROOT, env=self.env, text=True,
                                capture_output=True, timeout=timeout)
        # Diagnostics must never contain even the disposable bootstrap credential.
        diagnostic = (result.stdout + result.stderr).replace(self.password, "[redacted]")
        diagnostic = diagnostic.replace(self.bootstrap, "[redacted]")
        if result.returncode:
            raise RuntimeError(f"Command failed: {args[:3]}\n{diagnostic[-6000:]}")
        return result.stdout

    def compose(self, *args, timeout=600):
        return self.command(["docker", "compose", "--env-file", "/dev/null", "-p",
                             self.project, "-f", str(self.manifest), *args], timeout)

    def check(self, name, condition=True, **details):
        if not condition:
            raise AssertionError(name)
        self.report["checks"].append({"name": name, **details})
        print(f"PASS {len(self.report['checks']):02}: {name}", flush=True)

    def request(self, path, body=None, *, token="current", expected=200,
                raw=False, headers=None, content=None):
        actual = self.token if token == "current" else token
        h = dict(headers or {})
        if actual:
            h["Authorization"] = "Bearer " + actual
        if body is not None:
            h["Content-Type"] = "application/json"
            content = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=content, headers=h)
        try:
            response = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            status, payload = response.status, response.read()
        if status != expected:
            raise AssertionError(f"{req.get_method()} {path}: expected {expected}, got {status}: {payload[:1200]!r}")
        if raw:
            return payload
        return json.loads(payload) if payload else None

    def upload(self, path, filename, content, fields=None, *, expected=202, token="current"):
        boundary = "fresh-" + secrets.token_hex(16)
        chunks = []
        for name, value in (fields or {}).items():
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        media = "application/pdf" if filename.endswith(".pdf") else "text/csv"
        chunks.extend([
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {media}\r\n\r\n'.encode(),
            content, f"\r\n--{boundary}--\r\n".encode(),
        ])
        return self.request(path, content=b"".join(chunks),
                            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                            expected=expected, token=token)

    def ready(self):
        self.base = "http://" + self.compose("port", "app", "8080").strip()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if self.request("/api/health")["status"] == "ok":
                    return
            except (OSError, AssertionError):
                time.sleep(1)
        raise AssertionError("Fresh app did not become healthy")

    def settled(self, incident):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            overview = self.request(f"/api/incidents/{incident}/investigator")
            run = overview["latest_run"]
            if run and run["status"] == "completed" and not overview["reassessment_pending"]:
                return overview, self.request(f"/api/incidents/{incident}")
            time.sleep(0.5)
        raise AssertionError(f"Investigation {incident} did not settle")

    @staticmethod
    def holds(detail):
        return [h for h in detail["holds"] if h["status"] == "active"]

    @staticmethod
    def current(detail):
        return [d for d in detail["decisions"] if d["run_id"] == detail["runs"][-1]["id"]]

    def credential(self, role, store_ids=()):
        return self.request("/api/operations/credentials", {
            "name": "Fresh test " + role, "role": role, "store_ids": list(store_ids),
        })

    def run(self):
        print("Building a new app image and starting an empty isolated database…", flush=True)
        self.compose("up", "-d", "--build", "--wait", timeout=900)
        self.ready()
        self.report["test_url"] = self.base
        self.check("New database has no stores, recalls, credentials, inventory or incidents",
                   self.request("/api/stores") == [] and self.request("/api/recalls") == []
                   and self.request("/api/operations/credentials") == []
                   and self.request("/api/inventory?mode=live")["total"] == 0
                   and self.request("/api/incidents?mode=live")["items"] == [])
        html = self.request("/", raw=True).decode()
        asset = re.search(r'src="([^"]+\.js)"', html)
        self.check("Fresh production frontend bundle is served", bool(asset)
                   and len(self.request(asset[1], raw=True)) > 1000)
        self.request("/api/operations/refreshes", token="deliberately-invalid", expected=401)
        self.check("Invalid-token error recovers when token is cleared",
                   self.request("/api/operations/refreshes", token=None) == [])
        admin = self.credential("admin")
        self.token = admin["token"]
        self.check("Administrator created through public local setup authenticates",
                   self.request("/api/operations/credentials")[0]["id"] == admin["id"])

        store = self.request("/api/stores", {"name": "Fresh fictional grocery"})
        other = self.request("/api/stores", {"name": "Fresh separate store"})
        operator = self.credential("operator", [store["id"]])
        viewer = self.credential("viewer", [store["id"]])
        integration = self.credential("integration", [store["id"]])
        self.check("Store and all named roles created from scratch",
                   len(self.request("/api/stores")) == 2
                   and len(self.request("/api/operations/credentials")) == 4)
        self.request("/api/stores", {"name": "Not allowed"}, token=viewer["token"], expected=403)
        self.request("/api/recalls/sync", {"source": "snapshot"}, token=integration["token"], expected=403)
        self.check("Viewer writes and integration administration are blocked")
        self.check("Scoped store listing hides other stores",
                   [s["id"] for s in self.request("/api/stores", token=operator["token"])] == [store["id"]])

        print("Importing real archived recall records and newly authored fictional inventory…", flush=True)
        sync = self.request("/api/recalls/sync", {"source": "snapshot"})
        recalls = self.request("/api/recalls")
        self.check("Archived official source imported into empty database", len(recalls) == 4)
        duplicate = self.request("/api/recalls/sync", {"source": "snapshot"})
        self.check("Repeat source import does not duplicate recalls", len(self.request("/api/recalls")) == 4)
        refreshes = self.request("/api/operations/refreshes")
        self.request(f"/api/operations/refreshes/{refreshes[0]['id']}/rejections")
        self.check("Source history and rejected-record inspection are available", len(refreshes) == 2)
        csv = (
            "sku,product_name,gtin,lot,quantity,supplier,expires_on\n"
            "SALMON-KNOWN,Fictional salmon,3760099533007,OTHER-DEMO-BATCH,18,Fictional supplier,2024-12-20\n"
            "SALMON-DELIVERY,Fictional salmon,3760099533007,,24,Fictional supplier,2024-12-20\n"
            "INVALID,Fictional invalid row,not-a-barcode,,abc,Fictional supplier,2024-12-20\n"
        ).encode()
        fields = {"mode": "live", "store_id": store["id"]}
        imported = self.upload("/api/inventory/import", "fresh-stock.csv", csv, fields, expected=200)
        self.check("Inventory imports valid rows and identifies invalid line",
                   imported["imported"] == 2 and imported["errors"][0]["row"] == 4)
        self.upload("/api/inventory/import", "same-stock.csv", csv, fields, expected=200)
        stock_list = self.request("/api/inventory?mode=live")
        self.check("Repeated inventory import preserves two stock identities", stock_list["total"] == 2)
        stock = next(s for s in stock_list["items"] if s["sku"] == "SALMON-DELIVERY")
        incidents = self.request("/api/incidents?mode=live&search=2024-12-0201")["items"]
        self.check("Imported stock automatically creates a matching incident", len(incidents) == 1)
        incident = incidents[0]["id"]
        self.report["primary_incident_id"] = incident
        base = f"/api/incidents/{incident}"
        overview, detail = self.settled(incident)
        self.check("Missing batch requires review without creating a hold",
                   not self.holds(detail) and {d["verdict"] for d in self.current(detail)} == {"review", "unaffected"})
        self.check("Inventory search and dashboard reflect imported quantities",
                   self.request("/api/inventory?mode=live&search=SALMON-DELIVERY")["total"] == 1
                   and self.request("/api/dashboard?mode=live")["inventory_units"] == 42)

        delivery = (
            "delivery_id,sku,gtin,lot,quantity,expires_on,reference\n"
            "D-104,SALMON-DELIVERY,3760099533007,24326020,24,2024-12-20,Fictional receiving reference D-104\n"
            "D-105,SALMON-DELIVERY,3760099533007,OTHER-DELIVERY,24,2024-12-20,Fictional other shipment D-105\n"
        ).encode()
        source = self.upload(base + "/investigator/deliveries", "fresh-deliveries.csv", delivery)
        repeated = self.upload(base + "/investigator/deliveries", "renamed.csv", delivery)
        overview, detail = self.settled(incident)
        self.check("Delivery import retains two unconfirmed candidates",
                   source["claims_count"] == 2 and all(c["status"] == "unconfirmed" for c in overview["claims"]))
        self.check("Identical document bytes deduplicate across filenames",
                   repeated["duplicate"] and repeated["document_id"] == source["document_id"] and repeated["event_id"] is None)
        self.check("Original delivery download is byte-for-byte identical",
                   self.request(base + "/investigator/documents/" + source["document_id"], raw=True) == delivery)
        selected = next(c for c in overview["claims"] if c["delivery_id"] == "D-104")
        validation = {"inventory_lot_id": stock["id"], "accept": True,
                      "reason": "Fictional receiving reference checked against all 24 units."}
        self.request(base + f"/investigator/claims/{selected['id']}/validate", validation, token=None, expected=403)
        self.request(base + f"/investigator/claims/{selected['id']}/validate", validation, token=viewer["token"], expected=403)
        self.check("Claim acceptance requires authorized human credentials")
        accepted = self.request(base + f"/investigator/claims/{selected['id']}/validate", validation,
                                token=operator["token"], expected=202)
        overview, detail = self.settled(incident)
        held = self.holds(detail)
        self.check("Confirmed delivery creates exactly one 24-unit hold", len(held) == 1 and held[0]["quantity"] == 24)
        self.check("Accepted evidence does not overwrite warehouse batch",
                   next(s for s in overview["inventory"] if s["id"] == stock["id"])["lot"] is None)
        self.check("Accepted association creates a scoped retrieval hint", bool(overview["retrieval_hints"]))
        self.check("Evidence records carry source row, validation and actor",
                   selected["locator"] == "CSV row 2" and any(e["id"] == accepted["evidence_id"]
                   and e["payload"]["actor"] == "Fresh test operator" for e in detail["evidence"]))
        run = overview["latest_run"]["id"]
        options = self.request(base + "/investigator/simulation-options?run_id=" + run)
        absent = self.request(base + "/investigator/simulate", {"run_id": run, "evidence_ids": []})
        present = self.request(base + "/investigator/simulate", {"run_id": run, "evidence_ids": options["default_evidence_ids"]})
        self.check("Frozen evidence comparison changes review to affected",
                   next(d for d in absent["decisions"] if d["inventory_lot_id"] == stock["id"])["verdict"] == "review"
                   and next(d for d in present["decisions"] if d["inventory_lot_id"] == stock["id"])["verdict"] == "affected")
        after = self.request(base)
        self.check("Simulation creates no operational decisions or holds",
                   after["holds"] == detail["holds"] and len(after["decisions"]) == len(detail["decisions"]))
        self.request(base + "/investigator/resolve", {
            "expected_run_id": run, "evidence_ids": [accepted["evidence_id"]],
            "reason": "Reviewed confirmed receiving record; affected stock remains held.",
        }, token=operator["token"])
        after = self.request(base)
        self.check("Human resolution retains protective hold", after["incident"]["review_status"] == "resolved" and self.holds(after) == held)

        statement = {"inventory_lot_id": stock["id"], "supplier": "Fictional supplier",
                     "lot": "OTHER-DELIVERY", "reference": "FRESH-CONTRADICTION",
                     "notes": "Fictional supplier statement contradicts the confirmed shipment."}
        first = self.request(base + "/supplier-evidence", statement, expected=202)
        again = self.request(base + "/supplier-evidence", statement, expected=202)
        overview, detail = self.settled(incident)
        self.check("Supplier submissions are idempotent", first["evidence_id"] == again["evidence_id"] and first["event_id"] == again["event_id"])
        self.check("Contradiction reopens review and preserves the same hold",
                   any(d["verdict"] == "conflict" for d in self.current(detail))
                   and detail["incident"]["review_status"] != "resolved" and self.holds(detail) == held)
        self.request(base + "/investigator/resolve", {
            "expected_run_id": run, "evidence_ids": [accepted["evidence_id"]],
            "reason": "Attempting review with outdated investigation snapshot.",
        }, expected=409)
        self.check("Stale investigation cannot be marked resolved")
        correction = self.request(base + "/supplier-evidence", {
            **statement, "lot": "24326020", "reference": "FRESH-CORRECTION",
            "notes": "Fictional correction confirms the receiving batch.",
            "supersedes_evidence_id": first["evidence_id"],
        }, expected=202)
        overview, detail = self.settled(incident)
        self.check("Supplier correction preserves both original and superseding evidence",
                   {first["evidence_id"], correction["evidence_id"]}.issubset({e["id"] for e in detail["evidence"]})
                   and self.holds(detail) == held and any(d["verdict"] == "affected" for d in self.current(detail)))
        self.request(base + "/review", {"action": "assign", "reason": "Named reviewer takes responsibility for this fictional case."}, token=operator["token"])
        self.check("Review assignment records the named operator", self.request(base)["incident"]["assigned_to"] == "Fresh test operator")
        self.request(base + "/review", {"action": "close", "reason": "Attempting closure while stock is still held.",
                     "expected_run_id": detail["runs"][-1]["id"], "evidence_ids": self.current(detail)[0]["evidence_ids"]}, expected=409)
        self.check("Affected held case cannot be closed")

        # Use the real PDF fixture generator already exercised by regression tests.
        pdf_code = "import base64,runpy; m=runpy.run_path('/app/backend/tests/test_delivery_pdf.py'); print(base64.b64encode(m['delivery_pdf']()).decode())"
        import base64
        pdf = base64.b64decode(self.compose("exec", "-T", "-e", "PYTHONPATH=/app/backend", "app", "python", "-c", pdf_code).strip())
        pdf_import = self.upload(base + "/investigator/deliveries", "fresh-delivery.pdf", pdf)
        overview, detail = self.settled(incident)
        pdf_claim = next(c for c in overview["claims"] if c["document_id"] == pdf_import["document_id"])
        self.check("Real PDF upload extracts one labelled claim with page provenance",
                   pdf_import["claims_count"] == 1 and pdf_claim["locator"] == "PDF page 1")
        self.check("Preserved PDF download matches uploaded bytes",
                   self.request(base + "/investigator/documents/" + pdf_import["document_id"], raw=True) == pdf)

        event = {"external_id": "fresh-warehouse-1", "sequence": 2,
                 "stock": {"sku": "CONNECTOR-1", "product_name": "Fictional integration stock",
                           "gtin": "00000000000000", "lot": "A", "quantity": 7}}
        path = f"/api/stores/{store['id']}/inventory-events"
        self.request(path, event, token=integration["token"], expected=202)
        repeated = self.request(path, event, token=integration["token"], expected=202)
        self.request(path, {**event, "sequence": 1}, token=integration["token"], expected=409)
        self.request(path, {**event, "stock": {**event["stock"], "quantity": 8}}, token=integration["token"], expected=409)
        self.request(f"/api/stores/{other['id']}/inventory-events", event, token=integration["token"], expected=403)
        self.check("Ordered inventory events reject stale, conflicting and cross-store updates", repeated["duplicate"])
        self.request(path, {**event, "sequence": 3, "stock": {**event["stock"], "quantity": 8}}, token=integration["token"], expected=202)
        self.check("Higher sequence updates stock successfully")

        print("Testing new demonstrations, targeted answers, case closure and evaluation…", flush=True)
        demo = self.request("/api/investigator/demo", {})
        unresolved = demo["unresolved_incident_id"]
        gap, gap_detail = self.settled(unresolved)
        self.check("New unresolved companion asks a question without a hold", bool(gap["questions"]) and not self.holds(gap_detail))
        self.request(f"/api/incidents/{unresolved}", token=operator["token"], expected=403)
        self.check("Store-scoped operator cannot inspect another store incident")
        answer = self.request(f"/api/incidents/{unresolved}/investigator/answers", {
            "inventory_lot_id": gap["inventory"][0]["id"], "lot": "OTHER-DEMO-BATCH",
            "expires_on": "2024-12-20", "reference": "FRESH-PHYSICAL-CHECK",
            "reason": "Fictional physical batch check of all seven packets.",
        }, expected=202)
        gap, gap_detail = self.settled(unresolved)
        self.check("Sourced physical observation resolves the unknown batch",
                   all(d["verdict"] == "unaffected" for d in self.current(gap_detail)) and not self.holds(gap_detail))
        review = {"action": "close", "reason": "Reviewed the unaffected stock and contributing evidence.",
                  "expected_run_id": gap_detail["runs"][-1]["id"],
                  "evidence_ids": self.current(gap_detail)[0]["evidence_ids"]}
        self.request(f"/api/incidents/{unresolved}/review", review)
        self.check("Settled unaffected case closes", self.request(f"/api/incidents/{unresolved}")["incident"]["review_status"] == "closed")
        self.request(f"/api/incidents/{unresolved}/review", {"action": "reopen", "reason": "Reopen this fictional case for another review."})
        self.check("Closed review can be explicitly reopened", self.request(f"/api/incidents/{unresolved}")["incident"]["review_status"] == "open")
        replay = self.request("/api/demo/replay/start", {})
        replay_id = replay["id"]
        self.request("/api/demo/replay/next", {"replay_id": replay_id, "expected_step": 0})
        repeated = self.request("/api/demo/replay/next", {"replay_id": replay_id, "expected_step": 0})
        self.check("Replay advance is idempotent", repeated["step"] == 1)
        completed = self.request("/api/demo/replay/next", {"replay_id": replay_id, "expected_step": 1})
        replay_detail = self.request(f"/api/incidents/{completed['incident_id']}")
        self.check("Classic three-stage replay completes with held conflict",
                   completed["step"] == 2 and len(completed["events"]) == 3
                   and any(d["verdict"] == "conflict" for d in self.current(replay_detail))
                   and sum(h["quantity"] for h in self.holds(replay_detail)) == 24)
        self.request("/api/demo/replay/start", {})
        self.check("New replay archives rather than deletes old evidence",
                   len(self.request(f"/api/incidents/{completed['incident_id']}")["decisions"]) == len(replay_detail["decisions"]))

        benchmark = self.request("/api/evaluation/run", {})
        comparison = self.request("/api/investigator/evaluation", {"include_model": False, "include_memory": True})
        self.report["benchmark"] = {"sample_size": benchmark["sample_size"], "results": benchmark["results"]}
        self.report["comparison"] = {"sample_size": comparison["sample_size"], "results": comparison["results"]}
        self.check("Both built-in evaluations execute on the fresh deployment",
                   benchmark["sample_size"] == 22 and comparison["sample_size"] == 12 and len(comparison["results"]) == 4)
        external = json.loads((ROOT / "data/fixtures/benchmark-import-example.json").read_text())
        measured = self.request("/api/evaluation/labeled", external)
        external_investigator = json.loads((ROOT / "data/fixtures/investigator-import-example.json").read_text())
        measured_investigator = self.request("/api/investigator/evaluation", {
            "include_model": False, "include_memory": True, "dataset": external_investigator,
        })
        self.check("External labelled evaluations retain expected case counts",
                   measured["sample_size"] == 3 and measured_investigator["sample_size"] == 2)
        self.request("/api/evaluation/labeled", {"source": "Missing labels"}, expected=422)
        self.check("Invalid evaluation dataset rejected")
        model = self.request("/api/settings/model-check", {})
        self.check("Absent model configuration is reported without a provider call", model["success"] is False)

        # Consume a real SSE progress message using an existing audit cursor.
        history = self.request(base + "/history")
        req = urllib.request.Request(self.base + "/api/events/stream", headers={
            "Authorization": "Bearer " + self.token, "Last-Event-ID": history[0]["id"],
        })
        with urllib.request.urlopen(req, timeout=10) as stream:
            lines = [stream.readline().decode() for _ in range(4)]
        self.check("Live event stream delivers persisted progress", any(line.startswith("data:") for line in lines))
        self.check("Worker heartbeat is healthy with no failed events",
                   self.request("/api/operations/health")["status"] == "ok")
        before = self.request(base)
        self.compose("restart", "app")
        self.ready()
        after = self.request(base)
        self.check("App restart preserves decisions, holds and source documents",
                   before["decisions"] == after["decisions"] and before["holds"] == after["holds"]
                   and before["evidence"] == after["evidence"])

        print("Checking production authentication, revocation, release and backup restore…", flush=True)
        self.env["FRESH_ENVIRONMENT"] = "production"
        self.env["FRESH_BOOTSTRAP_TOKEN"] = self.bootstrap
        self.compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "app")
        self.ready()
        self.request("/api/stores", token=None, expected=401)
        self.request("/api/operations/credentials", {"name": "Blocked", "role": "admin"}, token=None, expected=401)
        self.check("Production mode blocks unauthenticated reads and credential creation")
        self.check("Named administrator survives production restart", len(self.request("/api/operations/credentials")) == 4)
        self.request("/api/operations/credentials/" + viewer["id"] + "/revoke", {})
        self.request("/api/stores", token=viewer["token"], expected=401)
        self.check("Revoked credential cannot authenticate")
        self.request(base + "/review", {"action": "release_hold", "hold_id": held[0]["id"],
                     "reason": "Fictional end-to-end test of explicit authorized release."}, token=operator["token"])
        self.check("Authorized hold release is attributed and does not erase decisions",
                   not self.holds(self.request(base)) and bool(self.request(base)["decisions"]))
        self.request("/api/stores", {"name": "Rejected cross-origin"},
                     headers={"Origin": "https://untrusted.invalid"}, expected=403)
        self.check("Cross-origin mutation rejected")

        self.compose("exec", "-T", "db", "pg_dump", "-U", "recallops", "-d", "recallops", "-Fc", "-f", "/tmp/fresh-backup.dump")
        self.compose("exec", "-T", "db", "createdb", "-U", "recallops", "fresh_restore")
        self.compose("exec", "-T", "db", "pg_restore", "-U", "recallops", "--exit-on-error", "--no-owner", "-d", "fresh_restore", "/tmp/fresh-backup.dump")
        sql = "SELECT (SELECT count(*) FROM decisions), (SELECT count(*) FROM evidence), (SELECT count(*) FROM inventory_holds), (SELECT count(*) FROM decision_evidence de LEFT JOIN evidence e ON e.id=de.evidence_id WHERE e.id IS NULL);"
        original = self.compose("exec", "-T", "db", "psql", "-U", "recallops", "-d", "recallops", "-Atc", sql).strip()
        restored = self.compose("exec", "-T", "db", "psql", "-U", "recallops", "-d", "fresh_restore", "-Atc", sql).strip()
        self.check("Backup restores equal decision/evidence/hold counts with zero orphan links",
                   original == restored and restored.split("|")[-1] == "0", counts=restored)

        print("Running backend regression tests on another empty test database and frontend unit tests…", flush=True)
        tests = self.compose("run", "--rm", "-T", "--no-deps", "-v", str(ROOT) + ":/verify:ro",
                             "app", "python", "/verify/scripts/container_tests.py")
        match = re.search(r"(\d+) passed", tests)
        self.check("Backend regression suite passes including fault-injection recovery", bool(match), passed=int(match[1]) if match else 0)
        frontend = self.command(["npm", "--prefix", "frontend", "test", "--", "--run"])
        match = re.search(r"Tests\s+(\d+) passed", frontend)
        self.check("Frontend component/unit suite passes", bool(match), passed=int(match[1]) if match else 0)
        self.report["status"] = "passed"

    def finish(self):
        try:
            self.compose("stop", timeout=90)
            self.report["cleanup"] = "Isolated containers stopped; test volume retained; original app untouched."
        except Exception as exc:
            self.report["cleanup"] = str(exc)
        self.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.report["check_count"] = len(self.report["checks"])
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(self.report, indent=2) + "\n")
        print(f"Report: {self.output}\nStatus: {self.report.get('status')} · {len(self.report['checks'])} checks", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/fresh-e2e-results.json")
    args = parser.parse_args()
    run = FreshRun(args.output)
    try:
        run.run()
    except Exception as exc:
        run.report["status"] = "failed"
        run.report["error"] = str(exc).replace(run.password, "[redacted]").replace(run.bootstrap, "[redacted]")
        print("FAILED: " + run.report["error"], flush=True)
        raise
    finally:
        run.finish()


if __name__ == "__main__":
    main()
