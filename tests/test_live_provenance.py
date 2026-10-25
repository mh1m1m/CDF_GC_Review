"""TEST 41 — live-inference provenance assurance (ChatGPT directive after PR #3 review, P0).

Receipt shape and self-reported provider identity are not evidence of live inference. The runner derives the
execution source from the adapter object it was built with (``agents/provenance.py``); only PROVIDER_API with a
provider-originated request id counts, the trace is a hash chain whose head is named by the gate record and the
attestation, and every receipt is bound to the run, the review-state fingerprint and the role's own instructions.

The *trusted test adapter* used for positive paths is registered only by a pytest monkeypatch of
``provenance.trusted_live_adapter_types``; production code registers the Anthropic adapter alone. Nothing here
is a live inference, and no test here can make the production counter say otherwise.
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
from cdf_gco_crms.agents import provenance as PV  # noqa: E402
from cdf_gco_crms.agents.orchestrator import INDEPENDENCE_LIVE, INDEPENDENCE_LIVE_UNVERIFIED, ReviewOrchestrator  # noqa: E402
from cdf_gco_crms.agents.providers import CachedAdapter, ProviderConfig  # noqa: E402
from cdf_gco_crms.agents.providers.anthropic_adapter import AnthropicAdapter  # noqa: E402
from cdf_gco_crms.agents.providers.base import ProviderResult  # noqa: E402
from cdf_gco_crms.references.synthetic_index import synthetic_reference_index  # noqa: E402
from cdf_gco_crms.release import attestation as ATT  # noqa: E402
from cdf_gco_crms.release import authorization_gate as G  # noqa: E402
from test_release_attestation import Attestor, SimulatedLiveAdapter, TrustedTestAdapter, _script, _state, trusted  # noqa: E402,F401
from test_word_lifecycle import build_reviewed_doc  # noqa: E402

SYN = {"label": "SYNTHETIC_TEST_CASE"}
NO_OBJ = {"material_objection": False, "objection_kind": "NO_MATERIAL_OBJECTION", "challenged_claim": "", "proposition": "",
          "material_consequence": "", "evidence_refs": [], "existing_controls": [], "requested_correction": "",
          "reasoning_summary": "لا اعتراض جوهري.", "evidence_limitations": "", "confidence": 0.8}


def _run(tmp_path, adapter, attestor=None, gate="gate", demo=False, code="ATT"):
    st = _state(demo=demo, code=code)
    docx = build_reviewed_doc(st, tmp_path / f"{gate}.docx")
    runner = AgentRunner(adapter, TraceWriter(tmp_path / f"{gate}-trace.jsonl"))
    ex = ReviewOrchestrator(synthetic_reference_index(), runner=runner, gate_dir=tmp_path / gate).execute(
        st, docx, attestation_key=attestor.key if attestor else None)
    return st, docx, ex


def _reasons(st, docx, tmp_path, store, gate="gate"):
    return G.authorize(st, tmp_path / gate, trust_store=store, source_document_sha256=G.sha256_file(docx)).reasons


# ------------------------------------------------------------------ classification
def test_execution_source_is_derived_from_the_adapter_object_not_from_labels():
    assert PV.classify_adapter(None) == PV.SOURCE_DETERMINISTIC
    assert PV.classify_adapter(MockAdapter()) == PV.SOURCE_MOCK
    assert PV.classify_adapter(SimulatedLiveAdapter({})) == PV.SOURCE_SIMULATED_LIVE
    assert PV.classify_adapter(AnthropicAdapter(ProviderConfig(provider="anthropic"))) == PV.SOURCE_PROVIDER_API
    assert PV.classify_adapter(AnthropicAdapter(ProviderConfig(provider="anthropic"), client=object())) == PV.SOURCE_PROVIDER_API_UNTRUSTED

    class Sub(AnthropicAdapter):            # a subclass that could override complete() is not the registered adapter
        pass
    assert PV.classify_adapter(Sub(ProviderConfig(provider="anthropic"))) == PV.SOURCE_SIMULATED_LIVE


def test_regression_simulated_live_adapter_cannot_increase_actual_live_inference_count(tmp_path):
    runner = AgentRunner(SimulatedLiveAdapter({C.ROLE_BLACK: NO_OBJ}), TraceWriter(tmp_path / "t.jsonl"))
    for _ in range(3):
        resp = runner.run(C.ROLE_BLACK, "s", SYN)
        assert resp.status == C.STATUS_OK and resp.mode == C.MODE_LIVE and resp.provider == "anthropic"
        assert resp.execution_source == PV.SOURCE_SIMULATED_LIVE and not resp.is_live and resp.provider_request_id is None
    s = runner.trace.summary()
    assert s["actual_live_inference_count"] == 0 and s["simulated_live_count"] == 3 and s["by_mode"]["LIVE"] == 3
    rec = json.loads((tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["Execution_Source"] == PV.SOURCE_SIMULATED_LIVE and rec["Provider_Request_ID"] is None
    assert ATT.receipt_problems(rec, role=C.ROLE_BLACK) and any(ATT.R_RECEIPT_SOURCE in p for p in ATT.receipt_problems(rec, role=C.ROLE_BLACK))


def test_cached_replay_and_failed_calls_never_count_as_live(tmp_path):
    cache = tmp_path / "cache.json"
    req = C.AgentRequest(C.ROLE_BLACK, "s", SYN, C.BLACK_TEAM_SCHEMA)
    cache.write_text(json.dumps({req.prompt_hash: {"text": json.dumps(NO_OBJ), "model": "m", "invocation_id": "msg_live1",
                                                   "stop_reason": "end_turn", "recorded_mode": "LIVE"}}), encoding="utf-8")
    runner = AgentRunner(CachedAdapter(cache), TraceWriter())
    resp = runner.run(C.ROLE_BLACK, "s", SYN)
    assert resp.ok and resp.execution_source == PV.SOURCE_CACHED and not resp.is_live
    assert runner.trace.summary()["actual_live_inference_count"] == 0 and runner.trace.summary()["cached_replay_count"] == 1
    failed = AgentRunner(MockAdapter(fail_roles={C.ROLE_BLACK}), TraceWriter()).run(C.ROLE_BLACK, "s", SYN)
    assert failed.execution_source == PV.SOURCE_FAILED


# ------------------------------------------------------------------ the ten negative cases
def test_n1_simulated_live_adapter_is_not_independent_and_does_not_issue(tmp_path):
    att = Attestor()
    st, docx, ex = _run(tmp_path, SimulatedLiveAdapter(_script()), att)
    assert ex.record.independence == INDEPENDENCE_LIVE_UNVERIFIED and not ex.independence["verified"]
    assert ex.independence["execution_source"] == PV.SOURCE_SIMULATED_LIVE and ex.trace_summary["actual_live_inference_count"] == 0
    r = _reasons(st, docx, tmp_path, att.store())
    assert any(r_.startswith(G.R_FINAL_REVIEW_NOT_LIVE) for r_ in r) and any(ATT.R_RECEIPT_SOURCE in r_ for r_ in r)
    assert any(r_.startswith(G.R_INDEPENDENCE_NOT_VERIFIED) for r_ in r)


def test_n2_forged_provider_invocation_id_is_not_evidence(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _run(tmp_path, trusted(_script()), att)
    assert ex.record.independence == INDEPENDENCE_LIVE and ex.independence["verified"]
    assert _reasons(st, docx, tmp_path, att.store()) == [G.R_SYNTHETIC]
    # a mock whose invocation ids are forged to the provider shape still carries no provider request id and a MOCK source
    class Forged(MockAdapter):
        def complete(self, request):
            res = super().complete(request)
            return ProviderResult(res.text, "msg_01ForgedLooksReal", "claude-opus-5-5", res.usage, res.stop_reason)
    st2, docx2, ex2 = _run(tmp_path, Forged(script=_script()), att, gate="gate2")
    assert not ex2.independence["verified"] and ex2.trace_summary["actual_live_inference_count"] == 0
    assert any(ATT.R_ROLE_NOT_LIVE in x for x in ex2.independence["reasons"])        # a MOCK stays MOCK whatever ids it forges
    trace = ATT.load_trace(ex2.gate_record["trace_path"])
    assert all(r["Execution_Source"] == PV.SOURCE_MOCK and r["Provider_Request_ID"] is None and r["Invocation_ID"].startswith("msg_") for r in trace)
    assert all(ATT.R_RECEIPT_SOURCE in "|".join(ATT.receipt_problems(r, role=r["Agent_Role"])) for r in trace)


def test_n3_modified_execution_trace_breaks_the_chain(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _run(tmp_path, trusted(_script()), att)
    tp = Path(ex.gate_record["trace_path"])
    lines = tp.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0]); rec["Execution_Status"] = "OK"; rec["Token_Usage"]["input_tokens"] = 9999
    lines[0] = json.dumps(rec, ensure_ascii=False)
    tp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = _reasons(st, docx, tmp_path, att.store())
    assert any(ATT.R_TRACE_CHAIN in x for x in r)
    # a trace rewritten consistently (re-chained) no longer matches the head the record and attestation name
    records = [json.loads(l) for l in lines]
    prev = PV.GENESIS
    for rec in records:
        rec["prev_hash"] = prev; rec["line_hash"] = PV.line_hash(rec); prev = rec["line_hash"]
    tp.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in records) + "\n", encoding="utf-8")
    r = _reasons(st, docx, tmp_path, att.store())
    assert any(ATT.R_TRACE_HEAD in x for x in r)


def test_n4_replay_of_a_cached_response_is_not_a_new_inference(tmp_path, trusted):
    from cdf_gco_crms.agents.providers import RecordingAdapter
    cache = tmp_path / "cache.json"
    rec_adapter = RecordingAdapter(trusted(_script()), cache)
    st, docx, ex = _run(tmp_path, rec_adapter, gate="gate-rec")
    assert ex.independence["verified"] and ex.trace_summary["actual_live_inference_count"] > 0
    # A replay requires the *same* prompt hash. A new end-to-end review may
    # legitimately alter its contextual payload, so re-use one exact recorded
    # request instead of presuming that two separate runs have identical inputs.
    original_request = rec_adapter.inner.calls[0]
    replay_runner = AgentRunner(CachedAdapter(cache), TraceWriter(tmp_path / "cached-exact-replay.jsonl"))
    response = replay_runner.run(original_request.role, original_request.system, original_request.payload,
                                 schema=original_request.schema, agent_id=original_request.agent_id,
                                 model=original_request.model)
    assert response.status == "OK" and response.execution_source == PV.SOURCE_CACHED
    summary = replay_runner.trace.summary()
    assert summary["actual_live_inference_count"] == 0 and summary["cached_replay_count"] == 1
    trace = replay_runner.trace.records
    assert all(r["Execution_Source"] == PV.SOURCE_CACHED for r in trace)
    assert all(ATT.R_RECEIPT_SOURCE in "|".join(ATT.receipt_problems(r, role=r["Agent_Role"])) for r in trace)


def test_n5_duplicate_provider_request_ids_do_not_establish_independence(tmp_path, trusted):
    class SameRequest(trusted):
        def complete(self, request):
            res = super().complete(request)
            return ProviderResult(res.text, res.invocation_id, res.model, res.usage, res.stop_reason, provider_request_id="req_same")
    # a subclass is no longer the registered class: it is SIMULATED_LIVE by construction …
    st, docx, ex = _run(tmp_path, SameRequest(_script()))
    assert not ex.independence["verified"]
    # … and even if it were trusted, repeated provider request ids are refused by the classifier
    trace = ATT.load_trace(ex.gate_record["trace_path"])
    for r in trace:
        r["Execution_Source"] = PV.SOURCE_PROVIDER_API
    outcomes = ex.role_outcomes
    v = ATT.verify_live_roles(outcomes, trace, run_id=ex.run_id, fingerprint=ex.fingerprint)
    assert ATT.R_PROVIDER_IDS_NOT_UNIQUE in v["reasons"] or any(ATT.R_TRACE_CHAIN in x for x in v["reasons"])


def test_n6_incorrect_provider_identity_is_refused(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _run(tmp_path, trusted(_script()), att)
    trace = ATT.load_trace(ex.gate_record["trace_path"])
    for r in trace:
        r["Provider"] = "someone-else"
    v = ATT.verify_live_roles(ex.role_outcomes, trace, run_id=ex.run_id, fingerprint=ex.fingerprint)
    assert any(ATT.R_RECEIPT_PROVIDER in x for x in v["reasons"]) and any(ATT.R_TRACE_CHAIN in x for x in v["reasons"])


def test_n7_missing_provider_response_evidence_is_refused(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _run(tmp_path, trusted(_script()), att)
    trace = ATT.load_trace(ex.gate_record["trace_path"])
    for r in trace:
        r["Provider_Request_ID"] = None
    v = ATT.verify_live_roles(ex.role_outcomes, trace, run_id=ex.run_id, fingerprint=ex.fingerprint)
    assert any(ATT.R_RECEIPT_REQUEST_ID in x for x in v["reasons"])


def test_n8_stale_receipt_from_another_run_is_refused(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _run(tmp_path, trusted(_script()), att)
    trace = ATT.load_trace(ex.gate_record["trace_path"])
    v = ATT.verify_live_roles(ex.role_outcomes, trace, run_id="RUN-other", fingerprint=ex.fingerprint, expected_head=ex.gate_record["trace_head_hash"])
    assert any(ATT.R_RECEIPT_RUN in x for x in v["reasons"])
    p = G.gate_record_path(ex.fingerprint, tmp_path / "gate")
    rec = json.loads(p.read_text(encoding="utf-8")); rec["execution_summary"]["run_id"] = "RUN-other"
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    r = _reasons(st, docx, tmp_path, att.store())
    assert any(ATT.R_RECEIPT_RUN in x for x in r)


def test_n9_cross_document_receipt_reuse_is_refused(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _run(tmp_path, trusted(_script()), att)
    st2, docx2, ex2 = _run(tmp_path, trusted(_script()), att, gate="gate2", demo=False, code="OTH")   # another document
    # point the second record at the first run's trace: every receipt is bound to the first fingerprint
    p = G.gate_record_path(ex2.fingerprint, tmp_path / "gate2")
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["trace_path"] = ex.gate_record["trace_path"]; rec["trace_head_hash"] = ex.gate_record["trace_head_hash"]
    rec["final_review"]["execution_id"] = ex.final_review["execution_id"]; rec["execution_summary"]["run_id"] = ex.run_id
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    r = G.authorize(st2, tmp_path / "gate2", trust_store=att.store(), source_document_sha256=G.sha256_file(docx2)).reasons
    assert any(ATT.R_RECEIPT_FINGERPRINT in x for x in r) or any(ATT.R_RECEIPT_RUN in x for x in r)
    assert any(x.startswith(G.R_ATTESTATION_INVALID) for x in r)


def test_n10_valid_attestor_signature_over_false_execution_metadata_does_not_issue(tmp_path):
    """The attestor signs what the record says; the gate still checks what the trace proves."""
    att = Attestor()
    st, docx, ex = _run(tmp_path, SimulatedLiveAdapter(_script()), att)
    p = G.gate_record_path(ex.fingerprint, tmp_path / "gate")
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["independence"] = {"verified": True, "reasons": [], "live_executions": 7, "execution_source": "PROVIDER_API"}
    rec["final_review"]["execution_source"] = "PROVIDER_API"
    payload = ATT.build_payload(rec, purpose=ATT.PURPOSE_INSTITUTIONAL)
    rec["attestation"] = ATT.sign(payload, att.raw, att.key_id).to_dict()
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    r = _reasons(st, docx, tmp_path, att.store())
    assert not any(x.startswith(G.R_ATTESTATION_INVALID) for x in r), "the signature itself is valid over the false record"
    assert any(x.startswith(G.R_FINAL_REVIEW_RECEIPT) and ATT.R_RECEIPT_SOURCE in x for x in r), "the receipt check is independent of the signature"
    assert G.R_SYNTHETIC in r


def test_runner_binds_role_context_and_fingerprint_into_every_receipt(tmp_path, trusted):
    st, docx, ex = _run(tmp_path, trusted(_script()))
    trace = ATT.load_trace(ex.gate_record["trace_path"])
    assert all(r["Review_State_Fingerprint"] == ex.fingerprint and r["Run_ID"] == ex.run_id for r in trace)
    assert all(r["System_Hash"] == ATT.expected_system_hash(r["Agent_Role"]) for r in trace if r["Agent_Role"] in ATT.CHALLENGE_ROLES)
    ok, head, _ = PV.verify_chain(trace)
    assert ok and head == ex.gate_record["trace_head_hash"] == ex.trace_summary["trace_head_hash"]
    assert set(trace[0]["Provider_Originated"]) == {"Invocation_ID", "Provider_Request_ID", "Model", "Token_Usage"}
