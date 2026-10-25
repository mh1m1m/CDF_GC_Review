"""TEST 35 — live multi-agent runtime, layers A (unit) and B (integration), synthetic only, no provider credential.

Layer A: contracts and schema validation, provider adapters (mock, cached, credential-less anthropic), isolated
runner (ids, hashes, failure/refusal/schema handling), security (data-handling authorisation, context isolation,
redaction), tracing counts, debate productivity rules.
Layer B: the six roles over a scripted provider feeding the real engine objects, the orchestrator pipeline
(deterministic, mock-live, provider failure), editorial candidates, final reviewer, gate record binding.
Nothing here is a live inference and nothing here is reported as one (see tests/test_agents_live.py).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdf_gco_crms.agents import AgentRunner, MockAdapter, TraceWriter  # noqa: E402
from cdf_gco_crms.agents import context_builder as CB  # noqa: E402
from cdf_gco_crms.agents import contracts as C  # noqa: E402
from cdf_gco_crms.agents import roles as R  # noqa: E402
from cdf_gco_crms.agents.debate import Exchange, is_semantic_duplicate  # noqa: E402
from cdf_gco_crms.agents.orchestrator import INDEPENDENCE_MOCK, INDEPENDENCE_RULES, ReviewOrchestrator  # noqa: E402
from cdf_gco_crms.agents.providers import CachedAdapter, ProviderConfig, ProviderFailure, RecordingAdapter, provider_from_env  # noqa: E402
from cdf_gco_crms.agents.providers.anthropic_adapter import AnthropicAdapter  # noqa: E402
from cdf_gco_crms.agents.security import ContextIsolationViolation, DataHandlingViolation, sanitize  # noqa: E402
from cdf_gco_crms.assurance import challenge as CH  # noqa: E402
from cdf_gco_crms.assurance.evidence import EvidenceRegistry  # noqa: E402
from cdf_gco_crms.assurance.personas import RecipientPersona  # noqa: E402
from cdf_gco_crms.model.entities import Document  # noqa: E402
from cdf_gco_crms.references.synthetic_index import synthetic_reference_index  # noqa: E402
from cdf_gco_crms.release import authorization_gate as G  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import build_round1  # noqa: E402
from conftest import base_obs  # noqa: E402
from test_word_lifecycle import build_reviewed_doc  # noqa: E402

DEPT = "الحوكمة والامتثال"
SYN = {"label": "SYNTHETIC_TEST_CASE"}

NO_OBJ = {"material_objection": False, "objection_kind": "NO_MATERIAL_OBJECTION", "challenged_claim": "", "proposition": "",
          "material_consequence": "", "evidence_refs": [], "existing_controls": [], "requested_correction": "",
          "reasoning_summary": "لا اعتراض جوهري.", "evidence_limitations": "", "confidence": 0.8}
FINAL_READY = {"release_recommendation": "READY", "findings": [], "unresolved_critical_objections": [], "contradictions": [],
               "jurisdiction_consistent": True, "unsupported_or_excessive": [], "summary": "ok"}


def _state(n=4, code="AGT", demo=True):
    doc = Document(name="وثيقة اختبار الوكلاء", code=code, owning_department=DEPT, is_demo=demo)
    return build_round1(doc, base_obs(n), date="2026-02-15", document_version="الإصدار 0.1")


def _objection_script(target_reader="02", kind="UNCLEAR_ACTION", refs=None):
    def black(p):
        first = p["observation"]["reader_no"] == target_reader and not p.get("prior_exchange")
        return {**NO_OBJ, "material_objection": first, "objection_kind": kind if first else "NO_MATERIAL_OBJECTION",
                "proposition": "التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ." if first else "",
                "material_consequence": "تعذر التنفيذ", "evidence_refs": list(refs or []), "requested_correction": "تحديد الإجراء"}
    return black


# ====================================================================== layer A
def test_schema_validation_catches_shape_enum_pattern_and_extra_keys():
    assert C.validate(C.BLACK_TEAM_SCHEMA, NO_OBJ) == []
    bad = {**NO_OBJ, "objection_kind": "MADE_UP", "evidence_refs": ["not-an-id"], "extra": 1}
    errs = C.validate(C.BLACK_TEAM_SCHEMA, bad)
    assert any("enum" in e for e in errs) and any("pattern" in e or "match" in e for e in errs) and any("unexpected" in e for e in errs)
    assert C.validate(C.FINAL_REVIEWER_SCHEMA, FINAL_READY) == []
    assert C.validate(C.EDITORIAL_SCHEMA, {"requires_human_approval": False})   # must fail: enum [True] and missing keys


def test_request_ids_and_hashes_are_deterministic_per_content():
    a = C.AgentRequest(C.ROLE_BLACK, "sys", {"x": 1}, C.BLACK_TEAM_SCHEMA)
    b = C.AgentRequest(C.ROLE_BLACK, "sys", {"x": 1}, C.BLACK_TEAM_SCHEMA)
    c = C.AgentRequest(C.ROLE_BLACK, "sys", {"x": 2}, C.BLACK_TEAM_SCHEMA)
    assert a.prompt_hash == b.prompt_hash and a.context_id == b.context_id and a.prompt_hash != c.prompt_hash
    with pytest.raises(ValueError):
        C.AgentRequest("NOT_A_ROLE", "s", {}, {})


def test_runner_isolates_each_invocation_and_separates_modes(tmp_path):
    mock = MockAdapter(script={C.ROLE_BLACK: NO_OBJ})
    runner = AgentRunner(mock, TraceWriter(tmp_path / "t.jsonl"))
    r1 = runner.run(C.ROLE_BLACK, "s", {**SYN, "n": 1})
    r2 = runner.run(C.ROLE_BLACK, "s", {**SYN, "n": 1})
    assert r1.ok and r2.ok and r1.execution_id != r2.execution_id and r1.context_id == r2.context_id
    assert r1.mode == C.MODE_MOCK and r1.invocation_id != r2.invocation_id
    assert len(mock.calls) == 2 and all(len(c.payload) == 2 for c in mock.calls), "no state carried between invocations"
    s = runner.trace.summary()
    assert s["by_mode"]["MOCK"] == 2 and s["actual_live_inference_count"] == 0 and s["mock_inference_count"] == 2
    lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "Prompt_Hash" in lines[0] and "payload" not in lines[0].lower()


def test_runner_reports_failure_refusal_and_schema_violation_as_non_results():
    fail = AgentRunner(MockAdapter(fail_roles={C.ROLE_RED}), TraceWriter()).run(C.ROLE_RED, "s", SYN)
    assert fail.status == C.STATUS_PROVIDER_FAILURE and fail.output is None and not fail.ok
    refused = AgentRunner(MockAdapter(refuse_roles={C.ROLE_RED}), TraceWriter()).run(C.ROLE_RED, "s", SYN)
    assert refused.status == C.STATUS_REFUSED and refused.output is None
    bad = AgentRunner(MockAdapter(raw_text={C.ROLE_RED: '{"stance": "DEFEND"}'}), TraceWriter()).run(C.ROLE_RED, "s", SYN)
    assert bad.status == C.STATUS_SCHEMA_INVALID and bad.schema_errors
    none = AgentRunner(None, TraceWriter()).run(C.ROLE_RED, "s", SYN)
    assert none.status == C.STATUS_PROVIDER_FAILURE and none.mode == C.MODE_DETERMINISTIC


def test_retryable_failures_are_bounded():
    class Flaky(MockAdapter):
        def complete(self, request):
            self.calls.append(request)
            raise ProviderFailure("boom", retryable=True, kind="TIMEOUT")
    flaky = Flaky()
    resp = AgentRunner(flaky, TraceWriter(), max_attempts=3).run(C.ROLE_BLACK, "s", SYN)
    assert resp.status == C.STATUS_PROVIDER_FAILURE and len(flaky.calls) == 3


def test_security_data_handling_and_context_isolation(monkeypatch):
    live = AnthropicAdapter(ProviderConfig(provider="anthropic", timeout_seconds=3, max_retries=0))
    runner = AgentRunner(live, TraceWriter())
    with pytest.raises(DataHandlingViolation):
        runner.run(C.ROLE_BLACK, "s", {"label": "INSTITUTIONAL_CONTENT", "text": "x"})
    with pytest.raises(ContextIsolationViolation):
        runner.run(C.ROLE_BLACK, "s", {**SYN, "expected": "UPHELD"})
    authorised = AnthropicAdapter(ProviderConfig(provider="anthropic", timeout_seconds=3, max_retries=0,
                                                 data_authorization="INSTITUTIONAL_AUTHORIZED:REF-TEST-1"))
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    resp = AgentRunner(authorised, TraceWriter()).run(C.ROLE_BLACK, "s", {"label": "INSTITUTIONAL_CONTENT"})
    assert resp.status == C.STATUS_PROVIDER_FAILURE and "AUTHENTICATION" in (resp.error or ""), "no credential → failure, never a fabricated answer"
    assert "sk-ant-" not in sanitize("key sk-ant-abcdefghijklmnop more") and "[REDACTED]" in sanitize("Bearer abcdefghijklmnopqrstuvwxyz")


def test_provider_from_env_never_defaults_to_a_silent_mock():
    assert provider_from_env({}) is None
    assert provider_from_env({"CDF_AI_PROVIDER": "mock"}).mode == C.MODE_MOCK
    assert provider_from_env({"CDF_AI_PROVIDER": "anthropic"}).mode == C.MODE_LIVE


def test_cached_adapter_replays_only_recorded_live_responses(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"deadbeef": {"text": "{}", "recorded_mode": "MOCK"}}), encoding="utf-8")
    cached = CachedAdapter(cache)
    with pytest.raises(ProviderFailure):
        cached.complete(C.AgentRequest(C.ROLE_BLACK, "s", {}, C.BLACK_TEAM_SCHEMA))
    with pytest.raises(ValueError):
        RecordingAdapter(MockAdapter(), tmp_path / "x.json")


def test_debate_productivity_rules():
    assert is_semantic_duplicate("التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ.",
                                 ["التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ."])[0]
    assert is_semantic_duplicate("التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ في الوثيقة.",
                                 ["التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ."])[0]
    assert not is_semantic_duplicate("المصفوفة لا تسمي الإدارة جهةً معتمِدة لهذا البند.", ["التوصية لا تحدد الإجراء المطلوب."])[0]
    o = CH.Objection("GCO-AGT-R1-001", "UNCLEAR_ACTION", "التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً.", "الإدارة")
    ex = Exchange(o.challenge_id)
    assert ex.add(o, "BLACK", o.proposition, [])
    assert ex.add(o, "RED_ADVOCATE", "الإجراء محدد في البند نفسه بوضوح كاف.", [], stance="DEFEND")
    assert not ex.add(o, "BLACK", o.proposition, []), "an exact repeat never consumes a cycle"
    assert ex.unproductive and ex.unproductive[-1]["reason"] in ("EXACT_REPEAT", "NGRAM_REPEAT", "JACCARD_REPEAT")
    assert o.productive_cycles() == 2
    claims = ["المصفوفة لا تسمي الإدارة جهة اعتماد لهذا البند في أي صفحة.", "البند الثاني من المصفوفة يسمي الرئيس التنفيذي جهة الاعتماد صراحة.",
              "الدليل المستند إليه من مصدر مقترح غير معتمد فلا يحسم الاختصاص.", "مرساة الموضع ثابتة في الوثيقة المراجعة وتكفي لإثبات الواقعة.",
              "الضوابط القائمة في سياسة الصرف تعالج المسألة ذاتها دون حاجة للتوصية.", "سياسة الصرف المشار إليها غير مرفقة في سجل الأدلة فلا يُحتج بها."]
    actors = ["BLACK", "RED_ADVOCATE"]
    added = 0
    for i, c in enumerate(claims):
        if ex.add(o, actors[i % 2], c, [], stance="DEFEND" if i % 2 else None):
            added += 1
    assert o.productive_cycles() == 6 and ex.cap_hit, "the seventh productive cycle is refused"


# ====================================================================== layer B
def test_roles_convert_scripted_output_into_engine_objects(tmp_path):
    st = _state()
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    idx = synthetic_reference_index()
    reg = EvidenceRegistry(); reg.add_document_text(full); reg.add_reference_index(idx)
    persona = RecipientPersona.from_index(idx, DEPT, reg)
    obs = st.ordered()[1]
    anchor = reg.bind_clause(obs.quote)
    runner = AgentRunner(MockAdapter(script={C.ROLE_BLACK: _objection_script(refs=[anchor.id, "EV-000000000000"])}), TraceWriter())
    objections, out = R.run_black_team(runner, st, obs, reg, persona, issued=False)
    assert len(objections) == 1 and out.mode == C.MODE_MOCK and "hallucinated_refs:1" in out.notes
    o = objections[0]
    assert o.kind == "UNCLEAR_ACTION" and o.evidence_refs == [anchor.id] and o.detail["origin"] == C.MODE_MOCK
    # advocate: DEFEND without admissible evidence is downgraded, REVISE without text is downgraded
    runner = AgentRunner(MockAdapter(script={C.ROLE_RED: {"stance": "DEFEND", "objection_accepted": False, "reasoning": "r",
                                                          "evidence_refs": ["EV-000000000000"], "revised_comment": None, "revised_quote": None,
                                                          "route_to": None, "missing_evidence": [], "escalate": False, "new_argument": True}}),
                         TraceWriter())
    adv, ro = R.run_red_advocate(runner, st, obs, o, reg, persona, issued=False)
    assert adv.stance == "CONCEDE" and "UNSUPPORTED_DEFENCE" in ro.notes
    # adjudicator: a live UPHELD without a verified basis is withheld by the guard
    runner = AgentRunner(MockAdapter(script={C.ROLE_ADJUDICATOR: {"disposition": "UPHELD_UNCHANGED", "objection_valid": False, "rationale": "r",
                                                                  "decisive_evidence": [], "inadmissible_refs": [], "facts": [],
                                                                  "inferences": [], "unverified_assumptions": [], "remedy_assessment": "",
                                                                  "open_question": None, "escalate": False}}), TraceWriter())
    o_bare = CH.Objection(obs.internal_id, "UNCLEAR_ACTION", o.proposition, persona.addressee)      # no evidence anywhere
    adj, ao, guards = R.run_adjudicator(runner, st, obs, o_bare, adv, reg, issued=False)
    assert adj.disposition == "WITHHELD_FOR_EVIDENCE" and "NO_VERIFIED_BASIS" in guards
    adj_ok, _, guards_ok = R.run_adjudicator(runner, st, obs, o, adv, reg, issued=False)
    assert adj_ok.disposition == "UPHELD_UNCHANGED" and guards_ok == [], "a hashed document anchor is a verified basis, as in the rule engine"
    # issued observation: any live disposition is escalated (17.7)
    o_issued = CH.Objection(obs.internal_id, "UNCLEAR_ACTION", o.proposition, persona.addressee, issued=True)
    adj2, _, guards2 = R.run_adjudicator(runner, st, obs, o_issued, adv, reg, issued=True)
    assert adj2.disposition == "ESCALATED_TO_GCO_REVIEWER" and "RESERVED_MATTER" in guards2
    # deterministic fallback keeps the rule engine
    objs_det, out_det = R.run_black_team(None, st, obs, reg, persona, issued=False)
    assert out_det.mode == C.MODE_DETERMINISTIC
    props, dout = R.run_drafting(None, st, reg, persona)
    assert props == [] and dout.status == C.STATUS_NOT_RUN


def test_orchestrator_deterministic_pipeline_records_final_review_and_gate(tmp_path):
    st = _state()
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    ex = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, full)
    assert ex.status == "CLEAR" and ex.record.independence == INDEPENDENCE_RULES and ex.provider_failures == 0
    assert ex.final_review["mode"] == C.MODE_DETERMINISTIC and ex.final_review["recommendation"] == "READY"
    assert ex.gate_record["final_review"]["recommendation"] == "READY" and ex.gate_record["source_document_sha256"] == ex.document_sha256
    auth = G.authorize(st, tmp_path / "gate")
    assert auth.ok, auth.reasons
    assert G.authorize(st, tmp_path / "gate", source_document_sha256="0" * 64).reasons == [G.R_SOURCE_DOCUMENT_MISMATCH]


def test_orchestrator_mock_live_pipeline_runs_every_role_in_separate_contexts(tmp_path):
    st = _state()
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    idx = synthetic_reference_index()
    reg = EvidenceRegistry(); reg.add_document_text(full)
    anchor = reg.bind_clause(st.ordered()[1].quote)
    script = {
        C.ROLE_BLACK: _objection_script(refs=[anchor.id]),
        C.ROLE_RED: {"stance": "REVISE", "objection_accepted": True, "reasoning": "تُراجع الصياغة لتحديد الإجراء.",
                     "evidence_refs": [anchor.id], "revised_comment": "البند لا يحدد الإجراء.\nالتوصية: تحديد الإجراء المطلوب والجهة المنفذة.",
                     "revised_quote": None, "route_to": None, "missing_evidence": [], "escalate": False, "new_argument": True},
        C.ROLE_ADJUDICATOR: {"disposition": "UPHELD_WITH_REVISION", "objection_valid": True, "rationale": "r", "decisive_evidence": [anchor.id],
                             "inadmissible_refs": [], "facts": [], "inferences": [], "unverified_assumptions": [], "remedy_assessment": "ok",
                             "open_question": None, "escalate": False},
        C.ROLE_EDITORIAL: {"revised_comment": "البند لا يحدد الإجراء.\nالتوصية: تحديد الإجراء المطلوب والجهة المنفذة.", "finding_part": "f",
                           "recommendation_part": "r", "proposed_title": "تحديد الإجراء المطلوب", "changes": ["c"], "preserved_references": [],
                           "house_style": {"finding_before_recommendation": True, "no_accusation": True, "action_labelled": True,
                                           "within_word_ceiling": True}, "requires_human_approval": True},
        C.ROLE_FINAL: FINAL_READY,
    }
    runner = AgentRunner(MockAdapter(script=script), TraceWriter(tmp_path / "trace.jsonl"))
    ex = ReviewOrchestrator(idx, runner=runner, gate_dir=tmp_path / "gate").execute(st, full)
    dispositions = [(o.kind, o.disposition) for e in ex.record.entries for o in e.objections]
    assert dispositions == [("UNCLEAR_ACTION", "UPHELD_WITH_REVISION")]
    assert ex.record.independence == INDEPENDENCE_MOCK and ex.modes() == {"MOCK": len(ex.role_outcomes)}
    execs = [o["execution_id"] for o in ex.role_outcomes]
    assert len(execs) == len(set(execs)) and all(execs)
    assert ex.status == "CLEAR" and len(ex.editorial_candidates) == 1
    assert ex.editorial_candidates[0]["candidate"]["requires_human_approval"] is True
    assert ex.trace_summary["actual_live_inference_count"] == 0 and ex.trace_summary["by_mode"]["MOCK"] == len(ex.role_outcomes)
    assert ex.exchanges and list(ex.exchanges.values())[0]["productive_cycles"] == 2
    assert ex.final_review["mode"] == C.MODE_MOCK and ex.final_review["recommendation"] == "READY"
    auth = G.authorize(st, tmp_path / "gate")
    assert auth.ok, auth.reasons                      # demo document + synthetic reference: the gate may clear
    # the same pipeline on an institutional (non-demo) document is never issuable on a synthetic reference
    st_inst = _state(demo=False)
    full_inst = build_reviewed_doc(st_inst, tmp_path / "inst.docx")
    with pytest.raises(DataHandlingViolation):
        AgentRunner(AnthropicAdapter(ProviderConfig(provider="anthropic")), TraceWriter()).run(
            C.ROLE_BLACK, "s", CB.black_team_payload(st_inst, st_inst.ordered()[0], reg, RecipientPersona.from_index(idx, DEPT, reg), issued=False))


def test_orchestrator_provider_failure_blocks_and_never_approves(tmp_path):
    st = _state()
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    script = {C.ROLE_BLACK: _objection_script(), C.ROLE_FINAL: FINAL_READY}
    for failing in (C.ROLE_RED, C.ROLE_ADJUDICATOR, C.ROLE_BLACK):
        runner = AgentRunner(MockAdapter(script=script, fail_roles={failing}), TraceWriter())
        ex = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / f"gate-{failing}").execute(st, full) \
            if False else ReviewOrchestrator(synthetic_reference_index(), runner=runner, gate_dir=tmp_path / f"gate-{failing}").execute(st, full)
        assert ex.provider_failures >= 1 and ex.status == "BLOCKED"
        assert all(b["disposition"] == "ESCALATED_TO_GCO_REVIEWER" for b in ex.blockers)
        reasons = G.authorize(st, tmp_path / f"gate-{failing}").reasons
        assert any(r.startswith(G.R_PROVIDER_FAILURE) for r in reasons)


def test_editorial_candidate_is_proposed_not_applied(tmp_path):
    st = _state()
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    idx = synthetic_reference_index()
    reg = EvidenceRegistry(); reg.add_document_text(full); reg.add_reference_index(idx)
    obs = st.ordered()[0]
    before = obs.comment.text
    cand, out = R.run_editorial(None, st, obs, [{"revised_comment": "نص منقح.\nالتوصية: إجراء محدد.", "disposition": "UPHELD_WITH_REVISION"}], reg)
    assert cand["requires_human_approval"] is True and cand["candidate_status"] == "PROPOSED_FOR_HUMAN_REVIEW"
    assert cand["revised_comment"].startswith("نص منقح") and obs.comment.text == before
    assert cand["house_style"]["action_labelled"] and cand["proposed_title"] == "", "no engine extract is ever proposed as a title"
