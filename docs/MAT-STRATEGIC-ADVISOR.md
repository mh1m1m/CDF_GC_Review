# MAT Strategic GRC Advisor — architecture (branch `feature/v712-mat-professional-dna-agent`)

An advisory role that applies a reviewer's **documented** professional review method at three points of the
v7.12 protocol. The method itself (the "professional DNA" profile) is extracted from the reviewer's own comment
history with the forensic tools in `tools/mat_dna/`, lives in a **private** location, and is loaded at run time.
The public repository holds only the extraction code, the profile schema and loader, the agent, synthetic fixtures
and tests. Nothing in it is the reviewer's text or an institutional document.

## 1. Protocol position (Article 10–13 of the directive, compatible with the authoritative v7.12 sequence)

```
DOCUMENT INGESTION → EVIDENCE VERIFICATION → GCO DRAFTING AGENT
      → MAT-01 drafting advice (candidates preserved) ──┐
BLACK TEAM objection                                     │ advisory layer; no engine state is changed
      → MAT-02 interrogation (participation disclosed) ──┤
RED ADVOCATE (sees MAT-02 as labelled advisory)          │
      → MAT-03 reassessment (fresh context) ─────────────┘
INDEPENDENT ADJUDICATOR (sees MAT-02/03 only as ADVISORY_ONLY_NOT_EVIDENCE, with the disclosure)
      → GCO EDITORIAL → HUMAN AUTHORIZATION → INDEPENDENT FINAL REVIEW → RELEASE GATE
```

The authoritative sequence (`agents/orchestrator.py`) is unchanged: the advisor is inserted as advisory stages
and never rewrites an approved requirement. With no profile configured the stages do not run and every
record says so (`execution_summary.mat_advisor.enabled = false`).

## 2. Components

| File | Role |
|---|---|
| `tools/mat_dna/ooxml_forensics.py` | Word package forensics: comments (ids, authors, dates, `w14:paraId`, anchors, threads, resolved flags), tracked changes, core properties; evidence-based matching between two versions (`PARA_ID` → `REF_CODE` → `ANCHOR_TEXT` with date continuity or textual derivation → `COMMENT_TEXT_EXACT` → `SAME_PARAGRAPH_DATE_CONTINUITY` → `TEXT_SIMILARITY`); change types incl. `EMPTIED_IN_PLACE`, `DROP_RATIONALE`, `REFERRAL_TO_COLLEAGUE`; provenance per comment (`UNCHANGED`, `EDITED_IN_PLACE`, `RECREATED_AT_ANCHOR`, `NEW_COMMENT`, `ABSENT`). A comment missing from a later version is `REMOVED_FROM_VERSION` with `DECISION_NOT_OBSERVED` — never a withdrawal. |
| `tools/mat_dna/dna_deliverables.py` | Renders the JSON deliverables (questionnaire, distribution, register) to `.xlsx`. Generic. |
| `cdf_gco_crms/agents/mat_profile.py` | `PROFILE_SCHEMA`, `load_profile()` (explicit path or `CDF_MAT_PROFILE`), `LoadedProfile.binding()` (id, version, sha256, status, approval), `rule_status()` → `BINDING` only when the profile is VALIDATED **and** APPROVED **and** the rule is `mat_explicitly_approved`; otherwise `ADVISORY` / `NOT_ESTABLISHED` / `UNKNOWN_RULE`. |
| `cdf_gco_crms/agents/mat_advisor.py` | `MatAdvisor.draft / interrogate / reassess`, the three JSON schemas, stage prompts, the rule-based fallback (documented markers), deterministic guards, `MatObservationState` (Article 15 audit record). |
| `cdf_gco_crms/agents/orchestrator.py` | `ReviewOrchestrator(..., mat_profile=)`; `_mat_drafting`, `_mat_interrogation`, `_mat_reassessment`, `_mat_for_adjudicator`; `ex.mat_advice`, `ex.mat_state`, `ex.mat_disclosure`; `<record>.mat-state.json` next to the challenge record; `execution_summary.mat_advisor` in the gate record. |
| `cdf_gco_crms/agents/debate.py` | `Exchange.advise()` — advisory turns recorded outside the hash chain; repeats are unproductive; `advisory_view()` for other roles' payloads. |
| `cdf_gco_crms/agents/context_builder.py` | `mat_advisory` in the red-advocate and adjudicator payloads; adjudicator instructions state that advisory material is not evidence and does not bind. |
| `main.py` | `--mat-profile PATH | synthetic` on `review`, `challenge`, `adjudicate`, `agent-review`; output field `mat_advisor`. |
| `tests/fixtures/mat/synthetic_mat_profile.json` | Fictional profile (`SYN_GRC_DNA`), PROVISIONAL / NOT_APPROVED. |
| `tests/test_mat_forensics.py`, `tests/test_mat_advisor.py` | 15 tests (see §6). |

