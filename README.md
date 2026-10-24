<!-- Author: Mohammed Alsaleh | Last modified by: Mohammed Alsaleh | Company: صندوق التنمية الثقافي | Title: CDF–GCO–CRMS v7.12 source -->
# CDF–GCO–CRMS v7.12 — workbook engine

Builds the requester feedback workbook of the CDF–GCO–CRMS protocol with its executive dashboard
"لوحة المتابعة التنفيذية" (protocol Art. 10.4A) in the CDF brand library of Annex D.11 (v7.12), appends review
rounds, migrates v7.10 and v7.11 workbooks, writes Word follow-ups as native reply threads (G-SYNC-9),
reconciles with Word comments, carries the authority reference index (02.6, D.13), runs the deterministic
pre-issue challenge (19A) and enforces a release authorisation gate (19A.9) on every issuing command.

This is the **public engineering repository**. It holds the engine, the tests, the build tools, the patch register
and the forensic audit harness. It holds **no** institutional document, reference PDF, review case, brand asset or
protocol text: `REPOSITORY-STRUCTURE.md` lists what is tracked and what is excluded by policy.

## Status (three dimensions, never merged into one claim)

| Dimension | Status |
|---|---|
| Deterministic engineering | COMPLETE — 60-patch register: 49 PASS, 8 NOT_VERIFIED, 3 BLOCKED_EXTERNAL (`PATCH-STATUS.md`) |
| Multi-agent AI | LIVE_AGENTS_NOT_INTEGRATED_VERIFIED — the live runtime is implemented and tested in scripted and deterministic modes; no live inference has been executed or verified (no provider credential in CI or in the authoring environment) |
| Institutional approval | PENDING — never granted by a tool; the `release` command and the gate only report |

## Quick start (fresh public clone)

    python -m pip install -r requirements-lock.txt   # exact versions (Python ≥ 3.11); LibreOffice optional (render/recalc tests skip without it)
    python -m pytest tests -q                        # the whole suite runs without institutional files:
                                                     # the reference layer falls back to the public SYNTHETIC fixture
    CDF_TEST_SYNTHETIC_REFERENCE=1 python -m pytest tests -q   # force the fixture even where the sources are on disk
    python main.py --help

Tests that need the institutional reference PDFs (`tests/test_references.py`, `tests/test_challenge.py`, parts of
`tests/test_assurance.py`) and the design-guide page render (one test in `tests/test_brand.py`) **skip** on a public
clone with the reason printed; everything else, including the end-to-end case, the challenge and the release gate,
runs on `cdf_gco_crms/references/synthetic_index.py` — a fictional organisation and matrix labelled
`SYNTHETIC_NOT_APPROVED` everywhere.

## Workflow and the release gate

    python main.py round1 INPUT.json OUT_DIR                        # → "<name> - WORKING-COPY.xlsx" (a draft is never issuable)
    python main.py review  WB.xlsx --docx CASE.docx [--synthetic-reference]   # 19A challenge → build/adversarial/*.json + gate record
    python main.py adjudicate WB.xlsx DECISIONS.json --docx CASE.docx --trust-store KEYS.json   # signed reviewer decisions only
    python main.py build-excel WB.xlsx OUT_DIR [--issue]            # issuable only when the gate record for THIS content is CLEAR
    python main.py build-word  WB.xlsx OUT.docx [--source CASE.docx]
    python main.py append RETURNED.xlsx ROUND.json OUT_DIR --delivered DELIVERED.xlsx   # → next-round WORKING-COPY

