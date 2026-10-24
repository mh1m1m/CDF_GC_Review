# Test evidence register

All local checks use fictional fixtures. Baseline source: 837168c292161e7744e99258879e8653cfea0545. New checks refer to the takeover branch containing this register; retrieve exact SHA with git rev-parse HEAD.

| Evidence | Status | Scope / limitation |
|---|---|---|
| Baseline GitHub Actions run 40062788386 | PASSED | Three jobs: Python public suite, web build, Chromium browser E2E; inspected via GitHub connector |
| Baseline PR 2/3/4 runs 39989549736 / 40053736011 / 40058896046 | PASSED | Latest returned PR-triggered runs; PR 1 returned no run for its SHA |
| Historical 218 passed / 17 skipped | HISTORICAL_CLAIM | User handoff; not substituted for local results |
| Baseline public-file guard | PASSED | 224 tracked entries; heuristic only |
| Baseline npm run build | PASSED | TypeScript and Vite production build |
| Baseline full local Python suite | FAILED / INTERRUPTED | 2 LibreOffice recalculation timeouts, 129 passed, 11 skipped before interruption; earlier sandbox attempt interrupted at 58 passed / 11 skipped |
| Four baseline defect reproductions | CONFIRMED | Expired/future key accepted, unsigned revision replacement applied, rejected rule compiled, repeat compile IntegrityError; no confidential fixtures |
| Takeover Python suite with LibreOffice unavailable | PASSED_WITH_SKIPS | 228 passed, 17 skipped, 10 subtests passed in 94.60s; 6 skips are LibreOffice, 3 LIVE provider, 8 missing institutional inputs/assets. Optional inline rendering paths not executed |
| Real AI inference | NOT_RUN | No real provider configured; actual verified count for this cycle is 0 |
| Institutional acceptance | BLOCKED_EXTERNAL | No institutional identity, trust provisioning or authorization supplied |

Reproduce Python: python -m pytest tests qa_public -q -p no:cacheprovider -rs. Optional calibration dependencies: requirements-calibration.txt. New negative tests: tests/test_codex_safeguards.py. Browser setup follows .github/workflows/issuance-policy.yml using a random ephemeral token and a synthetic demo database. Do not commit tokens, logs containing secrets or databases.

## Environment controls
Chromium installation was attempted with `apps/web/node_modules/.bin/playwright install chromium` and returned HTTP 403 `Domain forbidden` for cdn.playwright.dev. Local browser E2E is BLOCKED_EXTERNAL; the baseline CI browser success remains historical evidence for the baseline only.

The final local Python run explicitly treats LibreOffice as unavailable because its macro recalculation timed out on the unchanged baseline. Reproduce this restricted check without modifying source:

```sh
python - <<'PYTEST'
from cdf_gco_crms.qa import lo_engine
lo_engine.available = lambda: False
import pytest
raise SystemExit(pytest.main(['tests', 'qa_public', '-q', '-p', 'no:cacheprovider', '-rs']))
PYTEST
```

The actual run used an equivalent temporary pytest plugin. Existing skip markers classify engine-dependent tests as SKIPPED; inline optional rendering branches are not executed. This does not validate independent spreadsheet recalculation or rendering. Normal loopback/process access is needed for FastAPI TestClient; sandboxed attempts stalled and were terminated, not reported as passes.

Final public-file guard: PASSED, 239 tracked entries after staging. Python compilation and staged whitespace checks passed. UI production build passed earlier; no UI source was changed. New CI result is not yet available at commit time; inspect the draft PR checks.

## Follow-up — installed LibreOffice diagnostic and completed CI
PR 6 head f2ff9b6708e6ac438ecfcd71eab737d5e3e07615: Actions run 40064935332 now PASSED in all three jobs, including browser E2E. This replaces the earlier queued status for that exact head. It does not verify LibreOffice, which the workflow does not install.

