# Executable unified acceptance

Run on Python 3.12 with `requirements-execution.txt`, the existing locked frontend, Chromium and stable LibreOffice. Personal provider credentials and institutional files are not required or propagated.

```bash
python -m cdf_gco_crms.acceptance.unified --mode public-synthetic --interfaces cli,mcp,react --exports word,excel,pdf --report-dir build/unified-acceptance
```

Use a new empty evidence directory. The harness creates a private temporary database and ephemeral one-hour development token, generates the fixed fictional cooperation DOCX, invokes the actual application CLI in separate processes, runs deterministic review and an explicitly mocked debate through the existing orchestrator, records a synthetic calibration decision and generates actual draft report jobs.

It starts an authenticated MCP HTTP process and uses an independent official SDK client for initialization, schema discovery, reads, idempotent CLI-operation replay, a genuine draft calibration mutation, authorization errors and chunked artifact retrieval. React runs against the same database; Playwright captures identifiers/metric fractions from rendered DOM, downloads persisted artifact bytes and visits actual debate/reference/MAT views on desktop and iPhone widths. It does not execute business logic by browser automation for the CLI or MCP paths.

Word/XML, native Excel charts/formulas, independent Calc cached values and PDF page rendering are validated against the same case and run. The source XLSX is hashed before/after recalculating a copy. Generated evidence includes command exit statuses, protocol discovery/invocations, browser JUnit/JSON, provenance, export validation, screenshots, cross-interface matrix, file hashes and a leakage scan.

For reproducible isolated acceptance, build `Dockerfile.libreoffice` as `cdf-lo-stable`, then `Dockerfile.execution-acceptance` as `cdf-execution-acceptance`. Mount a tracked-source archive at `/repo`, an empty writable evidence directory at `/evidence`, and copy `/opt/cdf-web/node_modules` into `/repo/apps/web/node_modules`. Run with `--init --network none --cap-drop ALL --security-opt no-new-privileges` as the source/evidence owner. The workflow `unified-execution.yml` contains the exact supported commands.

Existing full Python tests, mandatory stable-engine tests, browser regression tests, frontend tests/build and security jobs remain separate required evidence. No skips are accepted in the dedicated unified browser test. Ordinary regression browser runs explicitly skip that dedicated test unless its harness case is configured. Required local gates A–G must be assessed from executed evidence; H records actual external client blockers, I requires separate real inference evidence and J remains pending institutional authorization.
