# Open issues

| ID | Priority | State | Next action |
|---|---|---|---|
| AUD-01 | P1 | FIX_IMPLEMENTED | Exact signed replacement digest and challenge identity; review negative tests |
| AUD-02 | P1 | FIX_IMPLEMENTED | Attestor key validity enforced; review expired/future/malformed regressions |
| AUD-03 | P2 | FIX_IMPLEMENTED | Latest rule rejection/defer invalidates prior approval; version-specific workflow remains M1 |
| AUD-04 | P2 | FIX_IMPLEMENTED | Unchanged compilation returns stored immutable snapshot |
| ENV-01 | P1 validation | RESOLVED_IN_STABLE_CONTAINER | Stable LibreOffice 25.2.3.2 passes Calc/Writer/Impress smoke and all six engine checks; full suite 243 passed / 11 skipped. Host alpha remains unchanged. See STABLE_LIBREOFFICE.md and TEST_EVIDENCE_REGISTER.md; verify independent CI on the PR head |
| CAL-01 | P2 | OPEN | Model version-specific rule amendments and explicit changed wording; APPROVE_WITH_CHANGES remains ineligible for compilation |
| CAL-02 | P2 | OPEN | Compiler retains historical submitted observation evidence; define supersession and invalidate obsolete rule evidence |
| EXT-01 | P0 release prerequisite | BLOCKED_EXTERNAL | Institutional identity, reviewer provisioning, signing trust and private data approval |
| EXT-02 | P0 release prerequisite | BLOCKED_EXTERNAL | Authorized genuine provider execution and independent labelled holdout |
| PR-02 | P2 | OPEN | PR 2 conflicts and is included in PR 3 history; owner to reconcile superseded draft without automatic merge |

All source fixes await independent review. No institutional acceptance inferred.

| VIS-01 | P1 institutional acceptance | BLOCKED_EXTERNAL | Current DoA approval, effective dates and supersession are not confirmed. Financial thresholds and parsed role qualifiers require human reconciliation; public availability is not authority |
| VIS-02 | P2 visual acceptance | OPEN | Creative glass design and font fallbacks require institutional design review; supplied 8-page guide/real logos inspected, separate historical 87-page guide not reverified |
| VIS-03 | P2 scale/performance | OPEN | Bounded local case graphs and API snapshots; large datasets need paging/virtualization after measured volume. No production SLA claim |
| VIS-04 | P2 assurance | OPEN | Automated axe/screenshot checks are partial accessibility/visual evidence; cross-browser manual review and complete WCAG assessment remain |
| VIS-05 | P1 semantic quality | BLOCKED_EXTERNAL | Human alignment remains unknown until independent validated labels exist; no fabricated confidence/quality gauge |

- INST-01: Implement/provision the trusted institutional identity, tenancy, session and resource-grant adapter; the supplied default denies all private access. Private HTTP activation is intentionally disabled.
- INST-02: Verify current DoA approval/effective date/supersession and reconcile thresholds/ambiguous cells; source date 30 April 2024 is observed, not institutional approval.
- INST-03: Reconcile proposed organization mandates, explicit ownership/reporting/DoA relationships and independent source conflicts without inferred authority.
- INST-04: Institutional acceptance for branding/typography/safe areas, manual accessibility, storage/security/backup operations, real human labels and authorized provider processing remains external.
- INST-05: Verify native x14 sparkline/editor fidelity in Microsoft Excel desktop; other editors may remove the extension. Original XLSX/native charts/formulas and independent Calc reconciliation remain available.

- EXE-01: Actual ChatGPT/Claude MCP registration requires approved HTTPS/authentication deployment and account/client setup; independent official SDK protocol tests are not client connection proof. See docs/acceptance/EXTERNAL_BLOCKERS.md.
- EXE-02: Durable job pilot is single-host SQLite with explicit operator recovery of unclaimed QUEUED jobs and no automatic replay of ambiguous inference. Distributed scheduling, cross-host supervision, production capacity and operational acceptance remain deferred.
- EXE-03: Official provider API paths require approved credentials/model/policy; supervised consumer CLI receipts do not satisfy central API-provenance release requirements. No institutional workload is authorized by a normal consumer CLI login.

- CP-01: General arbitrary-source governance review is not implemented by attaching an extraction. Bind reviewed versions and validated source-specific templates through the existing engine before enabling it. Fixed synthetic cooperation remains the executable review source.
- CP-02: Bounded deterministic intent recognition is not a general language model planner. Policy/framework/charter methodologies need approved templates; targeted observation-subset debate is explicitly unsupported.
- CP-03: New review records use synthetic session identities, not verified human presence or signed institutional dispositions. Existing CAL-01/02 profile amendment/supersession issues and independent human-label validation remain open.
- CP-04: Online backup and staging verification are local operational evidence only. Approved production restore, retention/legal policy, tenant IdP/OAuth, external audit anchoring, live inference and institutional activation remain external prerequisites.

- CON-01: BLOCKED_EXTERNAL — native Codex diagnostic observed HTTP 403/connection/reconnect errors and no completion. Exact denied destination/provider-side outcome is unverified; operator must reconcile access/network policy before a separately authorized new request. Existing ambiguous requests are not replayed.
- CON-02: BLOCKED_EXTERNAL — approve/provision public MCP DNS/TLS, external OAuth issuer/JWKS and exact registered client identities. The new resource server's local security tests do not establish deployment or authorization-server/client compatibility.
- CON-03: BLOCKED_EXTERNAL — actual ChatGPT/Claude account registration and correlated authenticated calls unavailable. Independent SDK connections must remain separately classified.
- CON-04: BLOCKED_EXTERNAL — live-model case reconciliation, native exports and provider-side receipt reconciliation require a successful authorized real execution. No new mock/UI run may replace that evidence.

- HYG-01: FIX_IMPLEMENTED (2026-10-25) — literal bidi controls in source and unhardened stdlib XML parsing of uploaded packages; see EXECUTION_LOG. Remaining B314 hits are in `tools/` scripts that read files this repo generates; low risk, not changed.
- AUD-P0 (2026-10-25): FIX_IMPLEMENTED for D1–D8, D15 and C3 from the owner's stack audit; see EXECUTION_LOG. OPEN: D9 optimistic concurrency on decisions, D10 heightened_review never read / no APPROVED state, D11 rule approvals accept superseded evidence, D12 UI form state leaks between observations, D13 audit-chain head anchor and UPDATE/DELETE triggers, D14 (=CAL-01), D16 receipt_audit wording, D17 assert-gated acceptance, D18 compose port on internal network, stale threat-model/boundary docs. OWNER DECISION: C1 DoA/unit extraction in public history, C2 public Drive links, C4 CLAUDE-CODE-HANDOFF.md real-case forensics, C5 real wordmark on synthetic outputs.
