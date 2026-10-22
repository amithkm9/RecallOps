"""Small non-destructive HTTP concurrency check, not a production capacity claim."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from statistics import median, quantiles
import httpx
from app.core.config import settings

headers = (
    {"Authorization": "Bearer " + settings.operator_token}
    if settings.operator_token
    else {}
)
paths = ["/api/health", "/api/dashboard?mode=replay", "/api/inventory?mode=replay"]
with httpx.Client(
    base_url="http://127.0.0.1:8080", headers=headers, timeout=30
) as client:

    def request(index):
        start = time.perf_counter()
        try:
            response = client.get(paths[index % len(paths)])
            return {
                "status": response.status_code,
                "ms": (time.perf_counter() - start) * 1000,
            }
        except httpx.HTTPError:
            return {"status": 0, "ms": (time.perf_counter() - start) * 1000}

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, range(120)))
    elapsed = time.perf_counter() - start
times = [r["ms"] for r in results]
report = {
    "requests": len(results),
    "concurrency": 8,
    "successes": sum(r["status"] == 200 for r in results),
    "elapsed_seconds": elapsed,
    "p50_ms": median(times),
    "p95_ms": quantiles(times, n=100, method="inclusive")[94],
    "requests_per_second": len(results) / elapsed,
    "scope": "Local read-only HTTP/DB smoke load; no production capacity or sustained-write claim.",
}
print(json.dumps(report, indent=2))
if len(sys.argv) > 1:
    with open(sys.argv[1], "w") as file:
        json.dump(report, file, indent=2)
sys.exit(0 if report["successes"] == len(results) else 1)
