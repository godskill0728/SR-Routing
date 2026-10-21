"""Portable historical report allowlist; generic names, no report artifacts shipped.

Routes and filenames are sanitized, not byte-identical to the captured source.
The base handler confines file serving; ingress authentication is external.
"""
import portal_server

SLUG = "/reports/cpu-matrix/"
FILES = {
    "report.html": "text/html; charset=utf-8",
    "REPORT.md": "text/markdown; charset=utf-8",
    "summary-on.csv": "text/csv; charset=utf-8",
    "summary-off.csv": "text/csv; charset=utf-8",
    "paired.csv": "text/csv; charset=utf-8",
    "rounds.csv": "text/csv; charset=utf-8",
    "summary.json": "application/json; charset=utf-8",
    "audit.json": "application/json; charset=utf-8",
    "downloads.html": "text/html; charset=utf-8",
}
NEW_ROUTES = {
    SLUG + name: ("matrix-" + name, mime)
    for name, mime in FILES.items()
}
NEW_ROUTES[SLUG] = NEW_ROUTES[SLUG + "report.html"]
NEW_ROUTES["/reports/archive/"] = (
    "historic-index.html", "text/html; charset=utf-8"
)
assert not (portal_server.REPORT_ROUTES.keys() & NEW_ROUTES.keys())
portal_server.REPORT_ROUTES.update(NEW_ROUTES)

if __name__ == "__main__":
    portal_server.main()