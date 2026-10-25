"""TEST 40 — PR #3 review remediation (Directives 1–4): live final-review receipts, mandatory source binding,
independence verified from receipts, signed release attestation.

A *simulated live provider* is used for the positive path: an adapter that reports the LIVE mode, the provider
name and provider-shaped invocation ids of a real deployment while returning scripted JSON. It exists only to
exercise the verification logic end to end; it is never a live inference and the tests say so. Every key is an
ephemeral synthetic key generated in the test.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import main as CLI  # noqa: E402
from cdf_gco_crms.agents import AgentRunner, MockAdapter, TraceWriter  # noqa: E402
from cdf_gco_crms.agents import contracts as C  # noqa: E402
from cdf_gco_crms.agents.orchestrator import INDEPENDENCE_LIVE, INDEPENDENCE_LIVE_UNVERIFIED, INDEPENDENCE_MOCK, ReviewOrchestrator  # noqa: E402
from cdf_gco_crms.agents.providers.base import ProviderConfig, ProviderResult  # noqa: E402
from cdf_gco_crms.assurance.evidence import EvidenceRegistry  # noqa: E402
from cdf_gco_crms.ingestion.workbook_reader import parse_workbook  # noqa: E402
from cdf_gco_crms.model.entities import Document  # noqa: E402
from cdf_gco_crms.references.synthetic_index import synthetic_reference_index  # noqa: E402
from cdf_gco_crms.release import attestation as ATT  # noqa: E402
from cdf_gco_crms.release import authorization_gate as G  # noqa: E402
from cdf_gco_crms.release import trust as T  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import build_round1  # noqa: E402
from conftest import base_obs  # noqa: E402
from test_word_lifecycle import build_reviewed_doc  # noqa: E402

DEPT = "الحوكمة والامتثال"
NOW = dt.datetime(2026, 10, 24, 14, 0, tzinfo=dt.timezone.utc)
NO_OBJ = {"material_objection": False, "objection_kind": "NO_MATERIAL_OBJECTION", "challenged_claim": "", "proposition": "",
          "material_consequence": "", "evidence_refs": [], "existing_controls": [], "requested_correction": "",
          "reasoning_summary": "لا اعتراض جوهري.", "evidence_limitations": "", "confidence": 0.8}
FINAL_READY = {"release_recommendation": "READY", "findings": [], "unresolved_critical_objections": [], "contradictions": [],
               "jurisdiction_consistent": True, "unsupported_or_excessive": [], "summary": "ok"}


class TrustedTestAdapter(MockAdapter):
    """Stands in for the registered provider class ONLY while a test monkeypatches
    ``provenance.trusted_live_adapter_types`` (the ``trusted`` fixture). Scripted JSON with provider-originated-
    looking ids (message id, request id). Production code never registers it; it is not a live inference."""
    name = "anthropic"
    mode = C.MODE_LIVE
    endpoint = "https://api.anthropic.com"   # the pinned official endpoint the provenance registry requires

    def __init__(self, script):
        super().__init__(ProviderConfig(provider="anthropic", model="claude-opus-5-5-test",
                                        data_authorization="INSTITUTIONAL_AUTHORIZED:TEST-SIMULATION"), script=script)

    def complete(self, request):
        res = super().complete(request)
        return ProviderResult(res.text, f"msg_t{self._n:06d}", self.model, res.usage, res.stop_reason, refused=res.refused,
                              refusal_category=res.refusal_category, provider_request_id=f"req_t{self._n:06d}")


@pytest.fixture
def trusted(monkeypatch):
    from cdf_gco_crms.agents import provenance as PV
    monkeypatch.setattr(PV, "trusted_live_adapter_types", lambda: (TrustedTestAdapter,))
    return TrustedTestAdapter


class SimulatedLiveAdapter(MockAdapter):
    """Scripted responses that *declare* the shape of a live deployment (mode LIVE, provider 'anthropic', 'msg_'
    invocation ids) without being the registered adapter: the provenance layer classifies it SIMULATED_LIVE and
    nothing it produces counts as live inference (tests/test_live_provenance.py)."""
    name = "anthropic"
    mode = C.MODE_LIVE

    def __init__(self, script):
        super().__init__(ProviderConfig(provider="anthropic", model="claude-opus-5-5-simulated",
                                        data_authorization="INSTITUTIONAL_AUTHORIZED:TEST-SIMULATION"), script=script)

    def complete(self, request):
        res = super().complete(request)
        return ProviderResult(res.text, f"msg_sim{self._n:06d}", self.model, res.usage, res.stop_reason,
                              refused=res.refused, refusal_category=res.refusal_category)


def _state(demo=False, n=3, code="ATT"):
    doc = Document(name="وثيقة الإثبات", code=code, owning_department=DEPT, is_demo=demo)
    return build_round1(doc, base_obs(n), date="2026-02-15", document_version="الإصدار 0.1")


def _script(target_reader="02"):
    def black(p):
        first = p["observation"]["reader_no"] == target_reader and not p.get("prior_exchange")
        return {**NO_OBJ, "material_objection": first, "objection_kind": "UNCLEAR_ACTION" if first else "NO_MATERIAL_OBJECTION",
                "proposition": "التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ." if first else "",
                "material_consequence": "تعذر التنفيذ", "evidence_refs": p["evidence"][:1] and [p["evidence"][0]["id"]],
                "requested_correction": "تحديد الإجراء"}
    return {C.ROLE_BLACK: black,
            C.ROLE_RED: lambda p: {"stance": "REVISE", "objection_accepted": True, "reasoning": "تُراجع الصياغة لتحديد الإجراء.",
                                   "evidence_refs": [p["evidence"][0]["id"]] if p["evidence"] else [],
                                   "revised_comment": "البند لا يحدد الإجراء.\nالتوصية: تحديد الإجراء المطلوب والجهة المنفذة.",
                                   "revised_quote": None, "route_to": None, "missing_evidence": [], "escalate": False, "new_argument": True},
            C.ROLE_ADJUDICATOR: lambda p: {"disposition": "UPHELD_WITH_REVISION", "objection_valid": True, "rationale": "r",
                                           "decisive_evidence": [p["evidence"][0]["id"]] if p["evidence"] else [], "inadmissible_refs": [],
                                           "facts": [], "inferences": [], "unverified_assumptions": [], "remedy_assessment": "ok",
                                           "open_question": None, "escalate": False},
            C.ROLE_EDITORIAL: {"revised_comment": "البند لا يحدد الإجراء.\nالتوصية: تحديد الإجراء المطلوب والجهة المنفذة.", "finding_part": "f",
                               "recommendation_part": "r", "proposed_title": "تحديد الإجراء", "changes": ["c"], "preserved_references": [],
                               "house_style": {"finding_before_recommendation": True, "no_accusation": True, "action_labelled": True,
                                               "within_word_ceiling": True}, "requires_human_approval": True},
            C.ROLE_FINAL: FINAL_READY}


class Attestor:
    def __init__(self, key_id="INST-ATTESTOR-001", *, synthetic=False, roles=(ATT.ROLE_ATTESTOR,)):
        self.key_id = key_id
        self.priv = Ed25519PrivateKey.generate()
        self.raw = self.priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        self.pub = self.priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.synthetic, self.roles = synthetic, roles

    def store(self, *, status=T.STATUS_ACTIVE) -> T.TrustStore:
        s = T.TrustStore()
        s.keys[self.key_id] = T.KeyEntry(self.key_id, self.pub, status, tuple(self.roles), "institutional attestor", synthetic=self.synthetic)
        return s

    @property
    def key(self):
        return (self.raw, self.key_id)


def _institutional_run(tmp_path, *, adapter, attestor=None, demo=False, gate="gate"):
    st = _state(demo=demo)
    docx = build_reviewed_doc(st, tmp_path / "case.docx")
    runner = AgentRunner(adapter, TraceWriter(tmp_path / f"{gate}-trace.jsonl"))
    ex = ReviewOrchestrator(synthetic_reference_index(), runner=runner, gate_dir=tmp_path / gate).execute(
        st, docx, now=NOW, attestation_key=attestor.key if attestor else None)
    return st, docx, ex


def _authorize(st, docx, tmp_path, store, *, gate="gate", now=NOW, source=True):
    return G.authorize(st, tmp_path / gate, trust_store=store, now=now,
                       source_document_sha256=G.sha256_file(docx) if source else None)


# ================================================================== the positive institutional path
def test_institutional_issue_clears_only_with_live_receipts_source_hash_and_attestation(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=att)
    assert ex.status == "CLEAR" and ex.record.independence == INDEPENDENCE_LIVE and ex.independence["verified"]
    assert ex.final_review["mode"] == "LIVE" and ex.final_review["execution_source"] == "PROVIDER_API"
    assert ex.attestation and ex.gate_record["purpose"] == G.PURPOSE_INSTITUTIONAL
    # a SYNTHETIC reference index still blocks a non-demo document: the remaining reason must be exactly that one
    auth = _authorize(st, docx, tmp_path, att.store())
    assert auth.reasons == [G.R_SYNTHETIC], auth.reasons


def test_simulated_live_adapter_never_clears_an_institutional_issue(tmp_path):
    att = Attestor()
    st, docx, ex = _institutional_run(tmp_path, adapter=SimulatedLiveAdapter(_script()), attestor=att)
    assert ex.trace_summary["actual_live_inference_count"] == 0 and ex.trace_summary["simulated_live_count"] == len(ex.role_outcomes)
    assert not ex.independence["verified"] and ex.record.independence != INDEPENDENCE_LIVE
    r = _authorize(st, docx, tmp_path, att.store()).reasons
    assert any(x.startswith(G.R_FINAL_REVIEW_NOT_LIVE) for x in r) and any(x.startswith(G.R_INDEPENDENCE_NOT_VERIFIED) for x in r)


def test_demo_document_keeps_the_previous_rules(tmp_path):
    st, docx, ex = _institutional_run(tmp_path, demo=True, adapter=MockAdapter(script=_script()))
    assert ex.record.independence == INDEPENDENCE_MOCK
    assert G.authorize(st, tmp_path / "gate").ok, "a demo document needs no live receipt, source hash or attestation"


# ================================================================== Directive 1 — final reviewer assurance
def test_d1_deterministic_ready_never_satisfies_an_institutional_final_review(tmp_path):
    st = _state(demo=False)
    docx = build_reviewed_doc(st, tmp_path / "case.docx")
    ex = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, docx)
    assert ex.final_review["recommendation"] == "READY" and ex.final_review["mode"] == "DETERMINISTIC"
    reasons = _authorize(st, docx, tmp_path, T.TrustStore()).reasons
    assert any(r.startswith(G.R_FINAL_REVIEW_NOT_LIVE) for r in reasons)
    assert any(r.startswith(G.R_FINAL_REVIEW_RECEIPT) for r in reasons)
    assert G.R_ATTESTATION_MISSING in reasons and any(r.startswith(G.R_INDEPENDENCE_NOT_VERIFIED) for r in reasons)


def test_d1_mock_ready_never_satisfies_an_institutional_final_review(tmp_path):
    st, docx, ex = _institutional_run(tmp_path, adapter=MockAdapter(script=_script()))
    assert ex.final_review["mode"] == "MOCK" and ex.final_review["recommendation"] == "READY"
    reasons = _authorize(st, docx, tmp_path, T.TrustStore()).reasons
    assert any(r.startswith(G.R_FINAL_REVIEW_NOT_LIVE) for r in reasons)
    assert any("EXECUTION_RECEIPT_NOT_LIVE" in r or "PROVIDER_NOT_LIVE" in r for r in reasons)


def test_d1_forged_live_metadata_without_receipt_is_refused(tmp_path):
    att = Attestor()
    st, docx, ex = _institutional_run(tmp_path, adapter=MockAdapter(script=_script()), attestor=att)
    p = G.gate_record_path(ex.fingerprint, tmp_path / "gate")
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["final_review"]["mode"] = "LIVE"                     # the label is forged; the trace still says MOCK
    rec["independence"] = {"verified": True, "reasons": [], "live_executions": 9}
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    reasons = _authorize(st, docx, tmp_path, att.store()).reasons
    assert any(r.startswith(G.R_FINAL_REVIEW_RECEIPT) and "EXECUTION_RECEIPT_NOT_LIVE" in r for r in reasons)
    assert any(r.startswith(G.R_ATTESTATION_INVALID) for r in reasons), "the attestation no longer matches the edited record"


def test_d1_missing_execution_receipt_is_refused(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=att)
    Path(ex.gate_record["trace_path"]).unlink()              # the receipt file is gone
    reasons = _authorize(st, docx, tmp_path, att.store()).reasons
    assert any(r.startswith(G.R_FINAL_REVIEW_RECEIPT) and ATT.R_RECEIPT_MISSING in r for r in reasons)


def test_d1_final_review_bound_to_another_review_state_is_refused(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=att)
    p = G.gate_record_path(ex.fingerprint, tmp_path / "gate")
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["final_review"]["fingerprint"] = "0" * 64
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    reasons = _authorize(st, docx, tmp_path, att.store()).reasons
    assert G.R_FINAL_REVIEW_STATE in reasons and any(r.startswith(G.R_ATTESTATION_INVALID) for r in reasons)


def test_d1_failed_or_refused_final_review_inference_is_refused(tmp_path):
    for kind in ("fail", "refuse"):
        adapter = SimulatedLiveAdapter(_script())      # failure/refusal paths need no trusted provenance
        (adapter.fail_roles if kind == "fail" else adapter.refuse_roles).add(C.ROLE_FINAL)
        att = Attestor()
        st, docx, ex = _institutional_run(tmp_path, adapter=adapter, attestor=att, gate=f"gate-{kind}")
        assert ex.final_review["status"] in ("PROVIDER_FAILURE", "REFUSED") and ex.provider_failures >= 1
        reasons = G.authorize(st, tmp_path / f"gate-{kind}", trust_store=att.store(), now=NOW, source_document_sha256=G.sha256_file(docx)).reasons
        assert G.R_FINAL_REVIEW_MISSING in reasons and any(r.startswith(G.R_PROVIDER_FAILURE) for r in reasons)


# ================================================================== Directive 2 — mandatory source binding
def test_d2_omitting_the_source_hash_cannot_bypass_the_binding(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=att)
    reasons = _authorize(st, docx, tmp_path, att.store(), source=False).reasons
    assert G.R_SOURCE_DOCUMENT_REQUIRED in reasons
    other = build_reviewed_doc(st, tmp_path / "other.docx", omit=(st.ordered()[0].internal_id,))   # a different document version
    reasons = G.authorize(st, tmp_path / "gate", trust_store=att.store(), now=NOW, source_document_sha256=G.sha256_file(other)).reasons
    assert G.R_SOURCE_DOCUMENT_MISMATCH in reasons
    p = G.gate_record_path(ex.fingerprint, tmp_path / "gate")
    rec = json.loads(p.read_text(encoding="utf-8")); rec["source_document_sha256"] = None
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    reasons = _authorize(st, docx, tmp_path, att.store()).reasons
    assert G.R_SOURCE_DOCUMENT_MISMATCH in reasons, "a record without a source hash cannot be issued institutionally"


def test_d2_cli_issue_requires_the_reviewed_document(tmp_path, capsys):
    spec = {"document": {"name": "وثيقة الإثبات", "code": "ATT", "cover_version": "الإصدار 0.1", "owning_department": DEPT, "is_demo": False},
            "date": "2026-02-15", "observations": [{"location": o.location, "quote": o.quote, "comment": [[s.text, s.bold] for s in o.comment.segments]}
                                                   for o in base_obs(3)]}
    (tmp_path / "r1.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    rc = CLI.main(["round1", str(tmp_path / "r1.json"), str(tmp_path / "out")]); out = capsys.readouterr().out
    wb = json.loads(out[out.index("{"):])["output"]
    st = parse_workbook(wb).state
    docx = build_reviewed_doc(st, tmp_path / "case.docx")
    rc = CLI.main(["review", wb, "--docx", str(docx), "--gate-dir", str(tmp_path / "gate"), "--synthetic-reference"]); capsys.readouterr()
    rc = CLI.main(["build-excel", wb, str(tmp_path / "issue"), "--gate-dir", str(tmp_path / "gate")]); out = capsys.readouterr().out
    rep = json.loads(out[out.index("{"):])
    assert rc == CLI.RC_REFUSED and G.R_SOURCE_DOCUMENT_REQUIRED in rep["gate"]["reasons"]
    rc = CLI.main(["build-excel", wb, str(tmp_path / "issue"), "--gate-dir", str(tmp_path / "gate"), "--docx", str(docx)]); out = capsys.readouterr().out
    rep = json.loads(out[out.index("{"):])
    assert rc == CLI.RC_REFUSED and G.R_SOURCE_DOCUMENT_REQUIRED not in rep["gate"]["reasons"]
    assert any(r.startswith(G.R_FINAL_REVIEW_NOT_LIVE) for r in rep["gate"]["reasons"]) and G.R_ATTESTATION_MISSING in rep["gate"]["reasons"]


# ================================================================== Directive 3 — independence from receipts
def test_d3_independence_requires_receipts_not_labels(tmp_path, trusted):
    st, docx, ex = _institutional_run(tmp_path, adapter=MockAdapter(script=_script()))
    assert ex.record.independence == INDEPENDENCE_MOCK and not ex.independence["verified"]
    # a run that labels its outcomes LIVE but whose trace holds MOCK receipts is LIVE_CLAIMED_NOT_VERIFIED
    forged = [dict(o, mode="LIVE") for o in ex.role_outcomes]
    v = ATT.verify_live_roles(forged, ex.registry and list(AgentRunner(MockAdapter(script=_script()), TraceWriter()).trace.records))
    assert not v["verified"] and any(ATT.R_RECEIPT_MISSING in r for r in v["reasons"])
    trace = ATT.load_trace(ex.gate_record["trace_path"])
    v2 = ATT.verify_live_roles(forged, trace)
    assert not v2["verified"] and any(ATT.R_RECEIPT_NOT_LIVE in r for r in v2["reasons"])
    # duplicate execution ids are refused even when every receipt verifies
    st2, docx2, ex2 = _institutional_run(tmp_path, adapter=trusted(_script()), gate="gate2")
    trace2 = ATT.load_trace(ex2.gate_record["trace_path"])
    kw = dict(run_id=ex2.run_id, fingerprint=ex2.fingerprint)
    dup = ex2.role_outcomes + [dict(ex2.role_outcomes[0])]
    assert ATT.R_IDS_NOT_UNIQUE in ATT.verify_live_roles(dup, trace2, **kw)["reasons"]
    # a missing required role is refused
    only_black = [o for o in ex2.role_outcomes if o["role"] == "BLACK_TEAM"]
    assert any(r.startswith(ATT.R_ROLE_MISSING) for r in ATT.verify_live_roles(only_black, trace2, **kw)["reasons"])
    # evidence ids outside the registry are refused
    assert any(r.startswith(ATT.R_EVIDENCE_UNKNOWN) for r in ATT.verify_live_roles(ex2.role_outcomes, trace2, registry_ids=set(), **kw)["reasons"])
    assert ex2.record.independence == INDEPENDENCE_LIVE and ex2.independence["verified"]


def test_d3_mixed_substitution_is_not_independent(tmp_path):
    adapter = SimulatedLiveAdapter(_script())
    adapter.fail_roles.add(C.ROLE_ADJUDICATOR)               # the adjudicator never answers: no substitution is made
    st, docx, ex = _institutional_run(tmp_path, adapter=adapter)
    assert ex.provider_failures >= 1 and ex.status == "BLOCKED"
    assert ex.record.independence in (INDEPENDENCE_LIVE_UNVERIFIED, "ISOLATED_LIVE_CONTEXTS") or not ex.independence["verified"] or ex.blockers


# ================================================================== Directive 4 — release attestation
def test_d4_attestation_rejections(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=att)
    gate = tmp_path / "gate"
    ok_reasons = _authorize(st, docx, tmp_path, att.store()).reasons
    assert ok_reasons == [G.R_SYNTHETIC]
    # unknown key
    r = _authorize(st, docx, tmp_path, Attestor("OTHER-KEY").store()).reasons
    assert any(ATT.R_ATT_KEY_UNKNOWN in x for x in r)
    r = _authorize(st, docx, tmp_path, Attestor(att.key_id).store()).reasons          # same id, different key
    assert any(ATT.R_ATT_SIGNATURE in x for x in r)
    # key without the attestor role
    r = _authorize(st, docx, tmp_path, Attestor(att.key_id, roles=("GCO reviewer",)).store()).reasons
    assert any(ATT.R_ATT_KEY_NOT_ATTESTOR in x and ATT.R_ATT_SIGNATURE in x for x in r)
    # revoked key
    revoked = att.store(); revoked.revoke(att.key_id)
    r = _authorize(st, docx, tmp_path, revoked).reasons
    assert any(ATT.R_ATT_KEY_INACTIVE in x for x in r)
    # synthetic attestor key never for institutional
    syn = Attestor("SYNTHETIC_ATTESTOR", synthetic=True)
    st_s, docx_s, ex_s = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=syn, gate="gate-syn")
    r = G.authorize(st_s, tmp_path / "gate-syn", trust_store=syn.store(), now=NOW, source_document_sha256=G.sha256_file(docx_s)).reasons
    assert any(ATT.R_ATT_KEY_SYNTHETIC in x for x in r)
    # expired
    r = _authorize(st, docx, tmp_path, att.store(), now=NOW + dt.timedelta(hours=ATT.DEFAULT_VALID_HOURS + 1)).reasons
    assert any(ATT.R_ATT_EXPIRED in x for x in r)
    # tampered payload
    p = G.gate_record_path(ex.fingerprint, gate)
    rec = json.loads(p.read_text(encoding="utf-8")); rec["attestation"]["payload"]["purpose"] = ATT.PURPOSE_INSTITUTIONAL
    rec["attestation"]["payload"]["valid_until"] = "2099-01-01T00:00:00+00:00"
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    r = _authorize(st, docx, tmp_path, att.store()).reasons
    assert any(ATT.R_ATT_SIGNATURE in x for x in r)
    # replayed for other content: the attestation of this run attached to another run's record
    st2, docx2, ex2 = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=None, gate="gate2")
    G.attach_attestation(ex2.fingerprint, ex.attestation, tmp_path / "gate2")
    r = G.authorize(st2, tmp_path / "gate2", trust_store=att.store(), now=NOW, source_document_sha256=G.sha256_file(docx2)).reasons
    assert any(ATT.R_ATT_RECORD in x or ATT.R_ATT_FINGERPRINT in x or ATT.R_ATT_FINAL_REVIEW in x for x in r)
    # a demo-purpose attestation presented for an institutional issue
    st3, docx3, ex3 = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=att, demo=True, gate="gate3")
    assert ex3.attestation["payload"]["purpose"] == ATT.PURPOSE_DEMO
    r = G.authorize(st3, tmp_path / "gate3", trust_store=att.store(), now=NOW, source_document_sha256=G.sha256_file(docx3),
                    purpose=G.PURPOSE_INSTITUTIONAL).reasons
    assert any(ATT.R_ATT_PURPOSE in x for x in r)
    # no self-granted authority: a record written without any attestation key
    st4, docx4, ex4 = _institutional_run(tmp_path, adapter=trusted(_script()), gate="gate4")
    assert G.R_ATTESTATION_MISSING in G.authorize(st4, tmp_path / "gate4", trust_store=att.store(), now=NOW,
                                                  source_document_sha256=G.sha256_file(docx4)).reasons


def test_d4_attestation_binds_human_decisions_and_proofs(tmp_path, trusted):
    att = Attestor()
    st, docx, ex = _institutional_run(tmp_path, adapter=trusted(_script()), attestor=att)
    p = G.gate_record_path(ex.fingerprint, tmp_path / "gate")
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["human_decisions"] = [{"decision_id": "D-FAKE", "signing_key_id": "x", "observation_id": "y"}]
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    r = _authorize(st, docx, tmp_path, att.store()).reasons
    assert any(ATT.R_ATT_DECISIONS in x for x in r)
    rec["human_decisions"] = []; rec["role_execution_proofs"] = rec["role_execution_proofs"][:-1]
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    r = _authorize(st, docx, tmp_path, att.store()).reasons
    assert any(ATT.R_ATT_PROOFS in x for x in r)


def test_attestation_key_file_round_trip(tmp_path):
    att = Attestor()
    (tmp_path / "k.b64").write_text(base64.b64encode(att.raw).decode(), encoding="utf-8")
    (tmp_path / "k.raw").write_bytes(att.raw)
    assert ATT.load_private_key(tmp_path / "k.b64") == att.raw == ATT.load_private_key(tmp_path / "k.raw")
    payload = ATT.build_payload({"fingerprint": "f", "source_document_sha256": "d", "challenge_record_sha256": "c"},
                                purpose=ATT.PURPOSE_INSTITUTIONAL, now=NOW)
    signed = ATT.sign(payload, att.raw, att.key_id)
    assert ATT.verify(signed.to_dict(), att.store(), now=NOW, fingerprint="f", document_sha256="d", challenge_record_sha256="c",
                      purpose=ATT.PURPOSE_INSTITUTIONAL) == []
