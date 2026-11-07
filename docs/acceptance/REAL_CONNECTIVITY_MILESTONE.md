# Real MCP connectivity and verified AI inference

Base: preserved draft PR #11 at `2cbc880795027b0b3642a22b3fa881e7725d8d1f`. Work continues on `codex/real-mcp-connectivity`; no merge, history rewrite, deployment or private activation.

## Actual milestone status

**BLOCKED_EXTERNAL — genuine external client registration and successful model completion have not been established.** The new code/security checks are not substitutes for those missing results.

| Requested result | Actual evidence/status |
|---|---|
| Diagnose native Codex timeout | Fresh explicitly authorized single-stage fictional probe, separate from the original job: one persisted attempt, thread/turn start, six error events, connection/HTTP 403/reconnect categories, no completed turn. `codex-diagnostic.json` preserves sanitized evidence. Original attempt remains unresolved and unreplayed. |
| Verified inference receipt | BLOCKED_EXTERNAL; zero successful native/API completions. `independent-receipt-audit.json` verifies local chain/source/job/prompt bindings without asserting provider attestation. |
| Remote MCP/OAuth deployment | TLS-only resource server/configuration implemented and tested locally. Actual public DNS/TLS host, OAuth issuer/JWKS and deployment identity are absent; NOT_DEPLOYED / BLOCKED_EXTERNAL. |
| Actual ChatGPT registration | BLOCKED_EXTERNAL; user selected ChatGPT as target, but no approved hostname/issuer or account portal integration capability was supplied. |
| Actual Claude registration | BLOCKED_EXTERNAL; no account/client integration or executable/login available. |
| Controlled real-model governance task | Attempted one new synthetic drafting probe; failed before a completed receipt. No mock/deterministic replacement. |
| Persisted independently checked provenance | Source hash, attempt identity, prompt hash, role, job, terminal status and local trace chain independently checked. External provider reconciliation remains NOT_VERIFIED. |
| Same resulting live case across MCP/CLI/React | BLOCKED_EXTERNAL because no successful live-model case exists. Existing synthetic regression remains separate. |
| Word/Excel/PDF from resulting live case | BLOCKED_EXTERNAL for that case. Existing export regression/Calc tests continue independently; no live export verification claim. |
| Isolation/approval/release | Existing public/private guards, advisory MAT, independent roles, human checkpoints and fail-closed release gate preserved. |

## Timeout findings and changes

The original 60-second job and CLI deadlines overlapped, allowing supervision to kill the worker before the native CLI failure diagnostics could be published. The inner executor now leaves five seconds for failure publication. Metadata-only progress is committed during execution, so an outer interruption retains observed phases/errors even without a final receipt.

A new diagnostic (`SYN-REAL-CONNECTIVITY-001`, job `JOB-f4ec4f4f81b24d269ee68f4a5e5f0177`) observed HTTP 403/connection errors and reconnection with no `turn.completed`. Normal CLI login is available; login does not prove inference permission or completion. Current enforced environment spec 18 allows package-manager destinations, has no configured provider secrets/outbound identity or OAuth deployment variables, and has no retained network diagnostic bundle. Exact denied host/response bodies were not retained, so policy denial versus provider denial is not conclusively distinguished. This evidence narrows the failure but does not establish a repaired external connection.

The final collector fails promptly on observed 401/403 error events, caps stdin/stdout/stderr, handles a child that never reads input, preserves only byte counts/hashes and fixed event/error categories, disables the CLI shared daemon and never automatically retries. A configured model selector is now passed to the native command; consumer CLI provenance remains SUPERVISED_CLI, distinct from trusted API provenance. No new native attempt was made after the access-denial observation. The checked-in failed diagnostic was captured during development before those final fail-fast/daemon refinements; final tests use explicitly labelled local subprocess fixtures, not another real inference attempt.

## Security and reproduction

The external OAuth server owns authorization-code/PKCE/consent/client registration. The resource server verifies the pinned RFC 9068 RS256 access-token profile and maps an exact subject/client pair to server-defined synthetic roles. JWT roles/case claims are ignored; no implicit case grants, institutional identities or development bearer access. See [deployment configuration](../../../deploy/remote-mcp/README.md).

Local focused verification runs actual signature validation, wrong issuer/audience/token type/key/client/subject/expiry/scope, role escalation/foreign cases/revocation, HTTPS/Host/Origin/body limits, a real TLS socket with an independent SDK client, invalid CA rejection, bounded child processes and receipt tamper tests. These fixtures use an ephemeral local issuer/key and are explicitly not external account/client evidence.

```sh
python -m pytest tests/test_remote_mcp.py tests/test_remote_tls.py tests/test_cli_receipts.py tests/test_receipt_audit.py tests/test_connectivity_status.py -q
python -m cdf_gco_crms.execution.receipt_audit --db <protected-synthetic-db> --case SYN-REAL-CONNECTIVITY-001
python -m cdf_gco_crms.acceptance.connectivity --db <protected-synthetic-db> --case SYN-REAL-CONNECTIVITY-001 --output <report.json> --require-complete-milestone
```

The last command exits 3 while the milestone is blocked. Collecting a readiness report can succeed while its milestone remains BLOCKED_EXTERNAL. The checked-in report is an observed snapshot, not a startup authorization or a live receipt. No tokens, raw stderr, credentials or databases are committed.

## Remaining external inputs

Approved public hostname and TLS provisioning; OAuth issuer/JWKS/token profile and actual registered client IDs; ChatGPT/Claude account connector access; permitted network destinations; authorized provider credential/model or a functioning normal native CLI connection; independent provider-side receipt reconciliation. Sensitive institutional processing and private mode require their existing separate approvals. None of these gaps is marked PASS by configuration or local tests.
