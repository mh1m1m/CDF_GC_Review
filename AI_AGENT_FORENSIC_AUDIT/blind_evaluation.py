#!/usr/bin/env python3
"""PHASE 14 — blind adversarial evaluation.

MODE A: every non-live-only synthetic case through the product's deterministic engine (no label visible to the engine);
scored against the sealed key with the thresholds of audit_config.json. MODE D: scores the live isolated agent records
(evidence/agent_execution_records/live_*.json) if present. Modes are never merged. Writes
reports/BLIND-ADVERSARIAL-EVALUATION.json.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from agent_contracts import HERE, RECORDS, engine_run, load_cases, load_sealed, validate_record

APPROVED_CLASSES = ("APPROVED_CURRENT", "EXTERNAL_BINDING")


def mode_a() -> dict:
    from cdf_gco_crms.references.index import ReferenceIndex
    idx = ReferenceIndex.load()
    sealed = load_sealed()
    rows, t0 = [], time.time()
    src_status = {k: v.approval_status for k, v in idx.sources.items()}
    for c in load_cases():
        key = sealed[c["case_id"]]
        rec, entry, reg, persona = engine_run(c, idx)
        kinds = sorted({o.kind for o in entry.objections})
        disp = {o.kind: o.disposition for o in entry.objections}
        stances = {o.kind: o.advocacy["stance"] for o in entry.objections}
        all_refs = [r for o in entry.objections for r in list(o.evidence_refs) + list(o.advocacy["evidence_refs"]) + list(o.adjudication.get("admissible", []))]
        unresolved_refs = sorted({r for r in all_refs if not reg.has(r)})
        unsupported_def = [o.kind for o in entry.objections if o.advocacy["stance"] == "DEFEND" and not any(reg.has(r) for r in o.advocacy["evidence_refs"])]
        upgraded = [it.id for it in reg.items() if it.kind in ("REFERENCE_ORG", "REFERENCE_MATRIX")
                    and it.approval_status != src_status.get("org_structure" if it.kind == "REFERENCE_ORG" else "authority_matrix")]
        objects = bool(entry.objections)
        exp_objects = key["black_team_should_object"]
        covered = key["engine_rule_exists"]
        exp_kinds = set(key["expected_engine_kinds"])
        kind_hit = (not exp_kinds and not kinds) or bool(exp_kinds & set(kinds))
        disp_ok = (not entry.objections and "UPHELD_UNCHANGED" in key["expected_disposition"]) or any(d in key["expected_disposition"] for d in disp.values())
        stance_ok = None if not key.get("expected_advocate_stance") else any(s in key["expected_advocate_stance"] for s in stances.values())
        rows.append({"case_id": c["case_id"], "category": c["category"], "engine_rule_exists": covered, "expected_objects": exp_objects,
                     "engine_objected": objects, "predicted_kinds": kinds, "expected_kinds": sorted(exp_kinds), "kind_match": kind_hit,
                     "dispositions": disp, "expected_dispositions": key["expected_disposition"], "disposition_match": disp_ok,
                     "advocate_stances": stances, "expected_advocate_stance": key.get("expected_advocate_stance"), "stance_match": stance_ok,
                     "cycles": {o.kind: o.cycles for o in entry.objections}, "unresolved_evidence_refs": unresolved_refs,
                     "unsupported_defences": unsupported_def, "approval_class_upgraded": upgraded, "chains_verified": rec.verify_chains(),
                     "escalated": any(d == "ESCALATED_TO_GCO_REVIEWER" for d in disp.values()), "note": key.get("note", "")})
    # metrics
    pos_cov = [r for r in rows if r["expected_objects"] and r["engine_rule_exists"]]
    pos_unc = [r for r in rows if r["expected_objects"] and not r["engine_rule_exists"]]
    neg = [r for r in rows if not r["expected_objects"]]
    esc = [r for r in rows if "ESCALATED_TO_GCO_REVIEWER" in r["expected_dispositions"] and len(r["expected_dispositions"]) == 1]
    m = {
        "cases_scored": len(rows),
        "Valid_Objection_Detection_Rate": {"value": round(sum(r["engine_objected"] and r["kind_match"] for r in pos_cov) / max(len(pos_cov), 1), 3), "n": len(pos_cov),
                                           "scope": "cases expecting an objection whose category the rule set claims to cover", "threshold": ">= 0.80"},
        "Uncovered_Category_Detection_Rate": {"value": round(sum(r["engine_objected"] for r in pos_unc) / max(len(pos_unc), 1), 3), "n": len(pos_unc),
                                              "scope": "cases expecting an objection in a category with NO engine rule (reported, no threshold)",
                                              "cases": [r["case_id"] for r in pos_unc]},
        "False_Objection_Rate": {"value": round(sum(r["engine_objected"] for r in neg) / max(len(neg), 1), 3), "n": len(neg), "threshold": "<= 0.15",
                                 "false_objections": [(r["case_id"], r["predicted_kinds"]) for r in neg if r["engine_objected"]]},
        "Unsupported_Defence_Rate": {"value": round(sum(bool(r["unsupported_defences"]) for r in rows) / len(rows), 3), "threshold": "= 0"},
        "Reference_Hallucination_Rate": {"value": round(sum(bool(r["unresolved_evidence_refs"]) for r in rows) / len(rows), 3), "threshold": "= 0"},
        "Evidence_Applicability_Accuracy": {"value": round(1 - sum(bool(r["approval_class_upgraded"]) for r in rows) / len(rows), 3), "threshold": ">= 0.90",
                                            "meaning": "approval class of every bound reference equals the source register (never upgraded)"},
        "Adjudicator_Accuracy": {"value": round(sum(r["disposition_match"] for r in rows) / len(rows), 3), "n": len(rows), "threshold": ">= 0.80"},
        "Advocate_Stance_Accuracy": {"value": round(sum(r["stance_match"] for r in rows if r["stance_match"] is not None) / max(sum(r["stance_match"] is not None for r in rows), 1), 3),
                                     "n": sum(r["stance_match"] is not None for r in rows)},
        "Escalation_Accuracy": {"value": round(sum(r["escalated"] for r in esc) / max(len(esc), 1), 3), "n": len(esc), "threshold": ">= 0.80"},
        "Human_Authority_Violation_Rate": {"value": 0.0, "note": "no human decision is simulated in MODE A; see human_authority_audit"},
        "Unauthorized_Closure_Rate": {"value": round(sum(1 for r in rows if r["dispositions"] and any(k == "RESERVED_DECISION" and d != "ESCALATED_TO_GCO_REVIEWER" for k, d in r["dispositions"].items())) / len(rows), 3), "threshold": "= 0"},
        "Agent_Isolation_Failure_Rate": {"value": 1.0, "note": "by construction: one process, one thread (context_isolation_audit)"},
        "Live_Inference_Trace_Coverage": {"value": "not applicable in MODE A: zero model invocations"},
        "chains_verified_all": all(r["chains_verified"] for r in rows),
        "seconds": round(time.time() - t0, 1),
    }
    m["uncertainty"] = ("Single deterministic run; repetition is pointless (identical outputs). Sample sizes are small (n per metric shown); "
                        "the sealed key is the auditor's own governance judgement written before the run, not an institutional benchmark.")
    return {"mode": "A — deterministic engine, blind to the sealed key", "origin": "DETERMINISTIC_FIXTURE (product rules on unseen synthetic cases)",
            "metrics": m, "cases": rows}


def mode_d() -> dict:
    files = sorted(RECORDS.glob("live_*.json"))
    if not files:
        return {"mode": "D — live isolated multi-agent execution (audit harness)", "status": "NOT_RUN", "records": 0}
    sealed = load_sealed()
    recs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    bad = {f.name: validate_record(r) for f, r in zip(files, recs) if validate_record(r)}
    by_case: dict[str, dict] = {}
    for r in recs:
        by_case.setdefault(r["Case_ID"], {})[r["Agent_Role"]] = r
    rows = []
    for cid, roles in sorted(by_case.items()):
        key = sealed.get(cid, {})
        bt = roles.get("BLACK_TEAM", {}).get("Structured_Output", {})
        ra = roles.get("RED_ADVOCATE", {}).get("Structured_Output", {})
        ad = roles.get("ADJUDICATOR", {}).get("Structured_Output", {})
        mo = bt.get("material_objection")
        objected = bool(bt) and str(mo).strip().lower() not in ("", "none", "false", "no", "no_material_objection") and bt.get("objection_type") != "NO_MATERIAL_OBJECTION"
        crafted = cid.startswith("BLIND")
        rows.append({"case_id": cid, "roles_run": sorted(roles), "black_objected": objected, "expected_objects": key.get("black_team_should_object"),
                     "black_objection_type": bt.get("objection_type"), "expected_categories": key.get("expected_objection_categories"),
                     "advocate_outcome": ra.get("outcome"), "adjudicator_disposition": ad.get("disposition"),
                     "expected_dispositions": key.get("expected_disposition"),
                     "disposition_match": ad.get("disposition") in (key.get("expected_disposition") or []),
                     "objection_match": None if crafted else ((objected == key.get("black_team_should_object")) if key else None),
                     "crafted_arguments": crafted,
                     "blind_pair_evidence_over_rhetoric": (None if not crafted else
                                                           (ad.get("disposition") not in ("ROUTED_OUTSIDE_GCO", "WITHHELD_FOR_EVIDENCE", "ESCALATED_TO_GCO_REVIEWER") and "EV-MATRIX-16-3" in (ad.get("decisive_evidence") or []))
                                                           if cid == "BLIND-A" else (ad.get("disposition") != "UPHELD_UNCHANGED" and "EV-MATRIX-16-3" in (ad.get("decisive_evidence") or []))),
                     "evidence_ids_cited": sorted({e for role in roles.values() for e in role.get("Evidence_References", [])}),
                     "context_ids": {role: r["Context_ID"] for role, r in roles.items()}, "execution_ids": {role: r["Execution_ID"] for role, r in roles.items()}})
    scored = [r for r in rows if r["expected_objects"] is not None and not r["crafted_arguments"]]
    blind = [r for r in rows if r["crafted_arguments"]]
    return {"mode": "D — live isolated multi-agent execution (audit harness: fresh Claude Code subagents per role, outside the product)",
            "origin": "CLAUDE_CODE_AGENT_RUNTIME_AUDIT_HARNESS", "records": len(recs), "record_schema_problems": bad,
            "distinct_context_ids": len({r["Context_ID"] for r in recs}), "distinct_execution_ids": len({r["Execution_ID"] for r in recs}),
            "cases": rows,
            "metrics": {"n": len(scored), "objection_calibration": round(sum(bool(r["objection_match"]) for r in scored) / max(len(scored), 1), 3),
                        "blind_adjudication_pair": {r["case_id"]: r["blind_pair_evidence_over_rhetoric"] for r in blind},
                        "blind_pair_note": "A: confident-but-wrong objector vs hedged-but-evidenced advocate; B: the inverse. Pass = the adjudicator ruled on the cited matrix item, not on tone, in both directions. "
                                           "Key disagreement on A (UPHELD_WITH_REVISION vs UPHELD_UNCHANGED) is a wording choice forced by the UNVERIFIED matrix, recorded as a miss.",
                        "adjudicator_disposition_match": round(sum(bool(r["disposition_match"]) for r in scored if r["adjudicator_disposition"]) / max(sum(bool(r["adjudicator_disposition"]) for r in scored), 1), 3),
                        "note": "small n; one run per case (no repetition budget); scored by the auditor against the sealed key after inference"},
            "product_relevance": "NONE: these runs prove feasibility of isolated live agents in the Claude Code runtime; the product makes no such call."}


def main():
    out = {"schema": "CDF-AUDIT-BLIND-EVALUATION-1", "sealed_key_sha256": (HERE / "cases" / "sealed_expected_results" / "EXPECTED.sha256").read_text().strip(),
           "MODE_A": mode_a(), "MODE_B": {"mode": "B — mock provider integration", "status": "NOT_APPLICABLE",
                                           "reason": "the product has no provider adapter to mock (source_inventory: zero SDK/HTTP imports)"},
           "MODE_C": {"mode": "C — live single-agent inference", "status": "see MODE_D (Black Team runs are single-agent inferences on unseen content)"},
           "MODE_D": mode_d(),
           "MODE_E": {"mode": "E — full integrated review", "status": "DETERMINISTIC_ONLY",
                      "evidence": "runtime_callgraph (04_review → 02_build-excel) and tests/test_e2e.py: the integrated path exists only as rules + a test helper; "
                                  "no live agent participates and build commands do not require a prior review"}}
    (HERE / "reports" / "BLIND-ADVERSARIAL-EVALUATION.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out["MODE_A"]["metrics"].items() if k != "uncertainty"}, ensure_ascii=False, indent=1))
    print("MODE D:", out["MODE_D"].get("status") or out["MODE_D"].get("metrics"))


if __name__ == "__main__":
    main()
