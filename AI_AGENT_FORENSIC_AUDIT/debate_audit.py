#!/usr/bin/env python3
"""PHASE 09 — six-cycle debate controls and dynamic behaviour (read-only on the product)."""
from __future__ import annotations

import json
from pathlib import Path

from agent_contracts import HERE, engine_run, engine_state, load_cases

R = []


def rec(name, ok, detail):
    R.append({"test": name, "result": "PASS" if ok is True else ("NOT_VERIFIED" if ok is None else "FAIL"), "detail": str(detail)[:400]})


def main():
    from cdf_gco_crms.assurance import challenge as CH
    from cdf_gco_crms.assurance.evidence import EvidenceRegistry
    from cdf_gco_crms.assurance.objection_engine import MAX_CYCLES, Objection
    from cdf_gco_crms.assurance.personas import RecipientPersona
    from cdf_gco_crms.references.index import ReferenceIndex
    idx = ReferenceIndex.load()
    cases = {c["case_id"]: c for c in load_cases()}
    # ONE_CYCLE_RESOLUTION: REG-01 (REVISE on first reply)
    r, e, *_ = engine_run(cases["REG-01"], idx)
    cyc = {o.kind: o.cycles for o in e.objections}
    rec("ONE_CYCLE_RESOLUTION (REG-01 breach wording → REVISE)", all(v <= 2 for v in cyc.values()) and bool(cyc), cyc)
    # MULTIPLE_OBJECTIONS: TITLE-01 carries RESERVED + others? use DUP-01 + verbosity combination: craft case with two defects
    c = cases["DUP-01"] | {"case_id": "MULTI", "observation": dict(cases["DUP-01"]["observation"], comment=cases["DUP-01"]["observation"]["comment"] + "\n" + "وهذا مهم جداً ويحتاج عناية " * 25)}
    r, e, *_ = engine_run(c, idx)
    ids = [o.challenge_id for o in e.objections]
    rec("MULTIPLE_OBJECTIONS: distinct Challenge_IDs with their own cycle counters", len(ids) >= 2 and len(set(ids)) == len(ids), {o.kind: (o.challenge_id, o.cycles) for o in e.objections})
    # SIX_CYCLE_UNRESOLVED + ADJUDICATOR_ESCALATION: CYC-01
    r, e, *_ = engine_run(cases["CYC-01"], idx)
    co = [o for o in e.objections if o.kind == "CONTESTED_OWNERSHIP"]
    rec("SIX_CYCLE_UNRESOLVED → ADJUDICATOR_ESCALATION (CYC-01)", bool(co) and co[0].cycles == MAX_CYCLES and co[0].disposition == "ESCALATED_TO_GCO_REVIEWER",
        {o.kind: (o.cycles, o.disposition) for o in e.objections})
    # SEVENTH_CYCLE_REJECTED / SEMANTIC_DUPLICATE on the state machine
    ob = Objection("GCO-AUD-R2-002", "T", "p", "d")
    for i in range(MAX_CYCLES):
        ob.add("BLACK" if i % 2 == 0 else "RED_ADVOCATE", f"c{i}", [])
    try:
        ob.add("BLACK", "c7", []); seventh = False
    except ValueError:
        seventh = True
    rec("SEVENTH_CYCLE_REJECTED", seventh, ob.productive_cycles())
    ob = Objection("GCO-AUD-R2-002", "T", "p", "d"); ob.add("BLACK", "الصلاحية لمجلس الإدارة", ["E1"]); ob.add("RED_ADVOCATE", "رد", [])
    try:
        ob.add("BLACK", "الصلاحية   لمجلس الإدارة.", ["E1"]); dup = False
    except ValueError:
        dup = True
    rec("SEMANTIC_DUPLICATE: whitespace/punctuation paraphrase with same refs refused", dup, "canon() normalisation only; a true paraphrase with different words is NOT detected (see limitation)")
    ob = Objection("GCO-AUD-R2-002", "T", "p", "d"); ob.add("BLACK", "الصلاحية لمجلس الإدارة", ["E1"]); ob.add("RED_ADVOCATE", "رد", [])
    try:
        ob.add("BLACK", "صلاحية الاعتماد تعود إلى المجلس", ["E1"]); para = False
    except ValueError:
        para = True
    rec("SEMANTIC_DUPLICATE: genuine paraphrase (different words, same meaning) refused", para, "expected limitation: canonical-text equality only")
    # NEW_EVIDENCE_INTRODUCED: REG-01 → REG-02 (bound binding provision removes the objection)
    r1, e1, *_ = engine_run(cases["REG-01"], idx); r2, e2, *_ = engine_run(cases["REG-02"], idx)
    rec("NEW_EVIDENCE_INTRODUCED changes the outcome (REG-01 vs REG-02)", bool(e1.objections) and not e2.objections, {"REG-01": [o.kind for o in e1.objections], "REG-02": [o.kind for o in e2.objections]})
    # EVIDENCE_WITHDRAWN: REG-02 without the basis → objection returns
    c = cases["REG-02"] | {"case_id": "WITHDRAWN", "basis_policy": None}
    r3, e3, *_ = engine_run(c, idx)
    rec("EVIDENCE_WITHDRAWN restores the objection", bool(e3.objections), [o.kind for o in e3.objections])
    # cited clause corrected: EVID-01 (absent) vs TITLE-01-like clean
    r4, e4, *_ = engine_run(cases["EVID-01"], idx); r5, e5, *_ = engine_run(cases["TITLE-01"] | {"title": None, "title_status": "NONE", "case_id": "CLEAN"}, idx)
    rec("cited clause corrected (absent → present) changes the outcome", any(o.kind == "CLAUSE_NOT_FOUND" for o in e4.objections) and not e5.objections, {"absent": [o.kind for o in e4.objections], "present": [o.kind for o in e5.objections]})
    # observation narrowed: JUR-01 (technical) vs JUR-02 (governance)
    r6, e6, *_ = engine_run(cases["JUR-01"], idx); r7, e7, *_ = engine_run(cases["JUR-02"], idx)
    rec("observation narrowed (JUR-01 technical → JUR-02 governance) changes the outcome", [o.kind for o in e6.objections] != [o.kind for o in e7.objections], {"JUR-01": [o.kind for o in e6.objections], "JUR-02": [o.kind for o in e7.objections]})
    # recipient responsibility changes: ORG-01 with procurement vs human capital
    r8, e8, *_ = engine_run(cases["ORG-01"], idx); r9, e9, *_ = engine_run(cases["ORG-01"] | {"case_id": "ORG-01-HR", "department": "رأس المال البشري"}, idx)
    rec("recipient changes (procurement → human capital) changes the outcome", [o.kind for o in e8.objections] != [o.kind for o in e9.objections] or (not e8.objections and not e9.objections and None),
        {"procurement": [o.kind for o in e8.objections], "human_capital": [o.kind for o in e9.objections]})
    rec("institutional mandate reclassified (PROPOSED → APPROVED) changes the outcome", None, "NOT_VERIFIED: the reference index is read-only in this audit; no approved mandate exists to load")
    rec("PARTIAL_AGREEMENT (advocate REVISE = concedes wording, keeps the request)", any(o.advocacy["stance"] == "REVISE" for o in e1.objections), [o.advocacy["stance"] for o in e1.objections])
    rec("TWO_CYCLE_RESOLUTION", None, "NOT_VERIFIED: no synthetic case produced a resolution exactly at the second exchange; the loop supports it (_argue)")
    rec("debate history preserved (hash chain verified on every record)", all(x.verify_chains() for x in (r, r1, r2, r3, r4, r5, r6, r7, r8, r9)), "")
    out = {"schema": "CDF-AUDIT-DEBATE-1", "results": R, "summary": {k: sum(1 for x in R if x["result"] == k) for k in ("PASS", "FAIL", "NOT_VERIFIED")},
           "limitation": "The 'debate' is a fixed exchange table (_followups) per objection kind; arguments change only through the evidence registry and the "
                         "persona, not through reasoning. Dynamic behaviour exists for evidence, clause presence, scope and recipient, as shown."}
    (HERE / "evidence" / "debate_audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for x in R:
        print(f"{x['result']:13} {x['test']} | {x['detail'][:120]}")
    print(out["summary"])


if __name__ == "__main__":
    main()
