"""Refresh staged hashes after review; preserve immutable original-source hashes."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "SOURCE_MANIFEST.json"

def render():
    """Compute output metadata without modifying captured provenance or any file."""
    data = json.loads(MANIFEST.read_text())
    previous = {e["path"]: e for e in data["entries"]}
    entries = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p == MANIFEST or any(x in (".git", "__pycache__", ".venv", ".generated") for x in p.relative_to(ROOT).parts):
            continue
        rel = str(p.relative_to(ROOT))
        entry = previous.get(rel, {"path": rel, "source": {"kind": "authored portable export support"}, "source_sha256": None})
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        entry.update(sha256=digest, bytes=p.stat().st_size,
                     sanitized=bool(entry["source_sha256"] and entry["source_sha256"] != digest))
        if entry["sanitized"]:
            entry["change_note"] = {
                "portal/portal_server.py": "Loopback endpoints and bind default; portable reports root; generic historical report routes and filenames; manager mutation disabled unless explicitly enabled; omit backend URL from startup log.",
                "portal/compare_release.py": "Jaeger URL externally configured with disconnected loopback default; distinct portable trace service identities with explicit environment overrides; sanitized report-chain comment.",
                "portal/batch_release.py": "Eval URLs externally configured; pin explicitly labeled synthetic corpus instead of excluded production corpus.",
                "portal/fill_release.py": "Preserve final UI chain; add synthetic-data notice and honest report landing route.",
                **{f"portal/{name}_release.py": "Replace historical host/date-specific report routes and artifact filenames with generic allowlists; preserve distinct report/version slots; no report artifacts shipped and no source-identity claim."
                   for name in ("portal", "analysis", "binding", "binding_sweep", "streams_contrast")},
                "portal/litellm_portal_release.py": "Clarify that imported historical report modules install sanitized allowlists only, not live report artifacts.",
                **{f"routing/{mode}/config.yaml": "Replace operational backend/tracing DNS and environment labels with examples; disable tools and tracing by default; retain model decisions and distinct portable ON/OFF trace service names."
                   for mode in ("on", "off")},
                **{f"routing/{mode}/envoy.yaml": "Replace operational upstream DNS/host rewrites with chart-compatible example service; extproc and admin use loopback; preserve distinct model header-to-cluster routing."
                   for mode in ("on", "off")},
                "observability/build.py": "Replace source datasource UID, namespace, release selector and ON/OFF scrape DNS with portable examples; preserve dashboard queries and mode separation.",
                "observability/dashboard.json": "Regenerated-equivalent dashboard using example datasource UID; queries and metric interpretation unchanged.",
                "observability/scrapeconfig.json": "Regenerated-equivalent scrape template using example namespace/selector and distinct chart-compatible ON/OFF services.",
                "observability/test_build.py": "Update package-only fixture expectations for portable identifiers; assert distinct mode targets and exact builder/generated-artifact equality.",
                "tests/test_compare.py": "Update package-only trace fixtures to portable ON/OFF identities; test cross-mode rejection and explicit service-name override; original source tests untouched.",
            }[rel]
        else:
            entry.pop("change_note", None)
        entries.append(entry)
    data.update(entries=entries, package_policy={
        "manifest_self_hash": "excluded to avoid recursive hashes",
        "max_total_bytes": 5_000_000,
        "source_scope": ["live Portal application keys plus required JSON dependencies", "native OpenVINO overlay and four modified Go bridge files", "ON/OFF routing application config keys", "portable own Helm chart", "read-only observability source and offline tests"],
        "exclusions": ["Secrets and credential values", "full Kubernetes objects and annotations", "historical reports, raw prompts, private baselines and traces", "models, archives, native binaries, upstream .git/full source tree", "production provisioning or one-shot mutation scripts", "CSE/Pega and optional flow explorer"],
        "artifact_type": "sanitized public source bundle; original hashes and provenance retained; local validation is not native build or live integration proof"})
    return data

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--stdout", action="store_true", help="Render metadata without writing files")
    modes.add_argument("--check", action="store_true", help="Fail if stored metadata differs; do not write files")
    args = parser.parse_args()
    data = render()
    text = json.dumps(data, ensure_ascii=False, indent=2)+"\n"
    if args.stdout:
        print(text, end="")
        return
    if args.check:
        if MANIFEST.read_text() != text:
            raise SystemExit("Manifest is stale")
    else:
        MANIFEST.write_text(text)
    entries = data["entries"]
    print("Manifest:",len(entries),"entries;",sum(e["bytes"] for e in entries),"payload bytes;",sum(e["sanitized"] for e in entries),"modified captured sources")

if __name__ == "__main__": main()