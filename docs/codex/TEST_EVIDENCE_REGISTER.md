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
