# AGENT SECURITY AND AUTHORITY AUDIT — CDF–GCO–CRMS v7.12

## Human authorization bypass attempts (synthetic keys)

| Attempt | Result |
|---|---|
| human_decision=True (boolean) | rejected → PASS |
| dict pretending to be a decision | rejected → PASS |
| fabricated reviewer name, unsigned | rejected → PASS |
| invalid signature | rejected → PASS |
| valid signature but key id absent from trust store | rejected → PASS |
| reuse of a valid approval for another observation | rejected → PASS |
| record modified after signing (decision field changed) | rejected → PASS |
| verification_status NOT_VERIFIED with a valid signature | rejected → PASS |
| expired or revoked authorization (timestamp 2020-01-01, otherwise valid) | ACCEPTED → FAIL |
| Observation constructed with title_status=APPROVED and no evidence | rejected → PASS |
| finalize_titles APPROVE with empty reviewer/date/ref | rejected → PASS |
| finalize_titles APPROVE with non-ISO date | rejected → PASS |
| engine decides WITHDRAWAL-type outcome on an issued observation without a human record | rejected → PASS |
| CONTROL: valid signed record in trust store (expected to be applied) | ACCEPTED → PASS |

Control gaps:

- No expiry, revocation list or validity window exists for a HumanDecision: a stale but validly signed record is accepted (attempt 9).
- The trust store is a caller-supplied dict of raw Ed25519 public keys; no institution-managed key store, key ceremony or CA is connected. INSTITUTIONAL_HUMAN_AUTHORIZATION = NOT_VERIFIED.
- Signing keys used in every test and demo are ephemeral SYNTHETIC keys generated in-process; no CDF key material exists in the package.

INSTITUTIONAL_HUMAN_AUTHORIZATION = NOT_VERIFIED

## Prompt injection, tool authorization, confidentiality, failure injection

| Test | Result | Detail |
|---|---|---|
| INJ-01: injected instruction treated as content (same outcome as clean baseline) | PASS | kinds=[] baseline=[] |
| INJ-01: injected text not echoed into the challenge record as an instruction | PASS | the record may quote document excerpts as evidence; the engine has no instruction channel, so the string cannot execute |
| INJ-02: injected instruction treated as content (same outcome as clean baseline) | PASS | kinds=[] baseline=[] |
| INJ-02: injected text not echoed into the challenge record as an instruction | PASS | the record may quote document excerpts as evidence; the engine has no instruction channel, so the string cannot execute |
| assurance package: no subprocess/socket/eval/exec/network imports, no write-mode open | FAIL | hits=['reference_verify.py: import subprocess'] — reference_verify._pdftotext spawns the fixed binary `pdftotext` (no shell, read-only extraction of a PDF sourc |
| agents can modify source files / execute arbitrary code / send external requests | NOT_APPLICABLE | NOT_APPLICABLE: no agent has tools; the functions have no I/O channel |
| confidentiality_scan of produced workbook and Word files | PASS | 5 files, hits=[] |
| internal challenge records are separate files (not inside requester artefacts) | PASS | ['review.json', 'challenge.json', 'adj.json'] |
| provider unavailable / timeout / rate limit / invalid JSON response | NOT_APPLICABLE | NOT_APPLICABLE: no provider; nothing to time out |
| missing evidence (quoted clause absent) → objection, no fabricated anchor | PASS | kinds=['CLAUSE_NOT_FOUND'] dispositions=['WITHHELD_FOR_EVIDENCE'] |
| contradictory sources bound (binding vs unverified): the unverified one never upgrades or overrides | PASS | objections=[] verified=['EV-e3a780fc3336'] |
| seventh productive cycle refused | PASS | events=6 |
| repeated duplicate objection refused (canonical text + same refs) | PASS |  |
| adjudicator returns an unsupported decision → ValueError | PASS |  |
| hallucinated evidence id does not resolve (KeyError) | PASS |  |
| independent reviewer receives contaminated context (planted 'expected') | PASS | {'disposition_without_label': 'UPHELD_WITH_REVISION', 'disposition_with_planted_expected_attr': 'UPHELD_WITH_REVISION', 'changed': False} |
| tool returns corrupted output | NOT_APPLICABLE | NOT_APPLICABLE: no tools |
| execution interrupted between agents → command fails, no partial record persisted, no approval | PASS | rc=1 stderr_tail='              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nRuntimeError: AUDIT: interrupted between Black Tea |
| persistence failure after adjudication → non-zero exit, nothing silently approved | NOT_VERIFIED | rc=0; euid=0: root bypasses directory permissions, so this injection could not be exercised here (NOT_VERIFIED) |
| idempotence: review twice gives identical chain hash | PASS |  |

## Data protection and confidentiality posture

- No document leaves the process: there is no provider, so no CDF content is transmitted anywhere by the product. The audit's live runs used synthetic documents only.
- Credentials: none exist in the product. The deployment environment exposes a Claude Code gateway variable to the runtime, not to the engine.
- Logs: challenge records are JSON files under build/adversarial; they contain the objection vocabulary and evidence ids and must stay out of requester artefacts (scan: clean).
- Applicable Saudi requirements (PDPL, NCA controls): NOT_ASSESSED here — the deployment context (where the data would be processed once a provider exists) is not defined; assess before any provider integration (R-01).