LibreOffice is already installed: LibreOfficeDev 26.8.0.0.alpha0. Writer text-to-PDF passed; tiny synthetic XLSX and CSV Calc conversions timed out independently of the project workbook/macro. See LIBREOFFICE_DIAGNOSTIC.md for limits and reproduction. No new full-suite pass or spreadsheet reconciliation is claimed by this documentation-only follow-up.

## Stable LibreOffice implementation — 2026-10-24
Base: 5a20f318b183c2558404a7179f62b1482b3e5d17 (PR 6 remains open/draft). Work branch: codex/stable-libreoffice.

- Base registry digest: python:3.12-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 (resolved by successful Docker pull).
- Stable Debian package pin: 4:25.2.3-2+deb13u8; actual /usr/bin/soffice version: LibreOffice 25.2.3.2 520(Build:2).
- Local built image ID: sha256:701893538967e5ac5e559d8623c17d228fbcebbaafc38b49bf2aed5a1c2eabbc. No registry publication. Package/pip provenance is included in smoke.json.
- Smoke: Calc PASSED (uncached SUM=5, formula retained, source unchanged); Writer PASSED (valid one-page PDF, readable English and Arabic); Impress PASSED (valid one-page PDF, readable synthetic marker).
- Required engine run: 13 passed in 37.50s, no skips, including all six required engine checks plus existing e2e setup prerequisites. The initial six-test-only selection found an existing e2e ordering dependency (KeyError: 5); the runner now includes its complete module rather than weakening that test.
- Diagnostic regressions: 9 passed locally; prerelease rejection, timeout descendant cleanup, and JUnit skip/missing enforcement. An initially missed rc version suffix was caught and corrected before validation.
- Initial root container invocation could not read restrictive host file permissions after dropping capabilities. Validation now runs as the workspace UID/GID against an isolated public-source copy; original workspace permissions were not relaxed.
- Full stable-container public suite: 243 passed, 11 skipped, 10 subtests passed in 95.77s. All six required engine checks passed again; no unavailable-LibreOffice override. Skips: three real-provider checks and eight missing institutional inputs/assets. Exact-head CI must be checked independently on the new PR.

The host alpha runtime remains unchanged; these results apply to the stable container. See STABLE_LIBREOFFICE.md for build/run, cloud setup distinction, pinning limits and troubleshooting.

## Executive visual intelligence — local acceptance
Source base: 00c4f5b (PR 7), branch codex/visual-intelligence. Exact final SHA/CI will be linked from the new draft PR.

| Check | Result | Scope and limits |
|---|---|---|
| Stable-container document smoke | PASSED, Calc/Arabic Writer/Impress 3/3 | LibreOffice 25.2.3.2, original inputs unchanged |
| Required document-engine/prerequisite suite | 13 passed, no skips (43.23s) | Actual existing formulas, historical selection, sorting/navigation, PDF renderers |
| Full stable-container public suite | 257 passed, 11 skipped, 10 subtests passed (188.88s) | Includes new draft PDF parsing and independent Calc export formula evaluation. Skips remain 3 real-provider and 8 unavailable institutional inputs/assets; no LibreOffice override |
| Focused intelligence/source/API tests | PASSED | Denominators, snapshot corruption, fake LIVE label, source hash/page verification, access grants, no invented alignment, native draft exports; latest refinement verified separately |
| Frontend build | PASSED | Vite 8.3.5 / TypeScript 5.9.3; warning about optional chunk size and client directives documented, no build failure |
| Vitest | 2 passed | Unknown versus zero and distinct source labels; isolated from Playwright suites |
| Playwright | 5 passed | Existing calibration persistence/materiality/mobile checks and new command-center desktop/iPhone, source drill-down, draft export and metric refresh |
| Accessibility | No violations in automated WCAG A/AA desktop overview scan | Does not certify every WCAG criterion or all assistive-technology behavior; keyboard alternatives/reduced motion/mobile overflow also exercised |
| Visual regression | Desktop/iPhone screenshot baselines checked without updates | Noto Arabic runtime fonts and 2.5% pixel threshold; exact-head CI must validate cross-run rendering |
| Reference reproduction | 141 authority / 81 unit candidates | Source hashes verified; 15 sector groupings; extraction is not approval/current authority; financial thresholds require human reconciliation |
| Security | Scoped Bandit 0 findings; npm audit 0; PyPI audit 0 | Initial 55 advisories in pre-existing Pillow/pypdf pins were resolved by updates to 13.0.0 / 6.21.2; Gitleaks/history-wide scanning deferred explicitly |
| Real inference / institutional acceptance | NOT_RUN / NOT_AUTHORIZED | No model call, independent validated human-label dataset, institutional SSO or official issuance |

