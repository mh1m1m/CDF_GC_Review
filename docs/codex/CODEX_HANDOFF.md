# Codex engineering handoff

## Verified baseline — 2026-10-24
Repository: https://github.com/mh1m1m/CDF_GC_Review (public). Source baseline: 837168c292161e7744e99258879e8653cfea0545. Original main contains only README. Continue the feature stack; do not rebuild the application or merge main.

| PR | Head SHA | Base | State at inspection |
|---|---|---|---|
| 1 | 492915ad9d6d2a457b2b60bd30d051dc6a07b546 | main | open draft |
| 2 | e298083cf48d38886ca081005921827f5e34abf2 | development/v7.12-production-engineering | open draft, conflicting; ancestor of PR 3 |
| 3 | 7fe744460f07b0f8ef88aa5406e7b79bfacebc89 | development/v7.12-production-engineering | open draft |
| 4 | 50c339b7cd5ffe2df45f68ab84ac60f8c0e2e1ab | feature/v712-live-multi-agent-runtime | open draft |
| 5 | 837168c292161e7744e99258879e8653cfea0545 | feature/v712-mat-professional-dna-agent | open draft |

PR 3 contains PR 2's head through merge history. PR 4 builds on 3 and PR 5 on 4. Recheck before future work; branch topology is a snapshot.

## Architecture and evidence
The existing engine manages review rounds, evidence, challenges, Word comments and Excel registers. Multi-role orchestration supports deterministic, mock and provider adapters. The MAT advisor has three stages, candidate preservation and an adjudicator firewall. Calibration has SQLite events, local token API, RTL UI, separate rule review and synthetic profiles. See CURRENT_STATE_AUDIT.md and INTEGRATION_MATRIX.md for source paths and limits.

Historical handoff claims 218 passed / 17 skipped and browser success. Latest baseline CI run 40062788386 independently reports success for Python, web build and browser E2E. Historical private-workspace counts are not public-clone validation. No live model inference or institutional acceptance was established by this takeover.

## First-cycle remediation
INITIAL_AUDIT_FINDINGS.md records four independently reproduced defects on the baseline. This branch binds text-changing signatures to exact proposals, validates attestor-key validity windows, honors later rule rejection/deferral and makes unchanged profile compilation idempotent. Old signatures authorizing text changes must be reissued with challenge_id and revision_sha256; non-text signatures retain compatibility.

The synthetic rule compiler conservatively treats the latest action for a rule across versions as effective. APPROVE_WITH_CHANGES cannot compile unspecified changed wording. Version-specific rule bodies and a proper amendment workflow remain future work.

Institutional SSO/entitlements, managed signing keys, private storage, retention/backups, externally anchored audit logs, independently labelled cases and authorized live-provider trials remain external or future dependencies. No production readiness or personal reviewer validation is granted.

Read ROADMAP.md for the next work package and TEST_EVIDENCE_REGISTER.md for exact validation limits. Use SESSION_HANDOFF_TEMPLATE.md at the next handoff.

## Signing-contract migration
For a text-changing HumanDecision, an authorized signing workflow must display the actual proposal to the reviewer, set `challenge_id` to that objection's identity, and set `revision_sha256 = revision_digest(challenge_id, revised_comment, revised_quote)` from `cdf_gco_crms.release.dispositions` before signing `signature_payload()`. Preserve null versus empty quote/comment values. Any later wording change needs a new signature. Non-text outcomes retain legacy signature compatibility. Hashing a proposal is not itself human approval.

## Stable document-engine runtime
Use [STABLE_LIBREOFFICE.md](STABLE_LIBREOFFICE.md) for the pinned Debian container, real Calc/Writer/Impress smoke checks, mandatory engine tests and independent CI. The historical alpha-runtime failure remains documented separately; container verification does not change the managed host installation. Current exact results are in TEST_EVIDENCE_REGISTER.md.
