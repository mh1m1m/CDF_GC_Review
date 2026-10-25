# Forensic audit — remediation status (branches `development/v7.12-production-engineering` → `feature/v712-live-multi-agent-runtime`)

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
| R-01 / AI-001 no live AI provider, no isolated agents | CRITICAL | **PARTIAL** | `cdf_gco_crms/agents/`: Anthropic SDK adapter (LIVE, credentials from the environment only), mock and cached adapters, isolated runner (unique Execution_ID / Context_ID, fresh conversation per invocation, schema validation, sanitised trace), six roles over purpose-limited contexts, orchestrator (Article 06), data-handling guard. **No live inference has been executed in this environment** (no credential; the development session is not used as an inference service): Actual_Live_Inference_Count = 0 | `tests/test_agents.py` (14), `tests/test_agents_live.py` (3, SKIPPED without provider) |
| R-04 / AI-031 adjudicated advocate revisions never applied to the register | HIGH | **REMEDIATED** | `cdf_gco_crms/release/dispositions.py::apply_dispositions`: only a verified, in-date, state-bound human decision applies the recorded revision; append-only ledger with provenance; conflict detection; rollback; new fingerprint → new review | `tests/test_release_lifecycle.py`, `tests/test_e2e_agents.py` |
| R-05 Article 20 independent reviewer absent | HIGH | **PARTIAL** | `agents/roles.py::run_final_review`: fresh-context LIVE role (not run here) with a rule-based fallback that is explicitly labelled as not the Article 20 review; the gate refuses an issue without a READY final review | `tests/test_release_lifecycle.py::test_negative_9_missing_final_review` |
| R-08 human-decision records: no expiry/revocation; caller-supplied trust store | MEDIUM | **REMEDIATED** | `cdf_gco_crms/release/trust.py`: institutional trust store (key status, validity window, roles, synthetic flag, revocation), decision validity period, observation and review-state binding signed into the decision; re-validated at issue time | `tests/test_release_lifecycle.py` (negative tests 4–7, 10) |
| Six-cycle debate: semantic duplicate detection, substantive reason per cycle | — | **REMEDIATED** | `agents/debate.py`: productive-cycle rules (exact/n-gram/Jaccard repeats never consume a cycle; new evidence or stance change continues; seventh cycle refused by the chain; unresolved at the bound → escalated) | `tests/test_agents.py::test_debate_productivity_rules` |
| Provider failure must never approve | — | **REMEDIATED** | a failed role escalates its objection and blocks the gate record (`PROVIDER_FAILURE_IN_REVIEW`) | `tests/test_release_lifecycle.py::test_negative_8_failed_ai_provider` |
| Blind evaluation holdout (Article 11 D) | — | **PARTIAL** | sealed public holdout (24 cases, 8 families) and scorer; DETERMINISTIC baseline reported as a baseline only; the LIVE blind score is not produced without a provider | `tests/test_blind_evaluation.py`, `python main.py evaluate-holdout` |

Re-running `AI_AGENT_FORENSIC_AUDIT/runtime_callgraph.py` on this branch will show `02_build-excel` and
`03_build-word` returning rc 3 after a BLOCKED `04_review`; the recorded traces in the reports predate the gate.

## PR #3 independent review (ChatGPT, 2026-10-24) — remediation

