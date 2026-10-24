# CHECKPOINT — CDF–GCO–CRMS v7.12 production execution

Last update 2026-10-23T17:07:45+00:00 (UTC).

## State

- Patch register: {"PASS": 49, "NOT_VERIFIED": 8, "BLOCKED_EXTERNAL": 3} → PATCH-STATUS.json / PATCH-STATUS.md (035, 039, 040 reconciled to NOT_VERIFIED; 044 PASS through the release gate)
- Engineering status: ENGINEERING_COMPLETE; classification by dimension: deterministic engineering COMPLETE · multi-agent AI NOT_VERIFIED · institutional approval PENDING
- Package: /home/user/cdf-gco-crms/v7.12/dist/CDF-GCO-CRMS-v7.12-PRODUCTION-RC-COMPLETE.zip (261 members, 24785106 bytes, sha256 7cef5fd0b4933e7550adfe8761a7ba489df8039d2b84aba8869d81fe0c031af6, corrupt member: None)
- Folders: 01_PROTOCOL, 02_ENGINE, 03_EXECUTIVE_EXCEL, 04_ADVERSARIAL_ASSURANCE, 05_BRANDING, 06_MIGRATION, 07_QUALITY_ASSURANCE, 08_CROSSWALK, 09_EVIDENCE, 10_RELEASE

## Branch development/v7.12-production-engineering (after the forensic review)

- Release authorisation gate (`cdf_gco_crms/release/authorization_gate.py`): issuing commands refuse without a CLEAR review record for exactly this content; round1/append write marked WORKING-COPY files (tests/test_release_gate.py).
- Public SYNTHETIC reference fixture (`cdf_gco_crms/references/synthetic_index.py`): the full suite runs on a public clone (tests/test_reference_synthetic.py; `CDF_TEST_SYNTHETIC_REFERENCE=1`).
- Title fallback is the neutral "الملاحظة #NN"; lineage FAIL checks on v7.11 inputs classified BASELINE_INPUT_LIMITATION (6) with 0 engine failures.
- Test suite: 208 passed, 1 skipped (institutional sources on disk) and 208 passed, 1 skipped (fixture forced).
- The production RC ZIP in dist/ (sha256 7cef5fd0…) predates this branch and is not rebuilt here; rebuild with `python tools/build_rc.py` when the next RC is cut.
- Open from the forensic backlog: live AI provider adapter and isolated agents (needs a provider decision), applying adjudicated revisions to the register, Article 20 reviewer (AI_AGENT_FORENSIC_AUDIT/reports/REMEDIATION-STATUS.md).

## Branch feature/v712-live-multi-agent-runtime (ChatGPT-directed execution, Article 19 checkpoint)

- Base: development/v7.12-production-engineering @ 492915a; PR #2 (fix/v712-fail-closed-cli @ e298083) merged with history (6739ee2).
- Live multi-agent runtime: cdf_gco_crms/agents (providers, runner, roles, debate, orchestrator, evaluator, security, tracing);
  release lifecycle: release/trust.py, release/dispositions.py; gate extended (final review, provider failure, decision re-validation).
- CLI: review/challenge/adjudicate run through the orchestrator; agent-review, apply-dispositions, evaluate-holdout added;
  INTERNAL_DRAFT__ naming unified with PR #2; --internal-draft ≡ --working-copy; --trust-store on issuing commands.
- Tests: TEST 35–39 added; live tests skip without a provider. No live inference executed in this environment.
- PR #3 review remediation: live final-review receipts, mandatory source hash, receipt-based independence, signed release attestation (release/attestation.py; tests/test_release_attestation.py, 15 tests); tools/live_provider_trial.py.
- Live-inference provenance: execution source derived from the adapter object, provider request ids, hash-chained traces, receipt binding (agents/provenance.py; tests/test_live_provenance.py, 14 tests). Live inference count still 0.
- Resume: `git fetch origin feature/v712-live-multi-agent-runtime`; `python -m pytest tests qa_public -q`; to run live layers set
  CDF_AI_PROVIDER=anthropic and a credential (operator-held), then `python -m pytest tests/test_agents_live.py -q` and
  `python main.py evaluate-holdout --json build/holdout-live.json`.

## Patches not PASS (why)

- V712-020 NOT_VERIFIED: no Microsoft Excel in this environment
- V712-023 NOT_VERIFIED: cross-render in Excel/Word not available
- V712-025 BLOCKED_EXTERNAL: no Microsoft Excel in this environment
- V712-029 NOT_VERIFIED: no Microsoft Word in this environment
- V712-035 NOT_VERIFIED: LibreOffice render only; Word desktop fidelity not verified
- V712-039 NOT_VERIFIED: deterministic rules, no live Black Team agent
- V712-040 NOT_VERIFIED: deterministic rules, no live Red Advocate agent; adjudicated revisions not applied to the register
- V712-042 NOT_VERIFIED: no independent live model agents were run; the challenge engine is deterministic (SINGLE_PROCESS_RULE_BASED)
- V712-046 NOT_VERIFIED: no independent live model agents were run; the challenge engine is deterministic (SINGLE_PROCESS_RULE_BASED)
- V712-057 BLOCKED_EXTERNAL: Article 00.8 reference-case package (20 October 2026) not supplied; no replay possible
- V712-058 BLOCKED_EXTERNAL: signed DoA, sector responsibility status, GCO title sign-offs and legal review are institutional acts not supplied

## Resume from here

1. `python -m pytest tests -q` — must stay green (TEST 01–34).
2. `python tools/build_deliverables.py` — rebuilds demos, migration, verification, gates, tests, protocol, decisions.
3. `python tools/baseline_audit.py EVIDENCE && python tools/patch_status.py && python tools/build_rc.py`.
4. Institutional inputs still missing (BLOCKED_EXTERNAL): Article 00.8 reference-case package, signed DoA, department approval of mandates, GCO reviewer sign-offs; Excel 365 / Word desktop checks (NOT_VERIFIED). Supply them outside the engine; re-run step 3 so PATCH-STATUS reflects the evidence.
