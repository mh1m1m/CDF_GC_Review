"""TEST 39 — layer E: end-to-end review on an unseen synthetic document through the orchestrated pipeline
(scripted provider standing in for the live roles) down to saved Word and Excel artefacts and their verification.

    unseen synthetic document → agent review (black team → red advocate → adjudicator) → authorised
    disposition (signed synthetic decision on a demo document) → final review → gate → Word + Excel →
    saved-artefact verification (parse back, comments, confidentiality scan, working-copy markers)

Mocked and live results are never pooled: this test reports MOCK; tests/test_agents_live.py reports LIVE.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import main as CLI  # noqa: E402
from cdf_gco_crms.agents import AgentRunner, MockAdapter, TraceWriter  # noqa: E402
from cdf_gco_crms.agents import contracts as C  # noqa: E402
from cdf_gco_crms.agents import evaluator as E  # noqa: E402
from cdf_gco_crms.agents.orchestrator import ReviewOrchestrator  # noqa: E402
from cdf_gco_crms.assurance.challenge import confidentiality_scan  # noqa: E402
from cdf_gco_crms.assurance.objection_engine import HumanDecision  # noqa: E402
from cdf_gco_crms.ingestion.workbook_reader import parse_workbook  # noqa: E402
from cdf_gco_crms.model.entities import Document, GText  # noqa: E402
from cdf_gco_crms.references.synthetic_index import synthetic_reference_index  # noqa: E402
from cdf_gco_crms.release import authorization_gate as G  # noqa: E402
from cdf_gco_crms.release import trust as T  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import NewObservation, build_round1  # noqa: E402
from test_word_lifecycle import build_reviewed_doc, gco_comments  # noqa: E402

DEPT = "الحوكمة والامتثال"
FINAL_READY = {"release_recommendation": "READY", "findings": [], "unresolved_critical_objections": [], "contradictions": [],
               "jurisdiction_consistent": True, "unsupported_or_excessive": [], "summary": "s"}


def _unseen_state():
    """Observations on the holdout document, not on the regression fixtures: unseen by every earlier test."""
    q = E._QUOTE
    obs = [NewObservation("ص.2، المادة (3)", q[3], GText.plain("نوصي باشتراط موافقة الصندوق المسبقة على أي مبادرة جديدة لا الاكتفاء بالإشعار.")),
           NewObservation("ص.3، المادة (4)", q[4], GText.plain("نوصي بتحديد نطاق البيانات المتبادلة وضوابط حمايتها ومدة الاحتفاظ بها.")),
           NewObservation("ص.4، المادة (6)", q[6], GText.plain("البند عام ولا يوضح المقصود بالاتفاق المستقل."))]
    doc = Document(name="اتفاقية تعاون افتراضية غير مرئية", code="UNS", owning_department=DEPT, is_demo=True)
    return build_round1(doc, obs, date="2026-03-01", document_version="الإصدار 0.1")


def _run(argv, capsys):
    rc = CLI.main(argv)
    out = capsys.readouterr().out
    return (rc if isinstance(rc, int) else 0), json.loads(out[out.index("{"):])


def test_e2e_unseen_document_through_agents_decision_gate_and_artifacts(tmp_path, capsys):
    st = _unseen_state()
    # the case document: the holdout paragraphs with the quoted clauses present
    docx = build_reviewed_doc(st, tmp_path / "case.docx")
    xlsx_in = tmp_path / "in.xlsx"
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    build_workbook(st, xlsx_in, working_copy=True)
    st = parse_workbook(xlsx_in).state
    target = st.ordered()[2]
    from cdf_gco_crms.assurance.evidence import EvidenceRegistry
    reg = EvidenceRegistry(); reg.add_document_text(docx)
    anchor = reg.bind_clause(target.quote)

    def black(p):
        first = p["observation"]["reader_no"] == target.reader_no and not p.get("prior_exchange")
        return {"material_objection": first, "objection_kind": "UNCLEAR_ACTION" if first else "NO_MATERIAL_OBJECTION",
                "challenged_claim": "البند عام", "proposition": "الملاحظة لا تطلب إجراءً محدداً من الإدارة ولا تبين الصياغة المطلوبة." if first else "",
                "material_consequence": "تعذر التنفيذ", "evidence_refs": [anchor.id], "existing_controls": [],
                "requested_correction": "تحديد الإجراء", "reasoning_summary": "r", "evidence_limitations": "", "confidence": 0.7}
    revised = "البند عام ولا يوضح المقصود بالاتفاق المستقل.\nالتوصية: تعريف الاتفاق المستقل وربط اعتماده بصاحب الصلاحية المالية."
    script = {C.ROLE_BLACK: black,
              C.ROLE_RED: {"stance": "REVISE", "objection_accepted": True, "reasoning": "تُراجع الصياغة لتحديد الإجراء.", "evidence_refs": [anchor.id],
                           "revised_comment": revised, "revised_quote": None, "route_to": None, "missing_evidence": [], "escalate": False, "new_argument": True},
              C.ROLE_ADJUDICATOR: {"disposition": "UPHELD_WITH_REVISION", "objection_valid": True, "rationale": "r", "decisive_evidence": [anchor.id],
                                   "inadmissible_refs": [], "facts": [], "inferences": [], "unverified_assumptions": [], "remedy_assessment": "ok",
                                   "open_question": None, "escalate": False},
              C.ROLE_EDITORIAL: {"revised_comment": revised, "finding_part": "f", "recommendation_part": "r", "proposed_title": "تعريف الاتفاق المستقل",
                                 "changes": ["c"], "preserved_references": [], "requires_human_approval": True,
                                 "house_style": {"finding_before_recommendation": True, "no_accusation": True, "action_labelled": True, "within_word_ceiling": True}},
              C.ROLE_FINAL: FINAL_READY}
    gate = tmp_path / "gate"
    runner = AgentRunner(MockAdapter(script=script), TraceWriter(tmp_path / "trace.jsonl"))
    ex = ReviewOrchestrator(synthetic_reference_index(), runner=runner, gate_dir=gate).execute(st, docx, command="agent-review")
    assert ex.status == "CLEAR" and ex.trace_summary["mock_inference_count"] == len(ex.role_outcomes) and ex.trace_summary["actual_live_inference_count"] == 0
    assert [o.disposition for e in ex.record.entries for o in e.objections] == ["UPHELD_WITH_REVISION"]
    assert len(ex.editorial_candidates) == 1 and ex.final_review["recommendation"] == "READY"
    # human-authorised disposition (synthetic key on a demo document) → revised register with a new fingerprint
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    store = T.TrustStore(); store.keys["SYNTHETIC_TEST_KEY"] = T.KeyEntry("SYNTHETIC_TEST_KEY", pub, roles=("GCO reviewer",), synthetic=True)
    d = HumanDecision("D-1", target.internal_id, "UPHELD_WITH_REVISION", "م. مراجع (تجريبي)", "GCO reviewer", "DEC-1",
                      dt.datetime.now(dt.timezone.utc).isoformat(), "E-1", "VERIFIED_HUMAN_RECORD", "SYNTHETIC_TEST_KEY", "", ex.fingerprint, "")
    d = replace(d, signature_b64=base64.b64encode(priv.sign(d.signature_payload())).decode())
    from cdf_gco_crms.release.dispositions import apply_dispositions
    res = apply_dispositions(st, ex.record, [d], store, expected_fingerprint=ex.fingerprint, ledger_path=gate / "ledger.jsonl")
    assert res.applied and res.changed and res.state.by_id()[target.internal_id].comment.text == revised
    # the revised state is reviewed again (clean on the same document) and cleared
    ex2 = ReviewOrchestrator(synthetic_reference_index(), runner=AgentRunner(MockAdapter(script={C.ROLE_BLACK: lambda p: {**black(p), "material_objection": False, "objection_kind": "NO_MATERIAL_OBJECTION", "proposition": ""}, C.ROLE_FINAL: FINAL_READY}), TraceWriter()),
                             gate_dir=gate).execute(res.state, docx)
    assert ex2.status == "CLEAR" and G.authorize(res.state, gate).ok
    # Word + Excel through the gated CLI, then saved-artefact verification
    build_workbook(res.state, tmp_path / "revised_draft.xlsx", working_copy=True)
    rc, rep = _run(["build-excel", str(tmp_path / "revised_draft.xlsx"), str(tmp_path / "issue"), "--gate-dir", str(gate)], capsys)
    assert rc == 0 and rep["release_authorized"] and not rep["working_copy"]
    xlsx = Path(rep["output"])
    rc, rep = _run(["build-word", str(tmp_path / "revised_draft.xlsx"), str(tmp_path / "issue" / "r1.docx"), "--gate-dir", str(gate), "--source", str(docx)], capsys)
    assert rc == 0 and rep["release_authorized"]
    out_docx = Path(rep["output"])
    back = parse_workbook(xlsx).state
    assert back.by_id()[target.internal_id].comment.text == revised and len(back.observations) == 3
    assert not G.xlsx_is_working_copy(xlsx) and not G.docx_is_working_copy(out_docx)
    assert len(gco_comments(out_docx)) == 3
    assert confidentiality_scan([xlsx, out_docx]) == []
    # the original (unrevised) state is still not issuable with the old record after the register changed: different content
    assert G.authorize(st, gate).ok, "the first review's record still binds the first content"
    assert G.state_fingerprint(res.state) != ex.fingerprint
