"""Portable CPU report allowlist; generic paths, no report artifacts shipped."""
import analysis_release
import portal_server

portal_server.REPORT_ROUTES.update({
  "/reports/cpu-binding/report.html": [
    "binding-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/cpu-binding/rounds.csv": [
    "binding-rounds.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/cpu-binding/comparisons.csv": [
    "binding-comparisons.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/cpu-binding/summary.json": [
    "binding-summary.json",
    "application/json; charset=utf-8"
  ],
  "/reports/cpu-binding/report.md": [
    "binding-report.md",
    "text/markdown; charset=utf-8"
  ],
  "/reports/cpu-binding/SHA256SUMS.txt": [
    "binding-SHA256SUMS.txt",
    "text/plain; charset=utf-8"
  ],
  "/reports/cpu-binding/": [
    "binding-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/": [
    "binding-index.html",
    "text/html; charset=utf-8"
  ],
  "/reports/cpu-binding/previous-index.html": [
    "numa-v2-index.html",
    "text/html; charset=utf-8"
  ]
})

if __name__ == "__main__":
    portal_server.main()
