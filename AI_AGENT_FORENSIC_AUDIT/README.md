# AI_AGENT_FORENSIC_AUDIT — CDF–GCO–CRMS v7.12

Independent, read-only forensic audit of the adversarial AI-agent claims. No production file was modified.

Reproduce (from this directory, Python 3.11+, the engine's requirements-lock.txt):

    python synthetic_case_generator.py      # 34 SYNTHETIC cases + sealed key (hash in cases/sealed_expected_results/EXPECTED.sha256)
    python source_inventory.py              # provider / implementation inventories
    python runtime_callgraph.py             # instrumented traces of main.py commands with a socket guard
    python context_isolation_audit.py       # execution-identity and hidden-label probe
    python blind_evaluation.py              # MODE A (engine) and MODE D (live records if present)
    python human_authority_audit.py         # 14 bypass attempts
    python security_negative_tests.py       # injection, tool authorization, failure injection
    python debate_audit.py                  # six-cycle and dynamic-behaviour tests
    python workflow_integration_audit.py    # production-path integration
    python provider_trace_audit.py          # live-inference verification
    python release_assessment.py            # maturity matrix, 40 controls, backlog, verdict, reports

Live MODE C/D runs (evidence/agent_execution_records/live_*.json) were executed by the auditor through fresh Claude Code
subagents, one per (case, role), from the prompt files in evidence/live_prompts/; they are labelled
CLAUDE_CODE_AGENT_RUNTIME_AUDIT_HARNESS and are NOT product behaviour. record_live.py turns each reply into an
execution record and builds the next role's prompt.

Reports: reports/ (nine deliverables of §20 plus CONTROL-MATRIX.json and the runtime dependency graph).

## Note on the engineering patch register

PATCH-STATUS.json (built before this audit) marks V712-039, 040, 044 and 035 as PASS on the strength of unit tests and
the end-to-end test helper. This audit's execution evidence contradicts the operational reading of those entries:
AI-035 FAIL (no issuing command runs the challenge), AI-031/032 FAIL (advocate outputs never reach the register), and
the roles are L2 simulations. The register was not edited by the audit (audit-only boundary); the remediation backlog
R-01..R-04 is the engineering answer.
