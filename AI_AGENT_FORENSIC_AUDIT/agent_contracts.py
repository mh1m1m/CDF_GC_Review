#!/usr/bin/env python3
"""Shared contracts of the audit harness: case loading, engine state construction, and the execution-record schema
that every live (audit-harness) agent run must satisfy. Read-only on the product."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))

CASES = HERE / "cases" / "synthetic_inputs"
SEALED = HERE / "cases" / "sealed_expected_results"
RECORDS = HERE / "evidence" / "agent_execution_records"

RECORD_FIELDS = ("Case_ID", "Observation_ID", "Challenge_ID", "Execution_ID", "Agent_ID", "Agent_Role", "Provider", "Model", "Context_ID",
                 "Invocation_ID", "Timestamp", "Prompt_Hash", "Response_Hash", "Evidence_References", "Tool_Calls", "Token_Usage", "Latency",
                 "Execution_Status", "Origin")
ORIGINS = ("LIVE_PROVIDER_INFERENCE", "LOCAL_MODEL_INFERENCE", "CACHED_REPLAY", "DETERMINISTIC_FIXTURE", "MOCK_PROVIDER", "HARDCODED_OUTPUT",
           "UNVERIFIED_ORIGIN", "CLAUDE_CODE_AGENT_RUNTIME_AUDIT_HARNESS")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_cases(include_live_only: bool = False) -> list[dict]:
    out = []
    for p in sorted(CASES.glob("*.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        assert "_sealed" not in c and "expected" not in json.dumps(c, ensure_ascii=False).lower(), f"{p.name}: agent input carries a label"
        if c.get("live_only") and not include_live_only:
            continue
        out.append(c)
    return out


def load_sealed() -> dict:
    text = (SEALED / "EXPECTED.json").read_text(encoding="utf-8")
    seal = (SEALED / "EXPECTED.sha256").read_text(encoding="utf-8").strip()
    assert sha(text) == seal, "sealed expected results were modified after generation"
    return json.loads(text)


def engine_state(case: dict):
    """ReviewState + target Observation for a case, the way held-out cases are built (birth 2 unless issued)."""
    from cdf_gco_crms.model.entities import Document, GText, Observation, ReviewRound, ReviewState, TitleEvidence
    o = case["observation"]
    kwargs = {}
    if case.get("title"):
        kwargs = {"title": case["title"], "title_status": case["title_status"],
                  "title_evidence": TitleEvidence("Synthetic Reviewer", "2026-10-23", "SYN-TITLE-1") if case["title_status"] in ("APPROVED", "ISSUED") else None}
    obs = []
    if case.get("sibling"):
        obs.append(Observation("GCO-AUD-R1-001", "1", 1, o["location"], case["sibling"][0], GText.plain(case["sibling"][1])))
    birth = 1 if case["issued"] else 2
    target = Observation("GCO-AUD-R1-002" if case["issued"] else "GCO-AUD-R2-002", "2", birth, o["location"], o["quote"], GText.plain(o["comment"]), **kwargs)
    obs.append(target)
    doc = Document(name="مذكرة تفاهم تجريبية للتدقيق", code="AUD", owning_department=case["department"], is_demo=True)
    return ReviewState(doc, [ReviewRound(1, "2026-09-15"), ReviewRound(2, "2026-10-15")], obs), target


def engine_run(case: dict, index, *, max_cycles: int = 6):
    """One deterministic engine run of a case: (record, entry, registry, persona)."""
    from cdf_gco_crms.assurance import challenge as CH
    from cdf_gco_crms.assurance.evidence import EvidenceRegistry
    from cdf_gco_crms.assurance.personas import RecipientPersona
    reg = EvidenceRegistry()
    reg.add_document_text("\n".join(case["document_paragraphs"]), f"{case['case_id']}.txt")
    reg.add_reference_index(index)
    persona = RecipientPersona.from_index(index, case["department"], reg)
    state, target = engine_state(case)
    if case.get("basis_policy"):
        ev = reg.add_policy(case["basis_policy"][0], case["basis_policy"][1], approval_status=case["basis_policy"][2])
        reg.attach_basis(target.internal_id, ev.id)
    rec = CH.run_challenge(state, reg, persona, max_cycles=max_cycles, matters={target.internal_id: case["matter"]} if case.get("matter") else None)
    entry = next(e for e in rec.entries if e.internal_id == target.internal_id)
    return rec, entry, reg, persona


def validate_record(r: dict) -> list[str]:
    problems = [f for f in RECORD_FIELDS if f not in r]
    if r.get("Origin") not in ORIGINS:
        problems.append(f"Origin {r.get('Origin')!r} not in {ORIGINS}")
    return problems
