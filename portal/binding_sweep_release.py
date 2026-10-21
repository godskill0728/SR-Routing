"""Portable binding sweep allowlist; generic paths, no report artifacts shipped."""
import binding_release
import portal_server

_NEW_ROUTES = {
  "/reports/cpu-binding-c-sweep/report.html": [
    "binding-c-sweep-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/cpu-binding-c-sweep/rows.csv": [
    "binding-c-sweep-rows.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/cpu-binding-c-sweep/summary.json": [
    "binding-c-sweep-summary.json",
    "application/json; charset=utf-8"
  ],
  "/reports/cpu-binding-c-sweep/report.md": [
    "binding-c-sweep-report.md",
    "text/markdown; charset=utf-8"
  ],
  "/reports/cpu-binding-c-sweep/cpu32-rps.svg": [
    "binding-c-sweep-cpu32-rps.svg",
    "image/svg+xml"
  ],
  "/reports/cpu-binding-c-sweep/cpu32-p95_ms.svg": [
    "binding-c-sweep-cpu32-p95_ms.svg",
    "image/svg+xml"
  ],
  "/reports/cpu-binding-c-sweep/cpu32-p99_ms.svg": [
    "binding-c-sweep-cpu32-p99_ms.svg",
    "image/svg+xml"
  ],
  "/reports/cpu-binding-c-sweep/cpu64-rps.svg": [
    "binding-c-sweep-cpu64-rps.svg",
    "image/svg+xml"
  ],
  "/reports/cpu-binding-c-sweep/cpu64-p95_ms.svg": [
    "binding-c-sweep-cpu64-p95_ms.svg",
    "image/svg+xml"
  ],
  "/reports/cpu-binding-c-sweep/cpu64-p99_ms.svg": [
    "binding-c-sweep-cpu64-p99_ms.svg",
    "image/svg+xml"
  ],
  "/reports/cpu-binding-c-sweep/previous-index.html": [
    "binding-c-sweep-previous-index.html",
    "text/html; charset=utf-8"
  ],
  "/reports/cpu-binding-c-sweep/SHA256SUMS.txt": [
    "binding-c-sweep-SHA256SUMS.txt",
    "text/plain; charset=utf-8"
  ],
  "/reports/cpu-binding-c-sweep/": [
    "binding-c-sweep-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/": [
    "binding-c-sweep-index.html",
    "text/html; charset=utf-8"
  ]
}
assert not ((set(_NEW_ROUTES) - {"/reports/"}) & set(portal_server.REPORT_ROUTES))
portal_server.REPORT_ROUTES.update(_NEW_ROUTES)

if __name__ == "__main__":
    portal_server.main()
