#!/usr/bin/env python3
"""PHASE 04 — live inference verification. Product: zero model invocations (socket guard + static inventory).
Audit harness: every live record validated and listed with provenance. Writes reports/LIVE-INFERENCE-VERIFICATION.json."""
from __future__ import annotations

import json
from pathlib import Path

from agent_contracts import HERE, RECORDS, validate_record

g = json.loads((HERE / "reports" / "AGENT-RUNTIME-DEPENDENCY-GRAPH.json").read_text(encoding="utf-8"))
inv = json.loads((HERE / "reports" / "AI-PROVIDER-INTEGRATION-INVENTORY.json").read_text(encoding="utf-8"))
product = {"LIVE_INFERENCE_STATUS": "NOT_VERIFIED — no provider is configured or integrated; nothing to execute",
           "observed_live_calls": 0, "socket_attempts_during_all_traced_commands": sum(len(c["socket_attempts"]) for c in g["commands"]),
           "commands_traced": [c["label"] for c in g["commands"]], "static_inventory_conclusion": inv["conclusion"],
           "provider_strings_are_vocabulary": True,
           "origin_of_every_product_output": "DETERMINISTIC_FIXTURE (rule tables in cdf_gco_crms/assurance; hash-chained records)"}
live = []
for f in sorted(RECORDS.glob("live_*.json")):
    r = json.loads(f.read_text(encoding="utf-8"))
    live.append({k: r[k] for k in ("Case_ID", "Agent_Role", "Execution_ID", "Context_ID", "Invocation_ID", "Timestamp", "Prompt_Hash", "Response_Hash",
                                   "Token_Usage", "Latency", "Execution_Status", "Origin", "Provider", "Model")} | {"schema_problems": validate_record(r),
                 "evidence_ids_resolve": r.get("Evidence_References_All_Resolve")})
out = {"schema": "CDF-AUDIT-LIVE-INFERENCE-1", "product": product,
       "audit_harness": {"origin": "CLAUDE_CODE_AGENT_RUNTIME_AUDIT_HARNESS", "records": len(live),
                         "distinct_contexts": len({r["Context_ID"] for r in live}), "distinct_executions": len({r["Execution_ID"] for r in live}),
                         "how_verified": "each run is a separate Claude Code subagent task (fresh context, no conversation history); the harness recorded the task "
                                         "id digest, duration and token usage reported by the runtime, the prompt and response hashes; no vendor receipt or network "
                                         "trace is available to the auditor inside this sandbox, so the origin is the agent runtime's own accounting",
                         "limitations": ["tool access of the subagents was instructed, not technically restricted", "token usage includes the runtime's system overhead",
                                         "one run per case; no repetition", "these runs are not part of the product and prove feasibility only"],
                         "runs": live},
       "verdict": "The product performs NO live inference. Live, context-isolated inference is feasible in the deployment runtime (audit harness) but is not integrated."}
(HERE / "reports" / "LIVE-INFERENCE-VERIFICATION.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({"product_live_calls": product["observed_live_calls"], "harness_records": len(live), "distinct_contexts": out["audit_harness"]["distinct_contexts"]}))
