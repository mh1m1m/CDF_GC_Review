"""TEST 37 — MAT_STRATEGIC_GRC_ADVISOR (directive Articles 09–16): profile loader and binding, the three advisory stages,
deterministic guards, adjudicator firewall, cycle control, Article 15 audit state, adversarial cases, CLI flag.

Synthetic only: the profile is tests/fixtures/mat/synthetic_mat_profile.json (a fictional reviewer), the documents are the
regression fixtures, and no provider credential exists. Nothing here is a live inference.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdf_gco_crms.agents import AgentRunner, MockAdapter, TraceWriter  # noqa: E402
from cdf_gco_crms.agents import contracts as C  # noqa: E402
from cdf_gco_crms.agents import mat_advisor as MA  # noqa: E402
from cdf_gco_crms.agents import mat_profile as MP  # noqa: E402
from cdf_gco_crms.agents.debate import Exchange  # noqa: E402
from cdf_gco_crms.agents.orchestrator import INDEPENDENCE_MOCK, ReviewOrchestrator  # noqa: E402
from cdf_gco_crms.assurance import challenge as CH  # noqa: E402
from cdf_gco_crms.assurance.evidence import EvidenceRegistry  # noqa: E402
from cdf_gco_crms.assurance.personas import RecipientPersona  # noqa: E402
from cdf_gco_crms.references.synthetic_index import synthetic_reference_index  # noqa: E402
from cdf_gco_crms.release import authorization_gate as G  # noqa: E402
from test_agents import DEPT, FINAL_READY, _objection_script, _state  # noqa: E402
from test_word_lifecycle import build_reviewed_doc  # noqa: E402


def _keys(obj, acc=None):
    """Every key name in a nested payload (isolation is about what material is present, not about words in notes)."""
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(str(k).lower()); _keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, acc)
    return acc


def _no_material(payload, *fragments):
    return not any(f in k for k in _keys(payload) for f in fragments)


@pytest.fixture(scope="module")
def profile():
    return MP.load_profile(MP.synthetic_fixture_path())


def _env(tmp_path, profile):
    st = _state()
    docx = build_reviewed_doc(st, tmp_path / "doc.docx")
    idx = synthetic_reference_index()
    reg = EvidenceRegistry(); reg.add_document_text(docx); reg.add_reference_index(idx)
    persona = RecipientPersona.from_index(idx, DEPT, reg)
    return st, docx, idx, reg, persona


def _cands():
    """Fictional candidates on a fictional partnership agreement; each carries exactly one documented marker."""
    return [
        {"observation_id": "C-FORMAL", "origin": "T", "location": "ص.1", "quote": "", "comment": "عنوان المادة (3) ورد داخل فقرة البند السابق لا في سطر مستقل.\nالتوصية: يُفصل العنوان في فقرة مستقلة."},
        {"observation_id": "C-SANCTION", "origin": "T", "location": "ص.2", "quote": "", "comment": "يشترط البند توثيق تسليم المعدات.\nالتوصية: إضافة بند بالنص الآتي: (\"يقر الشريك بأن المعدات مسجلة باسمه، ويُعد الإخلال به تعدياً يُسأل عنه الشريك وفق المادة (9)\".)"},
        {"observation_id": "C-REGULATORY", "origin": "T", "location": "ص.3", "quote": "", "comment": "يمنع الإقرار تزويد الشريك ببيانات المستفيدين.\nالتوصية: استثناء ما تقتضيه التزامات مكافحة غسل الأموال النظامية."},
        {"observation_id": "C-AUTHORITY", "origin": "T", "location": "ص.4", "quote": "", "comment": "يجيز البند تعديل سقف المنحة بين 10,000 و90,000 ريال بإخطار دون قرار من صاحب الصلاحية.\nالتوصية: ربط التعديل بصاحب الصلاحية."},
        {"observation_id": "C-APPRAISAL", "origin": "T", "location": "ص.5", "quote": "", "comment": "تقديم موعد الإعلان على موعد الاعتماد يجعل الإجراءين مرتبين سلفاً، والأقرب أن ذلك يحتاج قراراً صريحاً من اللجنة.\nالتوصية: يُعرض الترتيب على اللجنة المختصة."},
        {"observation_id": "C-MONEY", "origin": "T", "location": "ص.6", "quote": "", "comment": "تودع مساهمات الشركاء في حساب المشروع العام دون فصل.\nالتوصية: تخصيص حساب مستقل لمساهمات الشركاء."},
        {"observation_id": "C-DUP-A", "origin": "T", "location": "ص.7", "quote": "", "comment": "البند الأول.\nالتوصية: نوصي بتحديد الجهة المنفذة والإجراء المطلوب ومهلة التنفيذ بوضوح."},
        {"observation_id": "C-DUP-B", "origin": "T", "location": "ص.8", "quote": "", "comment": "البند الثاني.\nالتوصية: نوصي بتحديد الجهة المنفذة والإجراء المطلوب ومهلة التنفيذ بوضوح."},
        {"observation_id": "C-UNANCHORED", "origin": "T", "location": "ص.9", "quote": "نص غير موجود في الوثيقة إطلاقاً", "comment": "ملاحظة.\nالتوصية: شيء."},
        {"observation_id": "C-PERSON", "origin": "T", "location": "ص.10", "quote": "", "comment": "يُفضَّل تأكيد ملاءمة البند من قبل الأخ فلان قبل التوقيع.\nالتوصية: مراجعة البديل المقترح."},
    ]


# ====================================================================== profile loader and binding (Article 08–09)
def test_profile_loader_binding_and_view(profile, tmp_path, monkeypatch):
    assert profile.profile_id == "SYN_GRC_DNA" and profile.synthetic and not profile.binding_allowed
    assert profile.rule_status("SYN-S01")["use"] == "ADVISORY" and profile.rule_status("SYN-S06")["use"] == "NOT_ESTABLISHED"
    assert profile.rule_status("MAT-W10")["use"] == "ADVISORY" and profile.rule_status("ZZ-Z99")["use"] == "UNKNOWN_RULE"
    view = profile.view()
    assert "corpus_hashes" not in json.dumps(view) and view["binding"]["profile_sha256"] == profile.sha256
    assert all(r["use"] in ("ADVISORY", "NOT_ESTABLISHED") for r in view["selection_rules"]), "a NOT_APPROVED profile binds nothing"
    with pytest.raises(MP.ProfileNotConfigured):
        MP.load_profile(env={})
    monkeypatch.setenv(MP.ENV_PROFILE, str(MP.synthetic_fixture_path()))
    assert MP.load_profile().sha256 == profile.sha256
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps({"profile_id": "X", "version": "1"}), encoding="utf-8")
    with pytest.raises(MP.ProfileInvalid):
        MP.load_profile(bad)
    # a profile that claims approval but is still PROVISIONAL binds nothing either
    data = dict(profile.data); data["human_approval_status"] = "APPROVED"
    p = tmp_path / "prov.json"; p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert not MP.load_profile(p).binding_allowed
    data["status"] = "VALIDATED"; p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    lp = MP.load_profile(p)
    assert lp.binding_allowed and lp.rule_status("SYN-S01")["use"] == "ADVISORY", "even then only mat_explicitly_approved rules bind"


# ====================================================================== MAT-01 drafting (rule-based fallback + guards)
def test_rule_based_drafting_advice_preserves_candidates_and_applies_guards(profile, tmp_path):
    st, docx, idx, reg, persona = _env(tmp_path, profile)
    res = MA.MatAdvisor(profile, None).draft(st, _cands(), reg, persona)
    assert res.ok and res.outcome.mode == C.MODE_DETERMINISTIC and res.binding["profile_sha256"] == profile.sha256
    by = {a["observation_id"]: a for a in res.output["assessments"]}
    assert set(by) == {c["observation_id"] for c in _cands()}
    assert all(a["candidate_preserved"] and a["restorable_by_human"] for a in by.values())
    assert by["C-FORMAL"]["recommendation"] == "PROPOSE_WITHDRAWAL" and by["C-FORMAL"]["withdrawal_ground"] == "MAT-W10" \
        and by["C-FORMAL"]["withdrawal_ground_use"] == "ADVISORY" and by["C-FORMAL"]["framing"] == "DEFECT_FLAG"
    assert by["C-SANCTION"]["recommendation"] == "SOFTEN" and "يُسأل" not in by["C-SANCTION"]["proposed_text"] and "مسجلة" in by["C-SANCTION"]["proposed_text"]
    assert by["C-REGULATORY"]["recommendation"] == "ESCALATE" and by["C-REGULATORY"]["withdrawal_ground"] is None
    assert by["C-AUTHORITY"]["recommendation"] == "CONVERT_TO_QUESTION" and by["C-AUTHORITY"]["framing"] == "DIRECT_QUESTION"
    assert by["C-APPRAISAL"]["recommendation"] == "REVISE"
    assert by["C-MONEY"]["recommendation"] == "KEEP" and by["C-MONEY"]["dna_rules_invoked"] == ["SYN-S01"]
    assert by["C-DUP-A"]["recommendation"] == "MERGE" and by["C-DUP-A"]["covered_elsewhere_by"] == ["C-DUP-B"]
    assert by["C-UNANCHORED"]["recommendation"] == "REQUEST_EVIDENCE" and by["C-UNANCHORED"]["withdrawal_ground"] == "MAT-W05"
    assert "الأخ" not in json.dumps(by["C-PERSON"], ensure_ascii=False)
    assert all(u["use"] != "BINDING" for a in by.values() for u in a["dna_rule_use"])


def test_live_drafting_output_is_guarded(profile, tmp_path):
    st, docx, idx, reg, persona = _env(tmp_path, profile)
    cands = _cands()[:3]
    scripted = {"assessments": [
        {"observation_id": "C-FORMAL", "should_be_formal_observation": False, "material": False, "within_gco_jurisdiction": "YES", "evidence_sufficient": True,
         "covered_elsewhere_by": [], "contradicts": [], "recommendation": "PROPOSE_WITHDRAWAL", "framing": "DEFECT_FLAG", "proposed_text": None,
         "rationale": "formal", "dna_rules_invoked": ["SYN-S02", "QQ-Q01"], "dna_rule_applicability": [], "withdrawal_ground": None,
         "proportionate_and_implementable": True, "evidence_refs": [], "confidence": 0.7},
        {"observation_id": "C-REGULATORY", "should_be_formal_observation": False, "material": False, "within_gco_jurisdiction": "NO", "evidence_sufficient": True,
         "covered_elsewhere_by": [], "contradicts": [], "recommendation": "PROPOSE_WITHDRAWAL", "framing": "DIRECT_RECOMMENDATION",
         "proposed_text": "يُنسَّق مع الأخ فلان بشأن الاستثناء", "rationale": "outside scope", "dna_rules_invoked": ["SYN-S06"], "dna_rule_applicability": [],
         "withdrawal_ground": "MAT-W03", "proportionate_and_implementable": True, "evidence_refs": ["EV-000000000000"], "confidence": 0.6},
    ], "reasoning_summary": "s"}
    mock = MockAdapter(script={C.ROLE_MAT: scripted})
    res = MA.MatAdvisor(profile, AgentRunner(mock, TraceWriter(tmp_path / "t.jsonl"))).draft(st, cands, reg, persona)
    assert res.ok and res.outcome.mode == C.MODE_MOCK
    by = {a["observation_id"]: a for a in res.output["assessments"]}
    assert by["C-FORMAL"]["withdrawal_ground"] == "MAT-W15" and by["C-FORMAL"]["dna_rules_invoked"] == ["SYN-S02"]
    assert by["C-REGULATORY"]["recommendation"] == "ESCALATE" and by["C-REGULATORY"]["withdrawal_ground"] is None
    assert "الأخ" not in by["C-REGULATORY"]["proposed_text"] and by["C-REGULATORY"]["evidence_refs"] == []
    assert by["C-SANCTION"]["recommendation"] == "ESCALATE", "an unassessed candidate is escalated, never dropped"
    assert {"UNKNOWN_RULE_DROPPED", "REGULATORY_SAFEGUARD_GUARD", "PERSON_REFERENCE_REMOVED", "WITHDRAWAL_GROUND_DEFAULTED_TO_W15",
            "HALLUCINATED_REFS_DROPPED", "CANDIDATE_NOT_ASSESSED", "NOT_ESTABLISHED_RULE_CANNOT_SUPPORT_WITHDRAWAL"} <= set(res.guards)
    call = mock.calls[0]
    assert call.role == C.ROLE_MAT and call.payload["stage"] == MA.STAGE_DRAFTING and call.payload["label"] == "SYNTHETIC_TEST_CASE"
    assert _no_material(call.payload, "adjudic", "advocate", "objection") and call.agent_id == MA.AGENT_IDS[MA.STAGE_DRAFTING]
    # the schema refuses any disposition-like field: the advisor cannot adjudicate through its output
    assert C.validate(MA.MAT_DRAFTING_SCHEMA, {**scripted, "disposition": "UPHELD_UNCHANGED"})


# ====================================================================== MAT-02 interrogation and MAT-03 reassessment
def _objection(obs, kind="UNCLEAR_ACTION", refs=(), existing=()):
    return CH.Objection(obs.internal_id, kind, "التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ.", "الإدارة",
                        evidence_refs=list(refs), material_consequence="تعذر التنفيذ",
                        detail={"existing_controls": list(existing), "requested_correction": "تحديد الإجراء"})


def test_interrogation_discloses_participation_selects_questions_and_downgrades_unsupported_defence(profile, tmp_path):
    st, docx, idx, reg, persona = _env(tmp_path, profile)
    obs = st.ordered()[1]
    o = _objection(obs, kind="AUTHORITY_UNSUPPORTED")
    scripted = {"challenge_id": o.challenge_id, "observation_id": obs.internal_id, "original_position": "p", "black_team_objection": "o",
                "accepted_facts": [], "disputed_facts": ["x"], "verified_evidence": ["EV-000000000000"], "unverified_assumptions": [],
                "mat_dna_rules_invoked": ["SYN-S01"], "mat_dna_rule_applicability": [{"rule_id": "SYN-S01", "applicable": False, "reason": "not money"}],
                "response": "ندافع لأننا شاركنا في الصياغة.", "decision": "DEFEND_WITH_EVIDENCE", "revised_position": "", "proposed_wording": None,
                "withdrawal_recommendation": False, "withdrawal_ground": None, "confidence": 0.9, "escalation_required": False, "new_argument": True}
    mock = MockAdapter(script={C.ROLE_MAT: scripted})
    adv = MA.MatAdvisor(profile, AgentRunner(mock, TraceWriter(tmp_path / "t.jsonl")))
    res = adv.interrogate(st, obs, o, reg, persona, prior_advice={"recommendation": "KEEP"}, prior_turns=[])
    assert res.ok and res.output["decision"] == "REQUEST_ADDITIONAL_EVIDENCE" and "UNSUPPORTED_DEFENCE_DOWNGRADED" in res.guards
    assert res.output["verified_evidence"] == [] and "HALLUCINATED_REFS_DROPPED" in res.guards
    assert res.output["advisory_only"] is True and res.output["binding_disposition"] is None
    p = mock.calls[0].payload
    assert p["disclosure"]["prior_drafting_involvement"] is True and p["disclosure"]["prior_advice"] == {"recommendation": "KEEP"}
    assert [q["id"] for q in p["interrogation_questions"]] == MA.QUESTIONS_BY_KIND["AUTHORITY_UNSUPPORTED"]
    assert _no_material(p, "advocate", "adjudic", "disposition")
    assert mock.calls[0].agent_id == MA.AGENT_IDS[MA.STAGE_INTERROGATION]


def test_reassessment_records_an_evidence_based_reversal_without_penalty(profile, tmp_path):
    st, docx, idx, reg, persona = _env(tmp_path, profile)
    obs = st.ordered()[1]
    anchor = reg.bind_clause(obs.quote)
    o = _objection(obs, refs=[anchor.id])
    interrogation = {"decision": "DEFEND_WITH_EVIDENCE", "response": "r", "verified_evidence": [anchor.id], "proposed_wording": None, "withdrawal_recommendation": False}
    advocate = {"stance": "CONCEDE", "reasoning": "the objection is right", "evidence_refs": [anchor.id], "revised_comment": None, "revised_quote": None, "route_to": None, "missing_evidence": []}
    scripted = {"challenge_id": o.challenge_id, "previous_reasoning_valid": False, "black_team_identified_genuine_deficiency": True,
                "red_advocate_addressed_deficiency": False, "revised_comment_necessary": False, "decision": "ACCEPT_OBJECTION",
                "final_advisory_position": "نقبل الاعتراض.", "proposed_wording": None, "withdrawal_recommendation": False, "withdrawal_ground": None,
                "new_evidence_required": [], "position_changed": False, "change_reason": "", "evidence_refs": [anchor.id], "confidence": 0.8}
    mock = MockAdapter(script={C.ROLE_MAT: scripted})
    res = MA.MatAdvisor(profile, AgentRunner(mock, TraceWriter(tmp_path / "t.jsonl"))).reassess(st, obs, o, reg, interrogation=interrogation, advocate=advocate)
    assert res.ok and res.output["decision"] == "ACCEPT_OBJECTION" and res.output["position_changed"] is True
    assert "POSITION_CHANGE_RECORDED" in res.guards and res.outcome.status == C.STATUS_OK, "a reversal is recorded, not penalised"
    p = mock.calls[0].payload
    assert p["own_interrogation_response"]["decision"] == "DEFEND_WITH_EVIDENCE" and p["red_advocate_response"]["stance"] == "CONCEDE"
    assert _no_material(p, "adjudic", "disposition", "prior_advice", "disclosure"), "fresh context: no adjudicator, no drafting advice"
    assert mock.calls[0].agent_id.endswith("FRESH")
    # rule-based fallback: the same reversal on the same facts
    det = MA.MatAdvisor(profile, None).reassess(st, obs, o, reg, interrogation=interrogation, advocate=advocate)
    assert det.output["decision"] == "ACCEPT_OBJECTION" and det.output["position_changed"] and det.outcome.mode == C.MODE_DETERMINISTIC


# ====================================================================== adversarial cases (Article 16.3), rule-based
def test_adversarial_cases_rule_based(profile, tmp_path):
    st, docx, idx, reg, persona = _env(tmp_path, profile)
    obs = st.ordered()[1]
    anchor = reg.bind_clause(obs.quote)
    adv = MA.MatAdvisor(profile, None)
    def inter(o):
        return adv.interrogate(st, obs, o, reg, persona, prior_advice=None).output
    # black team raises an invalid objection (passage exists): defended with the anchor
    r = inter(_objection(obs, kind="CLAUSE_NOT_FOUND"))
    assert r["decision"] == "DEFEND_WITH_EVIDENCE" and anchor.id in r["verified_evidence"]
    # the observation overlooks an existing control named by the objection: accepted
    assert inter(_objection(obs, kind="CLAUSE_NOT_FOUND", existing=["بند 9-2 ينظم ذلك"]))["decision"] == "ACCEPT_OBJECTION"
    # duplicative → merge; outside mandate → narrow; inapplicable authority claim → evidence requested; reserved → human
    assert inter(_objection(obs, kind="DUPLICATE_REMEDY"))["decision"] == "MERGE_OBSERVATIONS"
    assert inter(_objection(obs, kind="OUTSIDE_RECIPIENT_MANDATE"))["decision"] == "NARROW_SCOPE"
    assert inter(_objection(obs, kind="AUTHORITY_UNSUPPORTED"))["decision"] == "REQUEST_ADDITIONAL_EVIDENCE"
    assert inter(_objection(obs, kind="RESERVED_DECISION"))["escalation_required"]
    # excessive control with a sanction clause: revised without the sanction
    r = inter(_objection(obs, kind="UNSUPPORTED_BREACH_CLAIM"))
    assert r["decision"] == "REVISE_RECOMMENDATION" and r["proposed_wording"]
    # red advocate produces an unsupported defence: the reassessment does not accept it
    o = _objection(obs, refs=[anchor.id])
    weak = {"stance": "DEFEND", "reasoning": "x", "evidence_refs": [], "revised_comment": None, "revised_quote": None, "route_to": None, "missing_evidence": []}
    r = adv.reassess(st, obs, o, reg, interrogation={"decision": "REVISE_RECOMMENDATION", "verified_evidence": []}, advocate=weak).output
    assert r["decision"] == "REQUEST_ADDITIONAL_EVIDENCE" and not r["red_advocate_addressed_deficiency"]
    # new evidence (an admissible anchor the advisor had not seen) → reversal with the evidence named
    strong = {**weak, "evidence_refs": [anchor.id]}
    r = adv.reassess(st, obs, o, reg, interrogation={"decision": "ACCEPT_OBJECTION", "verified_evidence": []}, advocate=strong).output
    assert r["decision"] == "DEFEND_WITH_EVIDENCE" and r["position_changed"] and anchor.id in r["change_reason"]
    # a proposed withdrawal of a regulatory safeguard is turned into an escalation
    o_reg = CH.Objection(obs.internal_id, "UNCLEAR_ACTION", "الاستثناء المتعلق بالتزامات مكافحة غسل الأموال غير لازم في هذا العقد.", "الإدارة")
    out, guards = adv._guard_debate({"decision": "PROPOSE_WITHDRAWAL", "withdrawal_ground": "MAT-W10", "verified_evidence": [], "original_position": "x"}, reg, o_reg, stage=MA.STAGE_INTERROGATION)
    assert out["decision"] == "ESCALATE_TO_HUMAN" and "REGULATORY_SAFEGUARD_GUARD" in guards


# ====================================================================== cycle control (Article 14)
def test_advisory_turns_never_consume_productive_cycles():
    o = CH.Objection("GCO-AGT-R1-001", "UNCLEAR_ACTION", "التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً.", "الإدارة")
    ex = Exchange(o.challenge_id)
    claims = ["الإجراء محدد في البند نفسه بوضوح كاف.", "المصفوفة لا تسمي الإدارة جهةً معتمِدة لهذا البند.", "البند التاسع ينظم إعادة المبلغ عند التعذر.",
              "الملحق الثاني يحدد مواعيد التنفيذ بدقة.", "الإشعار الكتابي يسبق الصرف وفق البند الرابع.", "خطاب التفويض يحدد الحساب المستلم."]
    assert ex.add(o, "BLACK", o.proposition, [])
    assert ex.advise(MA.STAGE_INTERROGATION, {"response": "نرى أن الاعتراض في محله جزئياً.", "decision": "NARROW_SCOPE"})
    assert not ex.advise(MA.STAGE_INTERROGATION, {"response": "نرى أن الاعتراض في محله جزئياً.", "decision": "NARROW_SCOPE"}), "a repeated advisory turn is unproductive"
    for i, c in enumerate(claims[:5]):
        assert ex.add(o, "RED_ADVOCATE" if i % 2 == 0 else "BLACK", c, [], stance="DEFEND" if i % 2 == 0 else None)
    assert len(ex.turns) == 6 and o.productive_cycles() == 6
    assert ex.advise(MA.STAGE_REASSESSMENT, {"final_advisory_position": "الموقف النهائي: تضييق النطاق إلى ما تملكه الإدارة.", "decision": "NARROW_SCOPE"})
    assert not ex.add(o, "BLACK", claims[5], []) and ex.cap_hit, "the seventh productive cycle is refused with advisory turns present"
    d = ex.to_dict()
    assert d["productive_cycles"] == 6 and len(d["advisory_turns"]) == 2 and all(a["advisory_only"] for a in d["advisory_turns"])
    assert ex.advisory_view(MA.STAGE_INTERROGATION)["status"] == "ADVISORY_ONLY_NOT_EVIDENCE"


# ====================================================================== orchestration: deterministic and mock-live
def test_orchestrator_with_mat_deterministic_records_state_and_leaves_gate_unchanged(profile, tmp_path):
    st = _state()
    docx = build_reviewed_doc(st, tmp_path / "doc.docx")
    before = (len(st.observations), G.state_fingerprint(st))
    ex = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate", mat_profile=profile).execute(st, docx, record_path=tmp_path / "rec.json")
    assert (len(st.observations), G.state_fingerprint(st)) == before, "the advisor never changes the register"
    assert ex.mat_advice and ex.mat_advice["mode"] == C.MODE_DETERMINISTIC and ex.mat_disclosure["prior_drafting_involvement"]
    assert set(ex.mat_state) == {o.internal_id for o in st.ordered()}
    s = next(iter(ex.mat_state.values())).to_dict()
    for k in ("Observation_ID", "Review_Round", "Original_GCO_Text", "MAT_Drafting_Recommendation", "MAT_DNA_Profile_Version", "MAT_DNA_Rules_Used",
              "MAT_Drafting_Execution_ID", "Black_Team_Challenge_ID", "MAT_Interrogation_Execution_ID", "MAT_Interrogation_Response",
              "Red_Advocate_Execution_ID", "MAT_Reassessment_Execution_ID", "MAT_Final_Advisory_Position", "Adjudicator_Execution_ID",
              "Human_Decision", "Final_Observation_State", "transitions"):
        assert k in s
    assert s["MAT_DNA_Profile_Version"] == profile.version and s["transitions"][0]["stage"] == MA.STAGE_DRAFTING
    assert ex.gate_record["execution_summary"]["mat_advisor"]["enabled"] and ex.gate_record["execution_summary"]["mat_advisor"]["advisory_only"]
    assert (tmp_path / "rec.mat-state.json").exists()
    plain = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate2").execute(st, docx)
    assert ex.record.dispositions == plain.record.dispositions and ex.record.cycles_used == plain.record.cycles_used, "advice changes no engine outcome"
    assert ex.final_review["recommendation"] == plain.final_review["recommendation"] == "READY"
    assert ex.status == "CLEAR" and G.authorize(st, tmp_path / "gate").ok and G.authorize(st, tmp_path / "gate2").ok


def test_orchestrator_with_mat_mock_live_firewall_and_cycles(profile, tmp_path):
    st = _state()
    docx = build_reviewed_doc(st, tmp_path / "doc.docx")
    idx = synthetic_reference_index()
    reg = EvidenceRegistry(); reg.add_document_text(docx)
    anchor = reg.bind_clause(st.ordered()[1].quote)
    def mat(p):
        stage = p["stage"]
        if stage == MA.STAGE_DRAFTING:
            return {"assessments": [{"observation_id": c["observation_id"], "should_be_formal_observation": True, "material": True, "within_gco_jurisdiction": "YES",
                                     "evidence_sufficient": True, "covered_elsewhere_by": [], "contradicts": [], "recommendation": "KEEP", "framing": "DIRECT_RECOMMENDATION",
                                     "proposed_text": None, "rationale": "kept", "dna_rules_invoked": ["SYN-S01"], "dna_rule_applicability": [], "withdrawal_ground": None,
                                     "proportionate_and_implementable": True, "evidence_refs": [], "confidence": 0.5} for c in p["candidates"]], "reasoning_summary": "s"}
        if stage == MA.STAGE_INTERROGATION:
            assert _no_material(p, "advocate", "adjudic", "disposition")
            return {"challenge_id": p["objection"]["challenge_id"], "observation_id": p["observation"]["internal_id"], "original_position": "p", "black_team_objection": "o",
                    "accepted_facts": ["الإجراء غير محدد"], "disputed_facts": [], "verified_evidence": [anchor.id], "unverified_assumptions": [], "mat_dna_rules_invoked": [],
                    "mat_dna_rule_applicability": [], "response": "نقترح مراجعة الصياغة لتحديد الإجراء.", "decision": "REVISE_RECOMMENDATION", "revised_position": "r",
                    "proposed_wording": "التوصية: تحديد الإجراء المطلوب.", "withdrawal_recommendation": False, "withdrawal_ground": None, "confidence": 0.6,
                    "escalation_required": False, "new_argument": True}
        assert _no_material(p, "adjudic", "disposition") and p["red_advocate_response"]["stance"] == "REVISE"
        return {"challenge_id": p["objection"]["challenge_id"], "previous_reasoning_valid": True, "black_team_identified_genuine_deficiency": True,
                "red_advocate_addressed_deficiency": True, "revised_comment_necessary": True, "decision": "REVISE_RECOMMENDATION",
                "final_advisory_position": "الموقف النهائي: المراجعة كافية.", "proposed_wording": "التوصية: تحديد الإجراء المطلوب.", "withdrawal_recommendation": False,
                "withdrawal_ground": None, "new_evidence_required": [], "position_changed": False, "change_reason": "", "evidence_refs": [anchor.id], "confidence": 0.7}
    script = {
        C.ROLE_BLACK: _objection_script(refs=[anchor.id]), C.ROLE_MAT: mat,
        C.ROLE_RED: {"stance": "REVISE", "objection_accepted": True, "reasoning": "تُراجع الصياغة لتحديد الإجراء.", "evidence_refs": [anchor.id],
                     "revised_comment": "البند لا يحدد الإجراء.\nالتوصية: تحديد الإجراء المطلوب والجهة المنفذة.", "revised_quote": None, "route_to": None,
                     "missing_evidence": [], "escalate": False, "new_argument": True},
        C.ROLE_ADJUDICATOR: {"disposition": "UPHELD_WITH_REVISION", "objection_valid": True, "rationale": "r", "decisive_evidence": [anchor.id], "inadmissible_refs": [],
                             "facts": [], "inferences": [], "unverified_assumptions": [], "remedy_assessment": "ok", "open_question": None, "escalate": False},
        C.ROLE_EDITORIAL: {"revised_comment": "البند لا يحدد الإجراء.\nالتوصية: تحديد الإجراء المطلوب والجهة المنفذة.", "finding_part": "f", "recommendation_part": "r",
                           "proposed_title": "تحديد الإجراء المطلوب", "changes": ["c"], "preserved_references": [],
                           "house_style": {"finding_before_recommendation": True, "no_accusation": True, "action_labelled": True, "within_word_ceiling": True},
                           "requires_human_approval": True},
        C.ROLE_FINAL: FINAL_READY,
    }
    mock = MockAdapter(script=script)
    runner = AgentRunner(mock, TraceWriter(tmp_path / "trace.jsonl"))
    ex = ReviewOrchestrator(idx, runner=runner, gate_dir=tmp_path / "gate", mat_profile=profile).execute(st, docx)
    assert [(o.kind, o.disposition) for e in ex.record.entries for o in e.objections] == [("UNCLEAR_ACTION", "UPHELD_WITH_REVISION")]
    assert ex.record.independence == INDEPENDENCE_MOCK and ex.status == "CLEAR"
    exch = list(ex.exchanges.values())[0]
    assert exch["productive_cycles"] == 2, "same cycle count as the pipeline without the advisor"
    assert [a["stage"] for a in exch["advisory_turns"]] == [MA.STAGE_INTERROGATION, MA.STAGE_REASSESSMENT]
    mat_calls = [c for c in mock.calls if c.role == C.ROLE_MAT]
    assert [c.payload["stage"] for c in mat_calls] == [MA.STAGE_DRAFTING, MA.STAGE_INTERROGATION, MA.STAGE_REASSESSMENT]
    assert len({c.context_id for c in mat_calls}) == 3
    red = [c for c in mock.calls if c.role == C.ROLE_RED][0].payload
    assert red["mat_advisory"]["status"] == "ADVISORY_ONLY_NOT_EVIDENCE" and red["mat_advisory"]["decision"] == "REVISE_RECOMMENDATION"
    adj = [c for c in mock.calls if c.role == C.ROLE_ADJUDICATOR][0].payload
    assert adj["mat_advisory"]["status"] == "ADVISORY_ONLY_NOT_EVIDENCE" and adj["mat_advisory"]["disclosure"]["prior_drafting_involvement"]
    assert adj["mat_advisory"]["reassessment"]["decision"] == "REVISE_RECOMMENDATION"
    assert "mat_advisory" in CB_adjudicator_system() and "not evidence" in CB_adjudicator_system()
    outs = [o for o in ex.role_outcomes if o["role"] == C.ROLE_MAT]
    assert len(outs) == 3 and all(o["mode"] == "MOCK" for o in outs)
    assert ex.trace_summary["actual_live_inference_count"] == 0
    s = ex.mat_state[st.ordered()[1].internal_id].to_dict()
    assert s["MAT_Interrogation_Response"][0]["decision"] == "REVISE_RECOMMENDATION" and s["Adjudicator_Execution_ID"] and s["Final_Observation_State"].startswith("ADVISORY:")
    assert G.authorize(st, tmp_path / "gate").ok


def CB_adjudicator_system():
    from cdf_gco_crms.agents import context_builder as CB
    return CB.SYSTEM[C.ROLE_ADJUDICATOR]


def test_mat_provider_failure_is_advisory_not_blocking(profile, tmp_path):
    st = _state()
    docx = build_reviewed_doc(st, tmp_path / "doc.docx")
    idx = synthetic_reference_index()
    reg = EvidenceRegistry(); reg.add_document_text(docx)
    anchor = reg.bind_clause(st.ordered()[1].quote)
    script = {C.ROLE_BLACK: _objection_script(refs=[anchor.id]),
              C.ROLE_RED: {"stance": "CONCEDE", "objection_accepted": True, "reasoning": "r", "evidence_refs": [], "revised_comment": None, "revised_quote": None,
                           "route_to": None, "missing_evidence": [], "escalate": False, "new_argument": True},
              C.ROLE_ADJUDICATOR: {"disposition": "WITHHELD_FOR_EVIDENCE", "objection_valid": True, "rationale": "r", "decisive_evidence": [], "inadmissible_refs": [],
                                   "facts": [], "inferences": [], "unverified_assumptions": [], "remedy_assessment": "", "open_question": "q", "escalate": False},
              C.ROLE_FINAL: FINAL_READY}
    runner = AgentRunner(MockAdapter(script=script, fail_roles={C.ROLE_MAT}), TraceWriter())
    ex = ReviewOrchestrator(idx, runner=runner, gate_dir=tmp_path / "gate", mat_profile=profile).execute(st, docx)
    outs = [o for o in ex.role_outcomes if o["role"] == C.ROLE_MAT]
    assert outs and all(o["status"] == C.STATUS_PROVIDER_FAILURE for o in outs)
    assert ex.provider_failures >= 1 and ex.status == "BLOCKED", "a failed advisor invocation is still a provider failure: the gate stays closed"
    s = ex.mat_state[st.ordered()[1].internal_id].to_dict()
    assert any(t["detail"].startswith("NOT_AVAILABLE") for t in s["transitions"])


def test_cli_mat_profile_flag(tmp_path, capsys):
    import main as CLI
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    st = _state()
    docx = build_reviewed_doc(st, tmp_path / "doc.docx")
    xlsx = tmp_path / "in.xlsx"; build_workbook(st, xlsx, working_copy=True)
    rc = CLI.main(["review", str(xlsx), "--docx", str(docx), "--synthetic-reference", "--gate-dir", str(tmp_path / "gate"), "--mat-profile", "synthetic"])
    out = capsys.readouterr().out; payload = json.loads(out[out.index("{"):])
    assert payload["mat_advisor"]["enabled"] and payload["mat_advisor"]["profile"]["synthetic"]
    rc2 = CLI.main(["review", str(xlsx), "--docx", str(docx), "--synthetic-reference", "--gate-dir", str(tmp_path / "gate2")])
    out = capsys.readouterr().out; payload = json.loads(out[out.index("{"):])
    assert payload["mat_advisor"] == {"enabled": False}
    with pytest.raises((SystemExit, MP.ProfileNotConfigured)):
        CLI.main(["review", str(xlsx), "--docx", str(docx), "--synthetic-reference", "--gate-dir", str(tmp_path / "gate3"), "--mat-profile", str(tmp_path / "missing.json")])
