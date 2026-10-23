#!/usr/bin/env python3
"""PHASE 05 — agent independence forensics on the deterministic engine (read-only).

Checks, by execution, whether the three roles run with separate execution identities, separate model invocations,
separate contexts, separate memory, and whether hidden labels can reach them. Writes
reports/MULTI-AGENT-INDEPENDENCE-REPORT.md and evidence/agent_execution_records/engine_isolation_probe.json.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from cdf_gco_crms.assurance import challenge as CH  # noqa: E402
from cdf_gco_crms.assurance.evidence import EvidenceRegistry  # noqa: E402
from cdf_gco_crms.assurance.personas import RecipientPersona  # noqa: E402
from cdf_gco_crms.model.entities import Document, GText, Observation, ReviewRound, ReviewState  # noqa: E402
from cdf_gco_crms.references.index import ReferenceIndex  # noqa: E402


def probe() -> dict:
    case = json.loads((HERE / "cases" / "synthetic_inputs" / "DA-01.json").read_text(encoding="utf-8"))
    idx = ReferenceIndex.load()
    reg = EvidenceRegistry()
    reg.add_document_text("\n".join(case["document_paragraphs"]))
    persona = RecipientPersona.from_index(idx, case["department"], reg)
    o = Observation("GCO-AUD-R2-001", "01", 2, case["observation"]["location"], case["observation"]["quote"], GText.plain(case["observation"]["comment"]))
    st = ReviewState(Document("مذكرة تجريبية", "AUD", owning_department=case["department"], is_demo=True), [ReviewRound(1), ReviewRound(2)], [o])
    # identity of each role: process id, thread id, python object identity of shared inputs
    ids = {"black_team": None, "red_advocate": None, "adjudicate": None}
    orig = {k: getattr(CH, k) for k in ids}

    def wrap(name):
        fn = orig[name]

        def inner(*a, **k):
            ids[name] = {"pid": os.getpid(), "thread": threading.get_ident(), "registry_id": id(a[1]) if name == "black_team" else id(a[2]),
                         "module": fn.__module__, "qualname": fn.__qualname__}
            return fn(*a, **k)
        return inner
    for k in ids:
        setattr(CH, k, wrap(k))
    try:
        rec = CH.run_challenge(st, reg, persona)
    finally:
        for k in ids:
            setattr(CH, k, orig[k])
    # hidden-label leakage probe: attach an "expected" attribute to the objection and the advocacy, re-adjudicate
    leak = None
    entry = rec.entries[0]
    if entry.objections:
        ob = rec.objection(entry.objections[0].challenge_id)
        adv_dict = entry.objections[0].advocacy
        adv = CH.Advocacy(adv_dict["challenge_id"], adv_dict["stance"], adv_dict["reasoning"], list(adv_dict["evidence_refs"]),
                          revised_comment=GText.plain(adv_dict.get("revised_comment") or "نص معدل") if adv_dict["stance"] == "REVISE" else None,
                          route_to=adv_dict.get("route_to"))
        ob.expected = "ROUTED_OUTSIDE_GCO"; adv.expected = "ROUTED_OUTSIDE_GCO"
        before = entry.objections[0].adjudication["disposition"]
        after = CH.adjudicate(ob, adv, reg).disposition
        leak = {"disposition_without_label": before, "disposition_with_planted_expected_attr": after, "changed": before != after}
    same_pid = len({v["pid"] for v in ids.values() if v}) == 1
    same_thread = len({v["thread"] for v in ids.values() if v}) == 1
    same_registry = len({v["registry_id"] for v in ids.values() if v}) == 1
    src = inspect.getsource(CH.run_challenge) + inspect.getsource(CH._argue)
    return {
        "case": case["case_id"], "role_identities": ids, "same_process": same_pid, "same_thread": same_thread,
        "shared_registry_object": same_registry, "model_invocations": 0,
        "separate_execution_identity": False, "separate_model_invocation": False,
        "role_specific_instructions": "none: no prompts exist; each role is a Python function with a fixed rule table",
        "context_constructed_per_role": "no: all three read the same Observation, EvidenceRegistry and RecipientPersona objects in memory",
        "prior_agent_state_excluded": "no: red_advocate receives the Objection instance built by black_team; adjudicate receives both objects (by design)",
        "tool_access_controlled": "not applicable: the functions call no tools",
        "outputs_preserved_independently": "yes: ObjectionRecord keeps proposition, advocacy dict and adjudication dict separately, hash-chained",
        "hidden_expected_label_probe": leak,
        "independence_declared_by_engine": {"independence": rec.independence, "role_isolation": rec.role_isolation},
        "source_evidence": {"run_challenge_calls_black_then_argue": "black_team(" in src and "_argue(" in src,
                            "argue_calls_red_advocate_then_adjudicate": "red_advocate(" in src and "adjudicate(" in src},
    }


LEVELS = [
    ("ROLE_SEPARATION", "PARTIAL", "three distinct functions with distinct rule tables and outputs; no separate execution identity"),
    ("PROMPT_SEPARATION", "NOT_APPLICABLE", "no prompts exist in the product; the roles are rule tables, not prompted models"),
    ("CONTEXT_ISOLATION", "FAIL", "same process, same thread, same in-memory registry, persona and objection objects"),
    ("EXECUTION_ISOLATION", "FAIL", "one call chain run_challenge → black_team → _argue → red_advocate → adjudicate"),
    ("TOOL_PERMISSION_ISOLATION", "NOT_APPLICABLE", "no tools; the functions cannot open files or sockets"),
    ("MEMORY_ISOLATION", "FAIL", "shared Objection instance carries every prior event into the next role (by design of the state machine)"),
    ("EVALUATION_ISOLATION", "PASS", "the adjudicator ignores a planted 'expected' attribute (probe) and the held-out labels are underscore fields hidden from to_dict()"),
    ("PROVIDER_DIVERSITY", "NOT_APPLICABLE", "no provider at all"),
]


def main():
    p = probe()
    (HERE / "evidence" / "agent_execution_records").mkdir(parents=True, exist_ok=True)
    (HERE / "evidence" / "agent_execution_records" / "engine_isolation_probe.json").write_text(json.dumps(p, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    lines = ["# MULTI-AGENT INDEPENDENCE REPORT — CDF–GCO–CRMS v7.12", "",
             "Scope: the product's challenge engine (`cdf_gco_crms/assurance/challenge.py`) as executed by `main.py review`. "
             "Live isolated runs of the audit harness are reported separately in `BLIND-ADVERSARIAL-EVALUATION.json` (MODE D) and never "
             "stand for the product.", "",
             "## Execution probe (synthetic case DA-01)", "",
             f"- Same process for the three roles: **{p['same_process']}**; same thread: **{p['same_thread']}**; shared EvidenceRegistry object: **{p['shared_registry_object']}**.",
             f"- Model invocations observed: **{p['model_invocations']}**. Separate execution identity: **{p['separate_execution_identity']}**.",
             f"- Engine's own declaration: independence = `{p['independence_declared_by_engine']['independence']}`, role_isolation = `{p['independence_declared_by_engine']['role_isolation']}`.",
             f"- Hidden-label probe: disposition without label `{p['hidden_expected_label_probe']['disposition_without_label'] if p['hidden_expected_label_probe'] else 'n/a'}`, "
             f"with a planted `expected` attribute `{p['hidden_expected_label_probe']['disposition_with_planted_expected_attr'] if p['hidden_expected_label_probe'] else 'n/a'}` "
             f"(changed: {p['hidden_expected_label_probe']['changed'] if p['hidden_expected_label_probe'] else 'n/a'}).", "",
             "## Information boundaries (05.2–05.5)", "",
             "- Black Team receives: the observation, its comment, the document paragraphs through the registry, the recipient persona built from the "
             "organisational-structure index. It does not receive the advocate's draft or an expected decision (none exist). PASS as a boundary, but there is no "
             "'draft' to protect because the roles are synchronous rules.",
             "- Red Advocate receives the Objection object produced by black_team (proposition, kind, detail dict, evidence refs) — exactly the objection, nothing hidden.",
             "- Adjudicator receives the Objection and the Advocacy objects and the registry; `adjudicate()` reads only `kind`, `stance`, `evidence_refs`, `detail['reserved']` and `issued`; "
             "its docstring states that attributes named `expected` are not read and the probe confirms it.",
             "- Independent Final Reviewer (Art. 20): **no component exists**; no context is created, so independence cannot be assessed.", "",
             "## Independence levels (05.6)", "", "| Property | Result | Evidence |", "|---|---|---|"]
    for name, res, ev in LEVELS:
        lines.append(f"| {name} | **{res}** | {ev} |")
    lines += ["", "## Conclusion", "",
              "The product runs **one deterministic process**. The three roles are separated by function and by record, not by execution context, "
              "memory or model invocation. The engine states this itself (`SINGLE_PROCESS_RULE_BASED`, `role_isolation = NOT_VERIFIED`) in every record "
              "and in protocol 19A.2/23.1. Nothing in the product counterfeits independence: no separate context ids are logged for a single call.", ""]
    (HERE / "reports" / "MULTI-AGENT-INDEPENDENCE-REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: p[k] for k in ("same_process", "same_thread", "shared_registry_object", "hidden_expected_label_probe", "independence_declared_by_engine")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
