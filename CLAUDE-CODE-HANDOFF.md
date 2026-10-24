# CDF–GCO–CRMS v7.12 — CLAUDE CODE ENGINEERING HANDOFF

## A. Execution identity

- Execution_Date: 2026-10-24
- Repository: https://github.com/mh1m1m/CDF_GC_Review (PUBLIC, unchanged)
- Base_Branch: development/v7.12-production-engineering
- Working_Branch: feature/v712-live-multi-agent-runtime
- Base_Commit_SHA: 492915ad9d6d2a457b2b60bd30d051dc6a07b546 (development) + e298083cf48d38886ca081005921827f5e34abf2 (PR #2, merged with history at 6739ee21d7c6dbdd4eee7af629821093b1816796)
- Final_Commit_SHA: 1c364e7ac89455468a921c7b0f9f96cb07afdb2b (code, tests, docs, register); this handoff file is committed on top of it
- Pull_Request_URL: https://github.com/mh1m1m/CDF_GC_Review/pull/3 (draft, feature → development; PR #1 and PR #2 untouched; nothing merged into main)

## B. Engineering changes

| Component | Previous state | Implemented change | Current state | Evidence |
|---|---|---|---|---|
| Provider abstraction | none (no SDK, no HTTP in the product) | `agents/providers/`: Anthropic adapter (official SDK, credentials from environment only, JSON-schema output, typed error mapping, bounded rate-limit retries), mock adapter, cached replay; `provider_from_env` never defaults to a mock | implemented, exercised in failure and mock paths only | tests/test_agents.py (7 layer-A tests) |
| Isolated agent runner | roles ran as rules in one process | `agents/runner.py`: fresh request per invocation, unique Execution_ID, Context_ID from prompt material, schema validation, failure/refusal/schema-invalid as non-results, sanitised JSONL trace with mode/status counts | implemented | test_runner_isolates_each_invocation_and_separates_modes; trace files |
| Context isolation and data handling | n/a | `agents/context_builder.py` (purpose-limited payloads per role, adjudicator without a preferred party, final reviewer in a fresh context), `agents/security.py` (institutional content never sent LIVE without `INSTITUTIONAL_AUTHORIZED:<ref>`, sealed-label guard, credential redaction) | implemented | test_security_data_handling_and_context_isolation |
| Six roles | black/red/adjudicator rules only | `agents/roles.py`: Agents A–F over the runner; challenge roles fall back to the rule engine; editorial and final review have labelled rule-based fallbacks; guards re-apply the rule adjudicator's invariants to every live disposition; hallucinated evidence ids dropped and counted | implemented; LIVE path not executed | test_roles_convert_scripted_output_into_engine_objects |
| Debate engine | chain-level exact-duplicate check | `agents/debate.py`: productive-cycle rules (exact/n-gram/Jaccard repeats never consume a cycle; new evidence or stance change continues; seventh refused; unresolved → escalated) | implemented | test_debate_productivity_rules |
| Orchestrator | review command called run_challenge; no final review; no editorial | `agents/orchestrator.py`: Article 06 pipeline → hash-chained ChallengeRecord + gate record; consolidation of duplicate objections; editorial candidates (proposed only); human decisions inside the pipeline; independent final review; provider failure escalates and blocks | implemented | 3 orchestrator tests; test_e2e_agents |
| Central release gate | content fingerprint + CLEAR record (previous commit) | + provider-failure block, READY final review required, source-document hash, re-validation of recorded human decisions against the trust store at issue time; INTERNAL_DRAFT__ naming unified with PR #2 | implemented | tests/test_release_lifecycle.py (ten negative tests), qa_public |
| Authorization lifecycle | caller-supplied raw key dict, no expiry/revocation | `release/trust.py` (status, revocation, validity windows, roles, synthetic flag; legacy format accepted), HumanDecision signed with review-state binding and expiry | implemented | test_trust_store_formats_and_lifecycle_checks; negative tests 4–7, 10 |
| Disposition application | adjudicated revisions never reached the register | `release/dispositions.py::apply_dispositions` (verified in-date state-bound decision only; copy of state; ledger with original text and provenance; conflict detection; rollback; new fingerprint) + CLI `apply-dispositions` | implemented | test_apply_dispositions_requires_authorised_decision_and_keeps_history |
| CLI | review/challenge/adjudicate on rules; PR #2 disabled every issue | review/challenge/adjudicate through the orchestrator; `agent-review`, `apply-dispositions`, `evaluate-holdout`; `--trust-store`, `--internal-draft` alias; missing/unsafe inputs fail closed with `no_output_generated` | implemented | CLI tests in test_release_gate, test_release_lifecycle, qa_public |
| Public holdout | 34 sealed cases (gitignored, institutional excerpts) | `agents/evaluator.py` + `tests/fixtures/holdout/` (24 fictional cases, 8 families, sealed answers, SHA-256) scored per mode | implemented; deterministic baseline only | tests/test_blind_evaluation.py |
| CI | PR #2 job (6 tests) | `.github/workflows/issuance-policy.yml`: pinned clean install, compile, whole public-safe suite, PR #2 unittest entry point, JUnit artefact | committed; not observed running (no Actions access from this session) | workflow file |
| Docs / register | — | README, REPOSITORY-STRUCTURE, CHECKPOINT, REMEDIATION-STATUS, ENGINEERING-EVIDENCE-REGISTER, PATCH-STATUS regenerated (49 PASS / 8 NOT_VERIFIED / 3 BLOCKED_EXTERNAL) | updated | files in the commit |

## C. AI-agent operational verification

| Agent | Live model call | Separate context | Production integration | Tests | Maturity |
|---|---|---|---|---|---|
| A GCO Drafting | NOT EXECUTED (no credential) | yes (runner) | `agent-review --draft` (proposals only) | NOT_RUN path tested | LIVE_AGENTS_NOT_INTEGRATED |
| B Black Team | NOT EXECUTED | yes | orchestrator → ChallengeRecord | MOCK + DETERMINISTIC | PARTIAL_LIVE_AI_IMPLEMENTATION (code path), DETERMINISTIC in use |
| C Red Advocate | NOT EXECUTED | yes | orchestrator, guards | MOCK + DETERMINISTIC | same |
| D Independent Adjudicator | NOT EXECUTED | yes | orchestrator, guards, chain decide | MOCK + DETERMINISTIC | same |
| E GCO Editorial | NOT EXECUTED | yes | editorial candidates (never applied) | MOCK + rule fallback | same |
| F Independent Final Reviewer | NOT EXECUTED | yes (fresh agent id and context) | gate requires READY | MOCK + labelled rule fallback | same; rule fallback is not the Article 20 review |
| G Evidence Verification | deterministic (unchanged) | n/a | EvidenceRegistry, trust store | existing + new | COMPLETE (deterministic) |

Independence is recorded per run: ISOLATED_LIVE_CONTEXTS only when every challenge role ran LIVE; otherwise SINGLE_PROCESS_RULE_BASED or MOCK_SCRIPTED_CONTEXTS. No run on this branch recorded ISOLATED_LIVE_CONTEXTS.

## D. Provider verification

- Provider: anthropic adapter implemented (official SDK 2.3.0, pinned); configured only through `CDF_AI_PROVIDER` and a credential the SDK resolves from the environment
- Model: `claude-opus-5-5` default (`CDF_AI_MODEL`)
- Actual_Live_Inference_Count: **0**
- Mock_Inference_Count: scripted MOCK invocations in tests only (reported per run in trace summaries; never pooled with live)
- Provider_Trace_Location: `build/adversarial/traces/agent-trace.jsonl` (per run, sanitised; not committed), `build/evidence/live/*.jsonl` when live tests run
- Data_Handling_Authorization: `SYNTHETIC_ONLY` (default); institutional content leaves the process only with `CDF_AI_DATA_AUTHORIZATION=INSTITUTIONAL_AUTHORIZED:<reference>`, which no one has set. The Claude Code development session was not used as an application inference service (investigated; it is a development tool, not a supported provider).

## E. Test results (branch head 1c364e7, `python -m pytest tests qa_public -q`)

- Unit_Tests_Passed: 14 (tests/test_agents.py layers A+B) + 3 (tests/test_blind_evaluation.py) + 13 (tests/test_release_lifecycle.py)
- Integration_Tests_Passed: included above (orchestrator, roles over the engine, CLI); 19 gate/PR #2 tests (tests/test_release_gate.py 11 + qa_public 8)
- Live_Agent_Tests_Passed: 0 — 3 SKIPPED (no LIVE provider configured); never counted as passed
- Blind_Evaluation_Score: DETERMINISTIC baseline on the 24-case public holdout: objection detection 1.00, false-objection rate 0.00, adjudicator accuracy 1.00 (21 adjudicated) — classification `DETERMINISTIC_BASELINE_NOT_A_PASS` (templates derive from the engine's own categories); LIVE score: not produced. Forensic baseline carried for comparison: 32 sealed cases, 65.6 % / 76.5 % / 9.1 %.
- End_to_End_Tests_Passed: 1 (tests/test_e2e_agents.py, MOCK provider) + 8 (tests/test_e2e.py deterministic)
- Security_Tests_Passed: tests/test_security.py and the security assertions in test_agents.py — all passed
- Existing_Regression_Tests_Passed: whole suite 246 passed, 4 skipped, 0 failed (with institutional sources on disk)
- Fresh public clone (`git archive` of 1c364e7, no institutional files, `pytest tests qa_public`): 155 passed, 11 skipped (7 institutional-source tests, 1 brand render, 3 live-provider), 0 failed
- Failures: 0
- Skipped: 4 (3 live-provider tests; 1 refusal-path test that needs a public clone)
- Not_Verified: live inference, live blind score, CI run observation, Article 20 live review

## F. Release gate

- Challenge_Required_Before_Issue: YES (no record for the exact content → refused)
- BLOCKED_Prevents_Issuance: YES (blockers, provider failures, NOT_READY final review all refuse)
- State_Hash_Binding: YES (content fingerprint; title decisions carry their own proof; the source-document hash is also checked when supplied)
- Human_Signature_Verification: YES (Ed25519; observation and review-state binding inside the signed payload)
- Revocation_Check: YES (trust store status re-checked at issue time; `--trust-store` mandatory when the record relies on decisions)
- Expiry_Check: YES (decision validity period, key validity window)
- Final_Reviewer_Required: YES (READY required; rule-based fallback is labelled and is not the Article 20 review)
- Official_Word_Excel_Issuance: only through `rebuild` / `finalize-titles` / `build-excel` / `build-word` after the gate passes; everything else is `INTERNAL_DRAFT__` with the package marker; a synthetic-key or synthetic-reference review never issues a non-demo document

## G. Repository verification

- Public_Safety_Scan: change set scanned for e-mail addresses, private keys, API-key patterns and the institutional source hashes — none (one test string exercises the redactor); no institutional document, case, policy or key added
- GitHub_Push_Verified: yes
- Remote_Commit_SHA: 1c364e7ac89455468a921c7b0f9f96cb07afdb2b (origin/feature/v712-live-multi-agent-runtime)
- Changed_Files: 41 in 1c364e7 (26 added, 15 modified) + 7 in the merge commit 6739ee2; remote tree 178 blobs = local tracked count
- Pull_Request_Status: #3 draft, open, feature → development; #1 and #2 unchanged (draft, open)
- Restricted_Files_Published: none. Visibility unchanged (public). No licence assigned.

## H. Outstanding issues

| Priority | Issue | Root cause | Required action | Dependency |
|---|---|---|---|---|
| P0 | No live inference executed; all live layers skipped | no provider credential in CI or the authoring environment; the development session must not serve as the application provider | operator sets `CDF_AI_PROVIDER=anthropic` and a credential (and `INSTITUTIONAL_AUTHORIZED:<ref>` only for authorised institutional content), then runs `pytest tests/test_agents_live.py` and `python main.py evaluate-holdout --json build/holdout-live.json`; records go to build/evidence/live | institutional decision on provider and data handling |
| P0 | Blind LIVE score (≥ 80 % adjudicator) not produced | same | same; the holdout answers are sealed and never shown to agents | same |
| P1 | Article 20 final review runs only as a labelled rule fallback | LIVE role not executed | run live; keep the gate's READY requirement | P0 |
| P1 | Drafting agent has no deterministic fallback (NOT_RUN without provider) | by design (no rule-based drafting) | live run; proposals stay human-reviewed | P0 |
| P1 | CI run not observed | no Actions access from this session | confirm the `Public-safe test suite` workflow result on PR #3 | GitHub |
| P2 | Holdout templates derive from the engine's own categories | public-safe generation | ChatGPT to supply or approve an independently authored synthetic set (sealed by a third party) for the live evaluation | reviewer |
| P2 | Prompt and threshold tuning (duplicate thresholds 0.8 / 0.85, validity 30 days) are engineering defaults | no institutional parameters supplied | confirm or override via configuration | policy |

## I. Final verdict

- Engineering_Status: ENGINEERING_COMPLETE_WITH_UNVERIFIED_ITEMS
- Multi_Agent_Status: LIVE_AGENTS_NOT_INTEGRATED (runtime implemented and tested in MOCK/DETERMINISTIC modes; no verified live invocation)
- Institutional_Authorization: NOT_AUTHORIZED (institutional evidence pending; no tool grants approval)
- Production_Readiness: not ready for institutional issue; technically ready for a controlled pilot of the deterministic path with human decisions, and for a live-provider trial on synthetic data once credentials are configured

## J. Message to ChatGPT

CHATGPT REVIEW REQUEST

"Review the implementation committed to the GitHub repository and the Pull Request identified above.

Independently examine the modified source files and runtime integration.

Verify whether the claimed AI agents actually execute independent model calls.

Assess whether the central issuance gate prevents bypasses.

Review the reported test evidence and identify unsupported completion claims.

Determine the next engineering actions, prioritizing critical defects.

Do not assume that Claude Code's reported completion is sufficient evidence.

Use the GitHub repository as the authoritative source of truth."
