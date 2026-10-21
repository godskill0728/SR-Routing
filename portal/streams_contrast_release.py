"""Portable streams report allowlist; generic paths, not source-identical routes."""
import binding_sweep_release
import portal_server

_NEW_ROUTES = {
  "/reports/streams-comparison/report.html": [
    "streams-comparison-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/streams-comparison/rows.csv": [
    "streams-comparison-rows.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/streams-comparison/summary.csv": [
    "streams-comparison-summary.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/streams-comparison/pairs.csv": [
    "streams-comparison-pairs.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/streams-comparison/summary.json": [
    "streams-comparison-summary.json",
    "application/json; charset=utf-8"
  ],
  "/reports/streams-comparison/report.md": [
    "streams-comparison-report.md",
    "text/markdown; charset=utf-8"
  ],
  "/reports/streams-comparison/rps.svg": [
    "streams-comparison-rps.svg",
    "image/svg+xml"
  ],
  "/reports/streams-comparison/p95_ms.svg": [
    "streams-comparison-p95_ms.svg",
    "image/svg+xml"
  ],
  "/reports/streams-comparison/p99_ms.svg": [
    "streams-comparison-p99_ms.svg",
    "image/svg+xml"
  ],
  "/reports/streams-comparison/router_cpu_cores.svg": [
    "streams-comparison-router_cpu_cores.svg",
    "image/svg+xml"
  ],
  "/reports/streams-comparison/client_cpu_cores.svg": [
    "streams-comparison-client_cpu_cores.svg",
    "image/svg+xml"
  ],
  "/reports/streams-comparison/SHA256SUMS.txt": [
    "streams-comparison-SHA256SUMS.txt",
    "text/plain; charset=utf-8"
  ],
  "/reports/streams-comparison/previous-index.html": [
    "streams-comparison-previous-index.html",
    "text/html; charset=utf-8"
  ],
  "/reports/streams-comparison/": [
    "streams-comparison-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/": [
    "streams-comparison-index.html",
    "text/html; charset=utf-8"
  ]
}
assert not ((set(_NEW_ROUTES) - {"/reports/"}) & set(portal_server.REPORT_ROUTES))
portal_server.REPORT_ROUTES.update(_NEW_ROUTES)

if __name__ == "__main__":
    portal_server.main()
