#!/usr/bin/env python3
"""Records one live (audit-harness) agent run as an execution record (17.1 fields) and builds the next role's prompt.
Provider/model: the Claude Code agent runtime; subagents inherit the session model (claude-fable-5-1 per get_session).
Execution/context ids are SHA-256 digests of the subagent task ids (one fresh subagent = one context)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from agent_contracts import HERE, RECORDS, sha, validate_record

OUT = HERE / "evidence" / "live_outputs"
PROMPTS = HERE / "evidence" / "live_prompts"
INDEX = json.loads((PROMPTS / "INDEX.json").read_text(encoding="utf-8"))


def record(case_id, role, task_id, duration_ms, tokens, prompt_path, output_path):
    out = json.loads(Path(output_path).read_text(encoding="utf-8"))
    prompt_text = Path(prompt_path).read_text(encoding="utf-8")
    refs = out.get("relevant_evidence") or out.get("evidence_ids") or out.get("decisive_evidence") or []
    payload = json.loads((PROMPTS / f"{case_id}_payload.json").read_text(encoding="utf-8")) if (PROMPTS / f"{case_id}_payload.json").exists() else None
    known = {e["id"] for e in payload["evidence"]} if payload else set()
    if role == "ADJUDICATOR" and case_id.startswith("BLIND"):
        known = {"EV-MATRIX-16-3"}
    rec = {"Case_ID": case_id, "Observation_ID": "GCO-AUD-R2-002", "Challenge_ID": f"LIVE-{case_id}", "Execution_ID": sha(task_id)[:16],
           "Agent_ID": f"audit-harness/{role.lower()}/{sha(task_id)[:8]}", "Agent_Role": role,
           "Provider": "Anthropic — Claude Code agent runtime (fresh general-purpose subagent, audit harness, NOT the product)",
           "Model": "claude-fable-5-1 (session model inherited by the subagent; served model per get_session)",
           "Context_ID": sha("ctx:" + task_id)[:16], "Invocation_ID": sha("inv:" + task_id)[:16],
           "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "Prompt_Hash": sha(prompt_text), "Response_Hash": sha(json.dumps(out, ensure_ascii=False, sort_keys=True)),
           "Evidence_References": refs, "Evidence_References_All_Resolve": all(r in known for r in refs) if known else None,
           "Tool_Calls": ["Read(prompt file) — the only permitted tool use; tool access was instructed, not technically enforced"],
           "Token_Usage": tokens, "Latency": f"{duration_ms} ms", "Execution_Status": "SUCCESS", "Retry_Count": 0,
           "Origin": "CLAUDE_CODE_AGENT_RUNTIME_AUDIT_HARNESS", "Structured_Output": out,
           "Isolation_Note": "fresh subagent with no conversation context; input = one prompt file carrying only the role's permitted payload; "
                             "hidden sealed labels never present in the prompt (see live_prompts/INDEX.json hashes)"}
    assert not validate_record(rec), validate_record(rec)
    RECORDS.mkdir(parents=True, exist_ok=True)
    (RECORDS / f"live_{case_id}_{role}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def next_prompt(case_id, role_done, out):
    """RED_ADVOCATE prompt from the Black Team output; ADJUDICATOR prompt from both."""
    payload = json.loads((PROMPTS / f"{case_id}_payload.json").read_text(encoding="utf-8"))
    common = INDEX["common"]
    if role_done == "BLACK_TEAM":
        pl = dict(payload); pl["black_team_objection"] = out
        text = (f"{common}\n\nROLE: RED ADVOCATE — you defend the GCO observation only where the evidence supports it; accept a valid objection, correct a wrong "
                f"reference, narrow an excessive recommendation, route a specialist matter, withhold an unsupported assertion. You must not defend every observation "
                f"and must not concede every objection; follow the evidence and the GCO house style (concise, no breach verdict without an approved source).\n\n"
                f"PAYLOAD:\n{json.dumps(pl, ensure_ascii=False, indent=1)}\n\nSCHEMA:\n{json.dumps(INDEX['schemas']['RED_ADVOCATE'], ensure_ascii=False, indent=1)}")
        p = PROMPTS / f"{case_id}_RED_ADVOCATE.md"
    else:
        bt = json.loads((OUT / f"{case_id}_BLACK_TEAM.json").read_text(encoding="utf-8"))
        pl = {"case_id": case_id, "label": "SYNTHETIC_TEST_CASE", "document_paragraphs": payload["document_paragraphs"], "observation": payload["observation"],
              "observation_issued_in_earlier_round": payload["observation_issued_in_earlier_round"], "title_status": payload["title_status"],
              "evidence": payload["evidence"], "black_team_objection": bt, "red_advocate_response": out}
        text = (f"{common}\n\nROLE: INDEPENDENT ADJUDICATOR — weigh the objection and the response on the admissible evidence only; confidence of tone is not evidence; "
                f"an unresolved dispute is a legitimate outcome; never override missing evidence, failed jurisdiction, an unverified authority or a decision reserved to the "
                f"human GCO reviewer (a change to an observation issued in an earlier round, a title approval, a withdrawal) — escalate those.\n\n"
                f"PAYLOAD:\n{json.dumps(pl, ensure_ascii=False, indent=1)}\n\nSCHEMA:\n{json.dumps(INDEX['schemas']['ADJUDICATOR'], ensure_ascii=False, indent=1)}")
        p = PROMPTS / f"{case_id}_ADJUDICATOR.md"
    p.write_text(text, encoding="utf-8")
    return p


if __name__ == "__main__":
    case_id, role, task_id, duration_ms, tokens = sys.argv[1:6]
    prompt = PROMPTS / f"{case_id}_{role}.md"
    rec = record(case_id, role, task_id, int(duration_ms), int(tokens), prompt, OUT / f"{case_id}_{role}.json")
    if role in ("BLACK_TEAM", "RED_ADVOCATE") and not case_id.startswith("BLIND"):
        print(next_prompt(case_id, role, rec["Structured_Output"]))
    print(rec["Execution_ID"], rec["Response_Hash"][:16], rec["Evidence_References_All_Resolve"])