`cdf_gco_crms/release/authorization_gate.py` fingerprints the reviewed content (document, rounds, every
observation's text and cells; title decisions carry their own proof). `rebuild`, `finalize-titles`, `build-excel` and
`build-word` refuse (return code 3) while no CLEAR, unaltered review record exists for exactly that fingerprint;
`--working-copy` writes a marked, non-issuable working copy instead (file suffix ` - WORKING-COPY`, marker in the
package properties). A review run with `--synthetic-reference` never authorises a non-demo issue.
Return codes: 0 OK · 1 FAIL · 2 input error · 3 refused by policy · 4 NOT_VERIFIED.

## Live multi-agent runtime (branch `feature/v712-live-multi-agent-runtime`)

`cdf_gco_crms/agents/` adds AI agents for the analytical roles without replacing a single deterministic safeguard:

| Module | Role |
|---|---|
| `providers/` | `anthropic_adapter` (LIVE, official SDK, credentials resolved from the environment only), `mock_adapter` (MOCK, scripted), `cached_adapter` (CACHED replay of recorded live responses). `provider_from_env()` returns None unless `CDF_AI_PROVIDER` is set — never a silent mock. |
| `runner.py` | one fresh execution context per invocation: unique Execution_ID, Context_ID from the exact prompt material, schema validation, bounded retries, sanitised trace; a failure, refusal or schema violation is a non-result |
| `roles.py` | Agent A drafting, B black team, C red advocate, D adjudicator, E editorial, F independent final reviewer; deterministic fallbacks for the challenge roles (the rule engine), rule-based fallbacks for editorial and final review (labelled as such); guards re-apply the rule adjudicator's invariants to every live disposition |
| `debate.py` | six *productive* cycles per objection; repeats never consume a cycle; the seventh is refused; unresolved → escalated |
| `orchestrator.py` | Article 06 pipeline → `ChallengeRecord` (hash-chained) + gate record; a provider failure escalates and blocks |
| `evaluator.py` | sealed public holdout (`tests/fixtures/holdout`, 24 cases) scored per mode; DETERMINISTIC is a baseline, never a pass |
| `release/trust.py`, `release/dispositions.py` | institutional trust store with revocation, validity windows, roles and state binding; authorised disposition application with ledger and rollback |

Configuration (environment only; nothing in the repository):

    CDF_AI_PROVIDER=anthropic            # LIVE; the SDK resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / a CLI profile
    CDF_AI_MODEL=claude-opus-5-5         # default
    CDF_AI_DATA_AUTHORIZATION=SYNTHETIC_ONLY   # institutional content leaves the process only with INSTITUTIONAL_AUTHORIZED:<ref>

    python main.py agent-review WB.xlsx --docx CASE.docx [--draft] [--decisions D.json --trust-store KEYS.json] [--execution-json OUT]
    python main.py apply-dispositions WB.xlsx DECISIONS.json OUT_DIR --docx CASE.docx --trust-store KEYS.json
    python main.py evaluate-holdout --json build/holdout.json

Without a configured provider every command runs the challenge roles as DETERMINISTIC rules and says so in its
output (`modes`, `independence`); the live tests in `tests/test_agents_live.py` are skipped, not passed.
**No live model inference has been executed or verified in this repository's CI or in the authoring session.**

### Institutional issue: evidence, not labels (PR #3 review remediation)

For a non-demo document the gate (`release/authorization_gate.py::authorize`) refuses an official issue unless all of
the following hold, each checked from evidence at issue time:

| Control | Evidence the gate reads | Refusal reason |
|---|---|---|
| Independent final review ran LIVE on this content | the runner's trace line for the review's Execution_ID: mode LIVE, status OK, known live provider, provider-shaped invocation id, response hash; bound to the review-state fingerprint | `FINAL_REVIEW_NOT_LIVE`, `FINAL_REVIEW_EXECUTION_RECEIPT_INVALID`, `FINAL_REVIEW_BOUND_TO_OTHER_REVIEW_STATE` |
| Source document bound | the caller supplies `--docx`; its SHA-256 must equal the hash the review examined | `SOURCE_DOCUMENT_HASH_REQUIRED_FOR_INSTITUTIONAL_ISSUE`, `SOURCE_DOCUMENT_VERSION_MISMATCH` |
| Agent independence verified | `release/attestation.py::verify_live_roles` over the trace: every challenge role has a live receipt, distinct Execution_IDs and Context_IDs, no MOCK/CACHED/DETERMINISTIC substitution, evidence ids in the registry | `AGENT_INDEPENDENCE_NOT_VERIFIED` |
| Release attestation | Ed25519 signature by a trust-store key with role `RELEASE_ATTESTOR` over fingerprint, document hash, challenge-record hash, role proofs, final-review receipt, decision ids, validity interval, purpose | `RELEASE_ATTESTATION_MISSING`, `RELEASE_ATTESTATION_INVALID:<reasons>` |

A deterministic or mock READY, a forged `mode=LIVE`, an omitted source hash or a locally written record never
clears an institutional issue (`tests/test_release_attestation.py`). Demo documents and `INTERNAL_DRAFT__`
outputs keep the previous rules. The attestation key is operator-held (`--attestation-key FILE`
`--attestation-key-id ID` on `review` / `agent-review` / `adjudicate`); its public key and role live in the
institutional trust store, never in the repository.

Live-provider trial (public-safe, synthetic only): `python tools/live_provider_trial.py` — stops at the first
blocked stage (configuration → connectivity → evaluation) and prints the exact reason and next action.

### Live-inference provenance (what counts as a live call)

`cdf_gco_crms/agents/provenance.py` derives an **execution source** from the adapter object the runtime was built
with, never from a declared mode or a self-reported provider name:

| Source | Meaning | Counts as live inference |
|---|---|---|
| `PROVIDER_API` | the registered Anthropic adapter class, built from configuration, with a provider-originated request id | yes (status OK) |
| `PROVIDER_API_UNTRUSTED_CLIENT` | the registered class with an injected client (test harness) | no |
| `SIMULATED_LIVE` | any other adapter that declares `mode=LIVE` (test fixtures that imitate a provider) | no |
| `MOCK_SCRIPT`, `CACHED_REPLAY`, `DETERMINISTIC_RULES`, `FAILED` | scripted, replayed, rules, no usable result | no |

Every trace line is hash-chained (`prev_hash` / `line_hash`); the chain head is stored in the gate record and
signed into the attestation. Each line separates **provider-originated** evidence (`Invocation_ID` = provider
message id, `Provider_Request_ID` = HTTP request id reconcilable with the provider's logs, server-echoed model and
usage) from **locally generated** telemetry (Execution_ID, Context_ID, hashes, timestamps), and is bound to the
run, the review-state fingerprint and the hash of the role's own instructions. A receipt verifies only when it is
`PROVIDER_API`, carries a request id, belongs to this run and fingerprint, and the chain is intact
(`tests/test_live_provenance.py`). `actual_live_inference_count` counts `PROVIDER_API` + OK only; simulated,
cached and mock calls are counted separately. A valid attestor signature authenticates the record; it never
turns unverified execution claims into verified ones.

## MAT strategic GRC advisor (branch `feature/v712-mat-professional-dna-agent`)

An advisory role that applies a reviewer's documented review method ("professional DNA") at three protocol points —
drafting advice after the GCO drafting agent, interrogation after a Black Team objection (participation disclosed),
reassessment after the Red Advocate (fresh context) — without changing any engine outcome: candidates are never
removed, advisory turns never consume a debate cycle, the adjudicator sees the advisor only as labelled
`ADVISORY_ONLY_NOT_EVIDENCE` material, and the advisor never approves or adjudicates. The profile is loaded from a
private location (`--mat-profile PATH` or `CDF_MAT_PROFILE`); the public repository ships the forensic extraction
tools (`tools/mat_dna/`), the schema and loader (`agents/mat_profile.py`), the agent (`agents/mat_advisor.py`), a
synthetic profile (`tests/fixtures/mat/`) and 15 tests. The reviewer's comment history, the extracted profile and
every DNA deliverable stay in the git-ignored `private/` tree. Design: `docs/MAT-STRATEGIC-ADVISOR.md`.

## Build and evidence tools

    python tools/build_deliverables.py         # stages: demo migration verify render gates tests registers references results protocol decisions
    python tools/baseline_audit.py EVIDENCE    # SHA-256 manifest of every authoritative input (V712-001)
    python tools/patch_status.py               # PATCH-STATUS.json/.md and the release-gate matrix from the evidence on disk
    python tools/lineage_audit.py ROUND_DIR    # lineage of a v7.11 round series; baseline-input failures are classified, never hidden
    python tools/build_rc.py                   # dist/ release candidate (not published; see REPOSITORY-STRUCTURE.md)
    python tools/write_docs.py                 # QA report and implementation guide from build/state.json

Several tools need inputs that are excluded from the public repository (institutional sources, v7.11 round files,
the design guide); they report what is missing rather than fail silently.

## Layout

`cdf_gco_crms/` engine (config, model, ingestion, rounds, reconciliation, analytics, excel, word, guidance, branding,
migration, qa, regression, references incl. the synthetic fixture, assurance, release, agents) · `tests/` regression suite
(TEST 01–39 incl. TEST 36 OOXML forensics and TEST 37 MAT advisor) · `qa_public/` PR #2 unittest entry point · `tools/` build, docs, packaging, lineage, patch status · `AI_AGENT_FORENSIC_AUDIT/` read-only audit
harness and reports · `EVIDENCE/` baseline manifest (hashes only, not tracked in the public repository).
