# CDF–GCO–CRMS engineering instructions

Continue the existing Python engine, FastAPI API, React/TypeScript RTL UI and SQLite pilot. Inspect before changing architecture. Read docs/codex/CODEX_HANDOFF.md, EXECUTION_LOG.md and OPEN_ISSUES.md at session start; check branch, status, current PR heads and CI. Durable evidence takes precedence over historical completion claims.

## Source of truth
Current source and reproducible evidence establish implemented behavior; versioned decisions describe intended policy; historical handoffs are leads to recheck. Explicit user instructions govern authorized engineering scope. Institutional approval must come from verified authorized records, never inferred from code or conversation.

## Authority and confidentiality
- This repository is public. Commit generic source, documentation and fictional fixtures only. Keep agreements, policies, real observations, reviewer profiles, calibration records, source hashes, keys and databases in authorized private storage. Never copy private source text into public reports.
- Software-development authorization is not institutional approval, permission to deploy, or permission to send confidential content to a provider. Institutional authorization remains NOT_AUTHORIZED until independently evidenced.
- Never fabricate reviewer signatures, regulatory citations, human-approved DNA rules, provider receipts or live execution counts.

## Architecture and human control
- Preserve separate drafting, Black Team, Red Advocate, adjudicator, editorial and final-review roles and purpose-limited contexts. MAT-01/02/03 advise only; MAT cannot approve, adjudicate, issue, or replace independent roles.
- Keep original observations restorable. Missing comments mean REMOVED_FROM_VERSION / DECISION_NOT_OBSERVED, never automatic withdrawal. Material withdrawals require authorized rationale and evidence or an explicitly recorded gap.
- Observation calibration and DNA-rule approval are separate. Synthetic profiles remain PROVISIONAL / NOT_APPROVED and nonbinding.
- Fail closed on issuance: bind review state, source version, exact signed replacement proposal, trusted human decisions, revocation/expiry, required provider provenance, final review and attestation. Never weaken controls to pass a test.
- LIVE labels, mocks, cached responses, deterministic logic and local hash chains do not independently prove provider inference. Preserve source classifications and honest counters.

## Workflow and verification
- Work in a feature branch on the appropriate stacked base; do not reset history, retarget existing PRs or merge into main without explicit instruction. Open draft PRs for review.
- Use focused, incremental changes and meaningful negative tests for authorization/state transitions. Reuse existing contracts. Text-changing decisions must sign challenge_id and revision_sha256 via revision_digest; legacy unbound revision approvals are rejected.
- Run relevant Python tests, public_repository_guard, and UI build/browser tests when affected. Full public suite: python -m pytest tests qa_public -q -p no:cacheprovider -rs. Install requirements-lock.txt and optional requirements-calibration.txt. UI: cd apps/web && npm install --no-audit --no-fund && npm run build.
- Report PASSED, FAILED, SKIPPED, NOT_RUN and BLOCKED_EXTERNAL separately; record command, SHA, environment and limitations. Never count skips as passes or successful mock tests as live readiness.
- Update docs/codex/EXECUTION_LOG.md, TEST_EVIDENCE_REGISTER.md, OPEN_ISSUES.md and session handoff after substantial work. Link exact commits, PRs and evidence; distinguish inspected paths from executed capabilities.

## Operating-mode isolation
- Public demo uses the fixed fictional reference provider and a PUBLIC_SYNTHETIC_DEMO database. It must operate without private source mounts/configuration; publication-authorized assets are distinct from institutional brand approval.
- PrivateInstitutionalProvider and PrivateWorkspace are in-process integration ports with a deny-all default. Resolve identity/resource permissions through the trusted InstitutionalAuthorizer; caller roles, environment mode flags and demo tokens never authorize institutional access.
- Keep original copies, source hashes, actual extractions and private brand versions in authorized private storage. Preserve source approval/effective/supersession limits; provider processing and case export require distinct permissions.
- Private HTTP production activation remains disabled pending the institutional prerequisites in docs/institutional/INSTITUTIONAL_REFERENCE_INTEGRATION.md. Passing synthetic tests or a local adapter implementation does not establish approval to activate it.