## 3. Outputs and guards

Drafting decisions: `KEEP, REVISE, STRENGTHEN, SOFTEN, CONVERT_TO_QUESTION, CONVERT_TO_RECOMMENDATION, NARROW, MERGE,
REQUEST_EVIDENCE, PROPOSE_WITHDRAWAL, ESCALATE`. Debate decisions: `DEFEND_WITH_EVIDENCE, ACCEPT_OBJECTION,
REVISE_RECOMMENDATION, CONVERT_TO_QUESTION, NARROW_SCOPE, MERGE_OBSERVATIONS, REQUEST_ADDITIONAL_EVIDENCE,
PROPOSE_WITHDRAWAL, ESCALATE_TO_HUMAN`. Every output carries the profile binding and `advisory_only = true`,
`binding_disposition = null`; the schemas reject any disposition-like field.

Deterministic guards applied to live and fallback output alike: `PERSON_REFERENCE_REMOVED` (honorific + name →
role placeholder), `UNKNOWN_RULE_DROPPED`, `NOT_ESTABLISHED_RULE_CANNOT_SUPPORT_WITHDRAWAL`,
`WITHDRAWAL_GROUND_DEFAULTED_TO_W15`, `REGULATORY_SAFEGUARD_GUARD` (a proposed withdrawal of an AML / regulator-access /
mandatory-reporting safeguard becomes an escalation — false-withdrawal protection, Article 16.2),
`HALLUCINATED_REFS_DROPPED`, `CANDIDATE_NOT_ASSESSED` (escalated, never dropped), `UNSUPPORTED_DEFENCE_DOWNGRADED`,
`REVISION_WITHOUT_TEXT`, `POSITION_CHANGE_RECORDED`, `REVERSAL_WITHOUT_REASON`. A candidate is never removed:
`candidate_preserved = restorable_by_human = true`.

## 4. Firewall and cycle control

* The advisor never sees adjudicator material (its payloads carry no such keys; tests assert it) and the adjudicator
  sees the advisor only under `mat_advisory` with `status = ADVISORY_ONLY_NOT_EVIDENCE` and the participation
  disclosure. The adjudicator's disposition comes from its own invocation; the guards of `roles.guard_disposition`
  apply unchanged.
* Advisory turns are recorded on the exchange (`advisory_turns`) and never appended to the objection's hash chain:
  the six-productive-cycle limit per objection is untouched; a seventh productive cycle is still refused
  (`tests/test_mat_advisor.py::test_advisory_turns_never_consume_productive_cycles`).
* A failed advisor invocation is a provider failure like any other: the run is BLOCKED and the gate stays closed.
* Independence classification (`_independence`) and the attestation's required roles are unchanged: the advisor is
  not a challenge role and never contributes to an independence claim.

## 5. Private workspace (never committed)

`private/` is git-ignored. The forensic inputs, the observation-evolution register, the 64-question DNA
questionnaire, distributions, writing DNA, selection and withdrawal rules, the style guide, the evidence register,
the validation report and the profile (`MAT_PROFESSIONAL_DNA_PROFILE.json`, status PROVISIONAL / NOT_APPROVED) live
there. Run with `--mat-profile private/.../MAT_PROFESSIONAL_DNA_PROFILE.json` or `CDF_MAT_PROFILE=…`. Sending
institutional content to an external provider still needs `CDF_AI_DATA_AUTHORIZATION=INSTITUTIONAL_AUTHORIZED:<ref>`.

## 6. Tests

`tests/test_mat_forensics.py` (4): extraction on a synthetic pair; evidence-based matching with every provenance
class; removal ≠ withdrawal; hamza-insensitive, word-bounded classifier; CLI + xlsx. `tests/test_mat_advisor.py`
(11): loader and binding; rule-based drafting with guards; guarded live drafting; interrogation disclosure, question
selection and unsupported-defence downgrade; evidence-based reversal recorded without penalty; adversarial cases
(Article 16.3); cycle control; deterministic and mock-live orchestration with the firewall, the Article 15 state and
the unchanged gate; advisor provider failure blocks; CLI flag.

## 7. What is not claimed

No live inference ran (no credential; `actual_live_inference_count = 0`). The private profile rests on one review
case with shared-account authorship; every rule is single-case evidence and none is approved by the reviewer. The
rule-based fallback applies documented markers and is labelled as such; it is not the reviewer's judgment. Writing-
and decision-fidelity scores (Article 16.1–16.2) and the baselines of Article 16.4 need a second independent case
and a live provider; they are NOT_RUN.
