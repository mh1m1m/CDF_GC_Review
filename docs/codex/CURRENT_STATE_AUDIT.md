# Current-state audit

Snapshot: 2026-10-24; source 837168c292161e7744e99258879e8653cfea0545. PR state is recorded in CODEX_HANDOFF.md. Findings and reproductions: INITIAL_AUDIT_FINDINGS.md. Test outcomes: TEST_EVIDENCE_REGISTER.md. Classifications below refer to the baseline and never imply institutional readiness.

| Capability | Classification | Source of truth | Evidence / limitation / next action |
|---|---|---|---|
| Multi-role orchestration | VERIFIED_IMPLEMENTED | cdf_gco_crms/agents/orchestrator.py, debate.py, roles.py | Synthetic unit/integration tests; preserve role isolation |
| Actual provider inference | BLOCKED_EXTERNAL | cdf_gco_crms/agents/providers/, provenance.py | No live run verified; requires authorized provider configuration and execution receipts |
| MAT-01/02/03 | VERIFIED_IMPLEMENTED | cdf_gco_crms/agents/mat_advisor.py | Synthetic advisor tests; professional fidelity not validated independently |
| Human-approved MAT DNA | BLOCKED_EXTERNAL | cdf_gco_crms/agents/mat_profile.py | Profile loader exists; no human-approved institutional profile supplied |
| Calibration persistence/API/UI | PARTIALLY_IMPLEMENTED | cdf_gco_crms/calibration/, apps/api/main.py, apps/web/src/main.tsx | Baseline CI browser success; four audit fixes included in takeover; versioned amendment workflow remains |
| Release authorization | PARTIALLY_IMPLEMENTED | cdf_gco_crms/release/, assurance/objection_engine.py | Negative regressions and synthetic attestations; key expiry and exact proposal binding required remediation |
| Offline DOCX/XLSX intake | VERIFIED_IMPLEMENTED | calibration/importer.py, excel_importer.py, input_safety.py | Synthetic importer tests; real institutional fidelity not exercised |
| Word/Excel output | PARTIALLY_IMPLEMENTED | cdf_gco_crms/word/, excel/, qa/lo_engine.py | Synthetic round trips; local LibreOffice recalculation timed out, not a pass |
| Local authentication | VERIFIED_IMPLEMENTED | apps/api/main.py, calibration/service.py | Loopback bearer token and case grants; pilot only |
| Institutional identity/security | NOT_IMPLEMENTED | docs/MAT-HUMAN-CALIBRATION-ACCEPTANCE.md | No SSO/managed entitlements; external design/approval needed |
| Public-file guard | VERIFIED_IMPLEMENTED | tools/mat_dna/public_repository_guard.py | Heuristic tracked-file scan passes; not full history/DLP certification |
| Institutional production release | BLOCKED_EXTERNAL | release gate and external acceptance | NOT_AUTHORIZED / NOT_READY; no deployment or official release performed |
