# CDF_GC_Review initial repository and PR audit

Historical pre-fix audit snapshot. Four fixes are implemented by the takeover branch; current results and remaining issues are in TEST_EVIDENCE_REGISTER.md and OPEN_ISSUES.md. Local paths below describe the audit workspace, not portable project prerequisites.

Audited 24 October 2026. Recommendation: keep the stack in draft pending the two authorization fixes and calibration corrections below.

## Scope and PR state

Risk-focused review of the five open PRs, their branch relationships, CI evidence, and the integrated latest source. This is not an exhaustive security certification. Original checkout remains on its unchanged initial commit; source inspection and verification used a detached worktree at `/workspace/cdf-audit`.

| PR | Head | Base | Observed PR CI | Assessment |
|---|---|---|---|---|
| #1 | `492915a` | main | No PR-triggered run returned for this SHA | Engineering baseline; no standalone clean-clone acceptance established here |
| #2 | `e298083` | development | Success, run 39989549736 | Conflicting per GitHub; its head is already an ancestor of #3. Reconcile as superseded rather than merging independently without review |
| #3 | `7fe7444` | development | Success, run 40053736011 | Two reproduced authorization defects; findings 1–2 |
| #4 | `50c339b` | #3 branch | Success, run 40058896046 | Inherits #3 defects; no additional confirmed finding in the inspected MAT profile/advisor paths |
| #5 | `837168c` | #4 branch | Success, run 40062788386 | Inherits #3 defects and introduces findings 3–4 |

All five are open drafts. #3 incorporates the #2 head by merge history. #5's latest CI has three successful jobs: public-safe Python tests, web build, and browser E2E. CI success does not cover the reproduced negative cases below. Repository metadata reports public visibility; confidential source inputs must remain outside tracked source.

## Findings

### 1. P1 — Signed approval does not bind replacement wording (PR #3)

Location: `cdf_gco_crms/release/dispositions.py:94–117`; signed payload: `cdf_gco_crms/assurance/objection_engine.py:105–113`.

`HumanDecision` signs the original state fingerprint, observation ID and disposition, but neither the challenge/proposal digest nor replacement text. `apply_dispositions` then takes `revised_comment` and `revised_quote` from the supplied record without verifying that they are the proposal approved by the signer. The optional text hash only checks the original comment.

Reproduced with a non-demo state and a valid signed `UPHELD_WITH_REVISION`: replace the record's `advocacy.revised_comment` after signing, reuse the unchanged signature, and call `apply_dispositions`. It applies the substituted text with one applied decision and no rejections. No signing-key compromise is needed to substitute a proposal once an approval for that original state exists. CLI re-orchestration can also generate a fresh proposal against the same original fingerprint.

Impact: unauthorized register edits recorded as human-authorized. The resulting new fingerprint still requires a new release review; this finding alone does not demonstrate final institutional issuance.

Fix: sign and verify the exact revision digest, challenge identity and outcome, and reject a mismatched challenge record/proposal before applying text. Add a negative test mutating the proposed comment and quote after signature.

### 2. P1 — Release attestations ignore signing-key validity windows (PR #3)

Location: `cdf_gco_crms/release/attestation.py:293–314`.

`verify` checks the key's role, status, synthetic flag and signature, then validates only the attestation payload's dates. It never checks `KeyEntry.valid_from` or `valid_until`.

Reproduced a correctly signed, currently valid institutional attestation twice: first with an ACTIVE attestor key expired yesterday, then with an ACTIVE key whose validity starts tomorrow. Both return `[]`, meaning accepted. Other release checks still apply, but this trust condition is bypassed even when the trust store explicitly limits the key's lifetime.

Fix: validate the attestor key's dates at issue time, fail closed on malformed configured dates, and test expired/not-yet-valid keys independently from attestation expiry.

### 3. P2 — Later rule rejection does not revoke earlier approval (PR #5)

Location: `cdf_gco_crms/calibration/profile_compiler.py:31–39`.

The compiler accumulates every historical APPROVE event. Later REJECT, DEFER and REQUEST_MORE_EVIDENCE events never remove that rule from the approved map; profile-version scoping is also ignored.

Reproduced: submit one observation, approve `SYN-S01`, reject the same rule for the same profile version, then compile. Compilation succeeds and attaches the old approval evidence to `SYN-S01`.

Impact: a reviewer cannot reliably withdraw a rule's eligibility for subsequent compiled snapshots. These snapshots remain synthetic, provisional and nonbinding; this is not institutional approval escalation.

Fix: reduce review events to the latest effective action for each rule/version, and compile only currently eligible approvals with current evidence. Test approval followed by rejection/deferral.

### 4. P2 — Repeating profile compilation raises an unhandled database error (PR #5)

Location: `cdf_gco_crms/calibration/profile_compiler.py:55–61,73`; insert: `cdf_gco_crms/calibration/store.py:270`.

Profile version is deterministically derived from the same submitted evidence and approvals. Repeating compile without a relevant change attempts to insert the same `(case_id, profile_version)` primary key, while `generated_utc` makes the serialized document differ. The UI leaves compilation available after success, and the API wrapper does not catch SQLite IntegrityError.

Reproduced: compile the same eligible case twice; second call raises `IntegrityError: UNIQUE constraint failed: profile_versions.case_id, profile_versions.profile_version`. Through the API this is an HTTP 500.

Fix: make unchanged compilation idempotently return the existing immutable snapshot, or explicitly allocate a new version. Do not silently overwrite versioned audit artifacts.

## Reproduction

Scripts use ephemeral generated keys, fictional text and temporary databases only:

```sh
cd /workspace/cdf-audit
PYTHONPATH=/workspace/cdf-audit python /workspace/repo-audit/calibration_and_attestation_repro.py
PYTHONPATH=/workspace/cdf-audit:/workspace/cdf-audit/tests python /workspace/repo-audit/revision_repro.py
```

Observed:

```text
expired attestor rejection reasons: []
future attestor rejection reasons: []
Rejected rule compiled: ['SYN-S01']
Repeated compile: IntegrityError UNIQUE constraint failed: profile_versions.case_id, profile_versions.profile_version
Applied unsigned replacement: AUDIT: replacement never signed by reviewer
Applied: 1 rejections: []
```

## Validation

- `npm run build`: passed (TypeScript and Vite production build).
- `python tools/mat_dna/public_repository_guard.py`: passed, 224 tracked entries. This is the repository's heuristic scan, not a comprehensive DLP or history/secret audit.
- Latest #5 GitHub Actions: all three jobs passed, including Chromium browser acceptance. Browser acceptance was inspected remotely, not rerun locally.
- Local Python suite: final result pending at report creation. Initial sandboxed attempt was interrupted after a subprocess wait, with 58 passed and 11 skipped; rerun uses normal process access and a diagnostic timeout.
- No actual LIVE provider inference, institutional approval, or confidential-input acceptance was performed.
- No source fixes, merges, GitHub review comments, or approval changes were made.
