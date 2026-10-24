# Open issues

| ID | Priority | State | Next action |
|---|---|---|---|
| AUD-01 | P1 | FIX_IMPLEMENTED | Exact signed replacement digest and challenge identity; review negative tests |
| AUD-02 | P1 | FIX_IMPLEMENTED | Attestor key validity enforced; review expired/future/malformed regressions |
| AUD-03 | P2 | FIX_IMPLEMENTED | Latest rule rejection/defer invalidates prior approval; version-specific workflow remains M1 |
| AUD-04 | P2 | FIX_IMPLEMENTED | Unchanged compilation returns stored immutable snapshot |
| ENV-01 | P1 validation | RESOLVED_IN_STABLE_CONTAINER | Stable LibreOffice 25.2.3.2 passes Calc/Writer/Impress smoke and all six engine checks; full suite 243 passed / 11 skipped. Host alpha remains unchanged. See STABLE_LIBREOFFICE.md and TEST_EVIDENCE_REGISTER.md; verify independent CI on the PR head |
| CAL-01 | P2 | OPEN | Model version-specific rule amendments and explicit changed wording; APPROVE_WITH_CHANGES remains ineligible for compilation |
| CAL-02 | P2 | OPEN | Compiler retains historical submitted observation evidence; define supersession and invalidate obsolete rule evidence |
| EXT-01 | P0 release prerequisite | BLOCKED_EXTERNAL | Institutional identity, reviewer provisioning, signing trust and private data approval |
| EXT-02 | P0 release prerequisite | BLOCKED_EXTERNAL | Authorized genuine provider execution and independent labelled holdout |
| PR-02 | P2 | OPEN | PR 2 conflicts and is included in PR 3 history; owner to reconcile superseded draft without automatic merge |

All source fixes await independent review. No institutional acceptance inferred.
