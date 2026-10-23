# Forensic audit — remediation status after branch `development/v7.12-production-engineering`

The nine audit reports in this folder describe the state they audited and are **not** edited. This file records what
changed afterwards, finding by finding, with the test that proves each change. Statuses are REMEDIATED (code and
covering test on this branch), PARTIAL, or OPEN. Nothing here changes the audit verdict
(DETERMINISTIC_AGENT_SIMULATION_ONLY / TECHNICAL_REMEDIATION_REQUIRED): the verdict is re-assessed only by re-running
the harness.

| Finding | Severity | Status | What changed | Proof |
|---|---|---|---|---|
| R-03 issuing commands never call the challenge; blockers do not stop a build (AI-002, AI-031 part) | CRITICAL | **REMEDIATED** | `cdf_gco_crms/release/authorization_gate.py`: content fingerprint; `review`/`challenge`/`adjudicate` write a gate record keyed by it; `rebuild`, `finalize-titles`, `build-excel`, `build-word` refuse (rc 3) unless a CLEAR, unaltered record exists for exactly that content; `round1`/`append` always write marked WORKING-COPY files; `--working-copy` writes a marked copy instead of refusing | `tests/test_release_gate.py` (11 tests): BLOCKED review → build-excel/build-word refused and nothing written; tampered gate or challenge record refused; CLEAR review → unmarked issue; same file name with unreviewed content refused |
| Finding B (review) public repository not independently testable | HIGH | **REMEDIATED** | `cdf_gco_crms/references/synthetic_index.py` (fictional organisation and matrix, every status `SYNTHETIC_NOT_APPROVED`); `tests/conftest.py::reference_index` fixture; `test_e2e` uses it; brand page test skips without the render; `--synthetic-reference` on the CLI; a synthetic-reference review never authorises a non-demo issue | `tests/test_reference_synthetic.py` (8 tests); full suite 208 passed / 1 skipped with `CDF_TEST_SYNTHETIC_REFERENCE=1` |
| R-11 round-1 JSON `title` dropped by `cmd_round1` | LOW | **REMEDIATED** | `_new()` passes `title` through to `NewObservation` | `main.py` |
| Title fallback tag "ملخص آلي غير معتمد" (review finding a) | — | **REMEDIATED** | dashboard and action list show the neutral "الملاحظة #NN" (reader number) where no approved title exists; no engine extract of the text is shown as a title | `tests/test_titles.py` |
| Lineage audit: six FAIL checks on v7.11 Word files unexplained (review finding b) | — | **REMEDIATED** | each is classified `BASELINE_INPUT_LIMITATION` with the covering v7.12 tests named; summary separates `fail_baseline_input_limitation` (6) from `fail_engine` (0); statuses stay FAIL | `tools/lineage_audit.py`; `deliverables/CDF-GCO-CRMS-v7.12-LINEAGE-VALIDATION.json` (local) |
| Patch statuses 035 / 039 / 040 / 044 disputed (review finding) | — | **RECONCILED** | 035 → NOT_VERIFIED (LibreOffice render only); 039, 040 → NOT_VERIFIED (deterministic rules, no live agents); 044 → PASS only through the release gate and its tests | `PATCH-STATUS.md` (49 PASS / 8 NOT_VERIFIED / 3 BLOCKED_EXTERNAL) |
| Release classification merged into one claim (review finding c) | — | **REMEDIATED** | three dimensions reported separately: deterministic engineering COMPLETE; multi-agent AI NOT_VERIFIED; institutional approval PENDING | `PATCH-STATUS.json::classification` |
| R-01 / AI-001 no live AI provider, no isolated agents | CRITICAL | **OPEN** | needs a provider decision and authorisation; the product still has no inference adapter | — |
| R-04 / AI-031 adjudicated advocate revisions never applied to the register | HIGH | **OPEN** | planned: apply REVISE outcomes carried by a verified HumanDecision to the observation register | — |
| R-05 Article 20 independent reviewer absent | HIGH | **OPEN** | — | — |
| R-08 human-decision records: no expiry/revocation; caller-supplied trust store | MEDIUM | **OPEN** | — | — |

Re-running `AI_AGENT_FORENSIC_AUDIT/runtime_callgraph.py` on this branch will show `02_build-excel` and
`03_build-word` returning rc 3 after a BLOCKED `04_review`; the recorded traces in the reports predate the gate.