| Review finding | Priority | Status | What changed | Proof |
|---|---|---|---|---|
| Gate does not require the final review to be LIVE | P0 | **REMEDIATED** | institutional issue requires a LIVE final review with a verifiable execution receipt in the trace (mode, status, provider, invocation id shape, response hash) bound to the review-state fingerprint; deterministic/mock READY, forged LIVE labels, missing receipts, outdated fingerprints and failed/refused inference are refused | `tests/test_release_attestation.py::test_d1_*` (6 tests) |
| Source-document hash check conditional on the caller | P0 | **REMEDIATED** | the hash is mandatory for an institutional issue (`SOURCE_DOCUMENT_HASH_REQUIRED_FOR_INSTITUTIONAL_ISSUE`); a record without a hash cannot be issued; CLI `--docx` on every issuing command | `test_d2_*` (2 tests) |
| Independence classified from mode labels | P1 | **REMEDIATED** | `attestation.verify_live_roles`: receipts per role, unique Execution_IDs and Context_IDs, no substitution, evidence ids checked; `ISOLATED_LIVE_CONTEXTS` only when verified, else `LIVE_CLAIMED_NOT_VERIFIED`; the gate reads `independence.verified` | `test_d3_*` (2 tests) |
| Local gate record not authenticated | P1 | **REMEDIATED** | signed release attestation (Ed25519, trust-store role `RELEASE_ATTESTOR`) over fingerprint, document hash, challenge-record hash, role proofs, final-review receipt, decision ids, validity interval, purpose; tampered, expired, replayed, revoked, synthetic-key, wrong-purpose or unsigned records are refused | `test_d4_*` (2 tests), `test_attestation_key_file_round_trip` |
| Live inference unverified | P0 | **OPEN** | `tools/live_provider_trial.py` prepared (configuration → connectivity → evaluation; synthetic only; credentials never read); blocked at configuration in this environment: `CDF_AI_PROVIDER` unset / no credential | trial report `build/evidence/live-trial-check/live-provider-trial.json` (local) |

## Live-inference provenance assurance (ChatGPT directive after the PR #3 review, P0)

| Finding | Status | What changed | Proof |
|---|---|---|---|
| A simulated adapter could be counted as live inference (receipt shape and self-reported provider identity trusted) | **REMEDIATED** | `agents/provenance.py`: execution source derived from the adapter object (exact registered class, no injected client); `PROVIDER_API` only with a provider-originated request id; `actual_live_inference_count` counts `PROVIDER_API` + OK; simulated / cached / mock counted apart; hash-chained trace with head in the gate record and attestation; receipts bound to run, fingerprint and role-instruction hash; gate and independence classifier read the source, not the mode | `tests/test_live_provenance.py` (14, incl. the regression that `SimulatedLiveAdapter` cannot increase the live count and the ten negative cases); `tests/test_release_attestation.py` (16) |
| Positive institutional path in tests | **EXPLICIT** | exercised only through a pytest monkeypatch of the trusted-adapter registry (`TrustedTestAdapter`); production registers the Anthropic adapter alone | `tests/test_release_attestation.py::trusted` |

## MAT professional DNA × strategic advisor (directive, branch `feature/v712-mat-professional-dna-agent`)

| Item | Status | What exists | Proof |
|---|---|---|---|
| Source forensics (Phase 1) | **DONE (private)** | both Word files inspected (comments, dates, paraIds, authors, body text); evidence-based matching; 39-row register; 0 documented withdrawals; authorship user-attested under a shared account | `tools/mat_dna/ooxml_forensics.py`; `tests/test_mat_forensics.py`; private register |
| DNA extraction (Phase 2) | **DONE (private, PROVISIONAL)** | 64-question questionnaire, distributions (91.7 % → 62.5 % recommendation family; 0 → 8.3 % direct questions; 2 conversions), writing DNA, 12 selection rules, 15 withdrawal grounds (all hypotheses or NOT_ESTABLISHED), style guide, evidence register, validation report, profile | private deliverables 1–10 |
| Human validation boundary (Phase 3) | **OPEN** | every rule marked single-case, `mat_explicitly_approved=false`; calibration package listed in the validation report | reviewer calibration not yet performed |
| Agent engineering (Phase 4) | **DONE** | contracts, loader, three stages, guards, fallback, traces, profile binding | `tests/test_mat_advisor.py` |
| Protocol integration (Phase 5) | **DONE** | advisory stages at the three points; firewall; cycle control; Article 15 state; CLI | pipeline tests |
| Validation (Phase 6) | **PARTIAL** | synthetic, adversarial, contradiction, withdrawal and e2e tests pass; fidelity scores and baselines need a second case and a live provider | NOT_RUN items named in `docs/MAT-STRATEGIC-ADVISOR.md` §7 |
| Live inference | **NOT_EXECUTED** | no credential; `actual_live_inference_count = 0` | — |

