# Export validation — 2026-10-21

## Executed

- `python3 -B tools/validate.py`: PASS.
- Python memory compile of staged Python sources: PASS, no compileall output artifacts.
- Isolated suites: compare 10, batch 17, race 11, parallel 16, English 5, C15 4, portable 6, observability 8 = **77 tests passed**.
- Latest `fill_release` handler imports all prior wrappers and serves homepage, health, comparison HTML, 3 JS assets, report notice and synthetic corpus: HTTP 200 using an ephemeral loopback port.
- All 83 excluded historical report routes return 404; 85 report allowlist entries retain distinct report/version slots under generic names. Disabled manager mutation returns 403; synthetic corpus SHA validation passes.
- Node `--check`: **10** raw/rendered/inline JavaScript snippets pass.
- `helm lint deploy/chart`: PASS (only optional icon recommendation).
- Full stack `helm template` with placeholder images and PVC: **11 resources**, zero Secret resources; YAML parses successfully. No install/apply was run.
- Metadata-only heuristic secret scan: **zero findings**.
- Independent **gitleaks 8.30.1** directory scan: **PASS, zero findings**, with `--redact=100`. Initial export artifacts and the final sanitized source bundle were scanned, including untracked files; this was not a Git-history-only scan. Secret scanning is not proof of absence of every sensitive identifier.
- Earlier local Playwright check of this source bundle: desktop and 390×844 mobile comparison surface visible; synthetic notice present; fullscreen control present; 3 external scripts; **zero page errors, zero non-GET/non-loopback requests**. No Start button was clicked, no eval/LLM calls occurred. Preview server was stopped afterward. Final sanitization was revalidated by the full offline command above, not a new browser/live performance run.

## Corrections found during validation

- Earlier historical wrappers overwrite `/reports/`; final wrapper now explicitly maps it to the portable notice. Re-run passes.
- Routing/Envoy service DNS, tracing identities, observability datasource/namespace/selector/targets, and historical report routes/filenames now use portable examples. Package-only tests verify three distinct model header/cluster matches, both raw and rendered configs, distinct ON/OFF scrape/trace matching, explicit trace-service overrides, and generated observability artifacts matching their builder. Original source fixtures were not modified.
- Historical report names are intentionally not source-identical URLs; no actual reports were included. Original source hashes and provenance remain separate from refreshed output hashes, sizes and change notes in [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json).
- Source capture used read-only Deployment/ConfigMap queries with certificate validation; never Secret resources. No live cluster operation was needed for final sanitization.
- Integrated browser could not reach remote loopback; existing locally installed Playwright was used instead.

## Validation boundaries

- Native C++/Go/Rust build, Docker image build/push, model export, real inference, hardware AMX verification, cluster deployment and live end-to-end routing **not executed**.
- Upstream full commit provenance is unverified. Native base-file hashes are recorded; a directory/tag label alone does not prove image reproducibility. Existing upstream license and headers are preserved; publication of custom sources is the owner's decision, with no new license invented here.
- The legacy chat route is not an authenticated/bounded multi-tenant gateway. Its ingress requirements and body/concurrency risks are documented in [SECURITY.md](SECURITY.md); passing local tests does not remove those deployment requirements.