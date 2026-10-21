"""Portable report-only allowlist; generic paths, no historical artifacts shipped."""
import portal_release
import portal_server

SLUG = portal_release.SLUG
portal_server.REPORT_ROUTES[SLUG] = (
    "analysis.html", "text/html; charset=utf-8"
)
portal_server.REPORT_ROUTES[SLUG + "original-report.html"] = (
    "matrix-report.html", "text/html; charset=utf-8"
)
portal_server.REPORT_ROUTES[SLUG + "analysis.json"] = (
    "analysis.json", "application/json; charset=utf-8"
)
portal_server.REPORT_ROUTES[SLUG + "analysis.md"] = (
    "analysis.md", "text/markdown; charset=utf-8"
)


# NUMA512: exact static report allowlist only. No directory serving.
portal_server.REPORT_ROUTES.update({
  "/reports/": [
    "numa-v1-index.html",
    "text/html; charset=utf-8"
  ],
  "/reports/numa-binding/": [
    "numa-v1-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/numa-binding/data.json": [
    "numa-v1-data.json",
    "application/json; charset=utf-8"
  ],
  "/reports/numa-binding/groups.csv": [
    "numa-v1-groups.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/numa-binding/rounds.csv": [
    "numa-v1-rounds.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/numa-binding/binding-pairs.csv": [
    "numa-v1-binding-pairs.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/numa-binding/amx-pairs.csv": [
    "numa-v1-amx-pairs.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/numa-binding/audit.json": [
    "numa-v1-audit.json",
    "application/json; charset=utf-8"
  ],
  "/reports/numa-binding/report.md": [
    "numa-v1-report.md",
    "text/markdown; charset=utf-8"
  ],
  "/reports/numa-binding/SHA256SUMS.txt": [
    "numa-v1-SHA256SUMS.txt",
    "text/plain; charset=utf-8"
  ]
})


# Separate v1/v2 allowlist slots; neither version's report artifacts are shipped.
portal_server.REPORT_ROUTES.update({
  "/reports/": [
    "numa-v2-index.html",
    "text/html; charset=utf-8"
  ],
  "/reports/numa-binding/": [
    "numa-v2-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/numa-binding/v1.html": [
    "numa-v1-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/numa-binding/report-v2.html": [
    "numa-v2-report.html",
    "text/html; charset=utf-8"
  ],
  "/reports/numa-binding/analysis-v2.json": [
    "numa-v2-analysis-v2.json",
    "application/json; charset=utf-8"
  ],
  "/reports/numa-binding/merged-v2.csv": [
    "numa-v2-merged-v2.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/numa-binding/binding-v2.csv": [
    "numa-v2-binding-v2.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/numa-binding/amx-v2.csv": [
    "numa-v2-amx-v2.csv",
    "text/csv; charset=utf-8"
  ],
  "/reports/numa-binding/lineage-v2.json": [
    "numa-v2-lineage-v2.json",
    "application/json; charset=utf-8"
  ],
  "/reports/numa-binding/report-v2.md": [
    "numa-v2-report-v2.md",
    "text/markdown; charset=utf-8"
  ],
  "/reports/numa-binding/SHA256SUMS-v2.txt": [
    "numa-v2-SHA256SUMS-v2.txt",
    "text/plain; charset=utf-8"
  ]
})

if __name__ == "__main__":
    portal_server.main()