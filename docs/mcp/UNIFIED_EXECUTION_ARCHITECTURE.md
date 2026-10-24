# Shared synthetic execution architecture

The existing engine is the source of governance behavior. The Python application CLI, official MCP SDK server and FastAPI/React interface share `ApplicationService`, `CalibrationService`, `IntelligenceService`, the existing `ReviewOrchestrator`, canonical agent contracts, the public reference provider and one SQLite database. No second agent framework, remote database or queue infrastructure is introduced.

## Authoritative records

`app_cases` stores the actual fixed fictional DOCX and SHA-256. An intake grant permits the owner to launch its first review. Publication atomically imports the eight document-anchored observations into the existing calibration case, records the existing engine execution and appends the job/audit records. Reviewed cases subsequently require the existing durable case grant. Calibration, dashboard projection and reports read that same case.

`app_jobs` owns the accepted request, actor session, deadline, lease, attempts, run ID, terminal result and failure stage. A supervisor atomically claims QUEUED once, starts an isolated compute process, renews its lease and terminates descendants on timeout, cancellation or expired authentication. Publication checks the current lease, deadline, session and case permission under the SQLite writer transaction. Cancellation cannot publish a later result. An expired RUNNING lease becomes FAILED / OUTCOME_UNKNOWN; recovery does not repeat an ambiguous external request. Operators explicitly resume unclaimed QUEUED work with `job recover`.

States: QUEUED → RUNNING → WAITING_FOR_HUMAN for successful review/debate; exports and stage probes end COMPLETED. FAILED, CANCELLED and BLOCKED_AUTHORIZATION are terminal. WAITING_FOR_HUMAN never means institutionally approved.

Mutations accept an idempotency key scoped to principal and operation. Identical replay returns the original job/result; changed request content returns a conflict. A partial unique index permits one active review/debate per case. This is local replay prevention, not a claim of exactly-once provider execution. Automatic provider retries are disabled in this interface.

## Client boundaries

- `python -m cdf_gco_crms.cli`: local, explicitly provisioned synthetic development session; fixed application subcommands, JSON and meaningful exit codes.
- `python -m cdf_gco_crms.interfaces.mcp_server`: official SDK Streamable HTTP on loopback with expiring bearer verification, typed request/output schemas, case/role authorization and bounded output. Stdio uses the explicitly inherited local development session. It is an isolated local integration server, not an internet deployment.
- FastAPI `/api/operations/{tool}`, `/api/cases/{id}/execution` and authenticated artifact download: same service and identity. React displays persisted jobs and reports alongside the existing dashboard, debate, evidence, MAT and calibration views.

Only fixed synthetic source creation is enabled. Arbitrary file paths, private uploads, arbitrary subprocess commands, caller-selected identities and institutional activation are absent from the tool inputs. No application token is passed on a subprocess command line.

## Artifacts and provenance

Artifacts contain actual DOCX/XLSX/PDF bytes, media type, SHA-256, originating job and case-state fingerprint. MCP retrieves bounded base64 chunks; CLI reassembles and verifies the hash; React downloads authenticated bytes. Existing artifacts remain labelled as earlier snapshots after relevant case changes. No report grants issuance authority.

Agent attempts persist STARTED before each actual invocation and a canonical completion receipt afterwards. Incomplete attempts are OUTCOME_UNKNOWN. Existing trace hash chains remain local integrity evidence, not third-party attestation. API inference, supervised consumer CLI inference, deterministic rules, explicit mocks and cached replay remain distinct. A supervised CLI receipt never satisfies the existing API-provenance release requirement.

Production limitations: single-host SQLite pilot, explicit queued-job recovery, no background distributed scheduler, no durable cross-host process supervisor, no configured external OAuth issuer or approved HTTPS endpoint. Private institutional HTTP remains disabled. See authorization and external-blocker documents before considering deployment.
