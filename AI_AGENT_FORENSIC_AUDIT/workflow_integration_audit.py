#!/usr/bin/env python3
"""PHASE 12 — production workflow integration: are the agents operational components or disconnected demonstrations?"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_contracts import ENGINE, HERE, engine_run, load_cases

R = []


def rec(q, ans, detail):
    R.append({"question": q, "answer": ans, "evidence": str(detail)[:500]})


def main():
    g = json.loads((HERE / "reports" / "AGENT-RUNTIME-DEPENDENCY-GRAPH.json").read_text(encoding="utf-8"))
    cmds = {c["label"]: c for c in g["commands"]}
    rec("Does the production orchestrator (main.py) invoke Black Team when a workbook is built or issued?", "NO",
        f"round1/build-excel/build-word/finalize-titles traces: touches_challenge_engine = {[cmds[k]['touches_challenge_engine'] for k in ('01_round1','02_build-excel','03_build-word','08_finalize-titles-with-wording')]}")
    rec("Is there any production entry point that invokes the challenge?", "YES, as separate operator commands",
        "review / challenge / adjudicate call run_challenge → black_team → red_advocate → adjudicate (04/05/06 traces); nothing forces them before a build")
    rec("Is that invocation a real model call?", "NO", "zero socket attempts in every trace; no provider SDK in any tree")
    rec("Does Red Advocate receive the actual Black Team output?", "YES (in-process object)", "_argue passes the Objection built by black_team; context_isolation probe")
    rec("Does the adjudicator receive both arguments?", "YES (in-process objects)", "adjudicate(objection, advocacy, registry)")
    rec("Does the adjudicator evaluate evidence independently?", "PARTIAL", "rule table _TABLE[kind][stance] + admissibility/verified checks; no independent reading of the arguments' content")
    # can a valid objection change the final observation? run review on DA-01 (REVISE) then build the workbook and compare the comment
    from cdf_gco_crms.references.index import ReferenceIndex
    idx = ReferenceIndex.load()
    cases = {c["case_id"]: c for c in load_cases()}
    r, e, reg, _ = engine_run(cases["DA-01"], idx)
    revised = [o.advocacy.get("revised_comment") for o in e.objections if o.advocacy.get("revised_comment")]
    work = HERE / "evidence" / "runtime_callgraphs" / "work"
    from cdf_gco_crms.ingestion.workbook_reader import parse_workbook
    from cdf_gco_crms.model.entities import plain_text
    wb_out = next((work / "out_excel").glob("*.xlsx"))
    built_comment = plain_text(parse_workbook(wb_out).state.observations[0].comment)
    rec("Can a valid objection change the final observation?", "NO (automatically)",
        f"advocate produced a revised comment ({bool(revised)}); build-excel after review wrote the ORIGINAL comment unchanged "
        f"(workbook comment == JSON input: {built_comment.startswith('تُسند المادة')}). The revision lives only in the challenge record; a human must re-enter it.")
    rec("Does the change reach the official observation register?", "NO", "no code path applies Advocacy.revised_comment / revised_quote / route_to to ReviewState")
    rec("Does the final observation reach Word comments and Excel?", "YES for the human-entered observation", "round1 → build_workbook; build-word → comment_document (traces 01/03)")
    rec("Are approved titles synchronized?", "PARTIAL", "finalize-titles writes title/status/evidence to the helper sheet (08 trace rc=0); Word comments carry no title by protocol; "
                                                     "round1 JSON 'title' is dropped by cmd_round1 (07 trace refused)")
    rec("Does the workflow block issuance when required evidence is missing?", "NO", "build-excel/build-word ran with rc=0 on the same case whose review returned rc=1 (blocker) — "
                                                                                   "only tests/test_e2e.py::_issue and the operator's discipline chain review before build")
    rec("Independent Final Red-Team Reviewer (Art. 20) invoked anywhere?", "NO", "no component; see AI-IMPLEMENTATION-INVENTORY")
    comps = [("black_team / red_advocate / adjudicate", "CONNECTED_TO_OPERATOR_COMMANDS_ONLY", "reachable via review/challenge/adjudicate; not on round1/append/build paths"),
             ("apply_human_decisions", "CONNECTED_TO_OPERATOR_COMMAND_ONLY", "adjudicate command"),
             ("confidentiality_scan", "CONNECTED (challenge command, test_e2e, build_rc)", ""),
             ("evaluate_held_out / held_out_cases", "DISCONNECTED_COMPONENT (evaluation only)", "called by tests and tools/build_rc.py, never by a review"),
             ("production_guard.evaluate", "CONNECTED (release command)", ""),
             ("Advocacy.revised_comment → ReviewState", "NOT_IMPLEMENTED", "no consumer"),
             ("Article 20 independent reviewer", "NOT_IMPLEMENTED", "")]
    out = {"schema": "CDF-AUDIT-WORKFLOW-INTEGRATION-1", "runtime_questions": R, "component_status": [{"component": a, "status": b, "note": c} for a, b, c in comps],
           "integration_success_rate": {"entry_points_that_run_the_challenge_before_issuing": "0 of 4 (round1, append, build-excel, build-word)",
                                        "operator_commands_that_run_it": "3 (review, challenge, adjudicate)"}}
    (HERE / "evidence" / "workflow_integration_audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for x in R:
        print(f"{x['answer']:28} {x['question']}")


if __name__ == "__main__":
    main()