Build measurements: chart module approximately 553 kB minified / 187 kB gzip, graph module approximately 318 kB / 102 kB gzip before final formatting. Page components are lazy-loaded; these are build sizes, not field performance/SLA measurements. Graphs are bounded (source graph maximum 65 nodes); large case pagination/virtualization remains a follow-on requirement. Original actual source PDFs remain local; published candidate/asset material was explicitly declared public by the user.

Final refinements: exact FastAPI 0.162.0 / Uvicorn 0.54.0 / HTTPX 0.28.1 pins match the stable container. Focused host intelligence/API/source run: 13 passed, 1 skipped (host alpha PDF/Calc acceptance). The final RTL/logo draft exporters were independently rechecked in the stable image: 2 passed, including PDF parsing and native Excel formula recalculation. Word, Excel and PDF synthetic samples were generated from one identical read model. Chart SVG coordinates are explicitly LTR inside the RTL interface; reviewed desktop/iPhone baselines then passed the five browser tests without updates (1.1m). Public candidate reproduction matched the committed JSON exactly. Final image ID: sha256:6149d2a16dab87d7f7f6405893c73bbede5a5e07cad876160fa793e1959530fe. CI results apply only after independently inspecting the exact new PR head.

## Institutional dual-mode continuation
Base b30dc5f01b5573d707c1ece77b42c1a3e690a0ae (PR #8); that base independently passed workflows 40071144261 and 40071144274. New branch codex/institutional-dual-mode.

| Verification | Local result | Evidence/limit |
|---|---|---|
| Refreshed Drive original checks | 5/5 matched | Private revalidation register; hashes/content not included in public artifacts |
| Private source ingestion | 141 DoA / 81 units / 15 sectors | Existing geometry/layout parsers; approval/currency unverified |
| Stable smoke and mandatory engine checks | 3/3 smoke, 13 passed without skips | LibreOffice 25.2.3.2, network disabled |
| Full stable-container source snapshot | 267 passed, 11 skipped, 10 subtests passed (117.21s) | Three provider and eight unavailable institutional input/asset skips; two later currency/version-history cases are covered in the focused run and final CI |
| Final focused API/intelligence/mode tests | 25 passed, 1 skipped | Host alpha engine acceptance skipped; private scopes, fake configuration, source versions, real orchestrator hook and native export boundaries |
| Final native document acceptance | 3 passed | Actual stable PDF parse/Calc reconciliation, native Word comments, structured tables and original x14 element |
| TypeScript/Vite and Vitest | PASSED / 2 passed | Existing toolchain pins retained |
| Browser and visual regression | 8 passed without baseline updates (49.9s) | Actual desktop/iPhone, gallery, historical filters/tree, calibration persistence, exports and WCAG automated scans |
| Dedicated visual gallery | 12 required actual captures present | Running app screenshots plus independently rendered Word/Calc previews; not institutional design acceptance |
| Public-mode container isolation | PASSED | Nonroot/no network/no private mounts; actual UI/API/reference/export exercise |
| Frontend configuration boundary | PASSED | Backend-only sentinel absent from bundle; private client-secret prefix rejected |
| Scoped security scans | Bandit 0; npm/PyPI 0 known advisories | Gitleaks/history-wide/manual penetration testing not claimed |
| Institutional activation, current approval, real inference | PENDING_AUTHORIZATION / NOT_VERIFIED / NOT_RUN | No production HTTP activation, organizational SSO/UAT, verified human-label dataset or actual provider call |

Actual x14 sparkline bytes survive in the delivered original XLSX; openpyxl/LibreOffice may drop or not render that extension when resaving. Microsoft Excel desktop verification remains NOT_RUN. Build/bundle measurements and graph-scale limits remain engineering observations, not field performance SLAs. Final SHA/CI evidence will be linked from the follow-up draft PR and final handoff.

Actual-source interoperability follow-up: the initial page-text check accepted 7/10 sampled real candidates and safely rejected three Arabic table rows because of PDF reading order. The adapter now verifies exact number/title/page and roles through the existing table-geometry parser; all 10 sampled DoA/mandate occurrences passed while remaining unverified authority. Two synthetic negative/geometry regressions passed. Initial final-head CI passed Python/web/browser/security and stable LibreOffice but the dedicated visual job failed because ripgrep was absent on that runner. Its configuration-leakage gate now uses a fail-closed Python checker with explicit missing/leaking/unexecuted-check tests, so a missing shell utility cannot silently pass the scan.

## Unified execution milestone — 2026-10-24

Focused verification: 13 real service/protocol/process-supervision cases passed; five additional HTTP/OpenAI receipt-contract cases passed. Initial full CLI/MCP/rendered-React consistency passed without exports. TypeScript/Vite production build, two Vitest cases, scoped Bandit (zero findings) and final locked Python advisory scan (zero known advisories) passed. The installed vulnerable MCP 1.29.0 was replaced with 1.30.0 before final acceptance.

Stable document smoke and 13 required engine checks passed. A disk-exhaustion run produced 252 passes / 11 skips / 37 temporary-directory setup errors; it is retained as failed environmental evidence and not counted as acceptance. The full sequential stable workflow and exact-head CI produce the authoritative later counts and artifact hashes. Required evidence: `execution-summary.json`, `interface-matrix.json`, protocol discovery/invocations, command exit results, browser JUnit/screenshots, structural/native export validation and original-source-preserving Calc reconciliation. The draft PR links final-head workflows/artifacts and distinguishes external client/model/institutional blockers.

Final focused service/protocol/HTTP/SDK/agent/MAT regression: **44 passed**. Failed job results now expose scoped persisted attempt receipts and named failure phases; provider SDK error bodies are sanitized before traces. The isolated browser integration passed after copying dependencies inside Vite's allowed application root. Word draft validation now checks the actual explicit `INTERNAL DRAFT` / `NOT AUTHORIZED FOR ISSUE` text rather than an incorrect underscore spelling. The final complete harness and head CI remain the definitive export/full-suite evidence.

Complete local stable verification: full CLI/MCP/React workflow **PASS**; all three native exports validated; all eight Excel fractions reconciled by stable Calc on a copy; eight-page PDF parsed/rendered; seven actual browser/document captures; one dedicated browser test passed without skips. Stable smoke passed, 13 required engine checks passed, and full suite **295 passed / 11 skipped / 10 subtests passed**. Skips are three genuine-provider tests and eight missing institutional inputs/assets. Exact-head initial stable CI independently matched those counts. Follow-up process-cleanup/reliability run: **22 passed** after correcting the observed /proc race. The official native Codex probe was attempted once, timed out without a receipt and remains BLOCKED_EXTERNAL / OUTCOME_UNKNOWN; zero verified API inference is claimed.

Additional independent MCP asynchronous proof: fresh export accepted over HTTP, QUEUED/RUNNING/COMPLETED observed, attempts=1, generated XLSX downloaded by CLI and MCP with equal bytes, and canonical case state reconciled after publication. Recorded as `mcp-job-lifecycle.json` in the final acceptance artifact; this supplements completed-job replay coverage.

Concurrent-worker regression: original deferred WAL reader failed a deterministic two-connection read/modify/write scenario with `database is locked`. Immediate root transactions fix the snapshot-upgrade race while nested publication rollback remains tested. **54 focused cases passed**, including the new concurrent-update check and existing authorization/agent/cleanup controls. Final-head CI must include the actual fresh MCP job lifecycle, not completed-job replay alone.
