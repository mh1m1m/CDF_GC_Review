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
