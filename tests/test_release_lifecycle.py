"""TEST 36 — release authorisation lifecycle (Articles 07, 08, 13.3): the ten mandatory negative tests, the
institutional trust store, decision expiry/revocation/binding, disposition application with ledger and rollback.
All keys are ephemeral synthetic keys generated in the test; nothing institutional is impersonated.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import sys
from dataclasses import replace
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
from cdf_gco_crms.agents.orchestrator import ReviewOrchestrator  # noqa: E402
from cdf_gco_crms.assurance.objection_engine import HumanDecision  # noqa: E402
from cdf_gco_crms.ingestion.workbook_reader import parse_workbook  # noqa: E402
from cdf_gco_crms.model.entities import Document, GText, plain_text  # noqa: E402
from cdf_gco_crms.references.synthetic_index import synthetic_reference_index  # noqa: E402
from cdf_gco_crms.release import authorization_gate as G  # noqa: E402
from cdf_gco_crms.release import trust as T  # noqa: E402
from cdf_gco_crms.release.dispositions import apply_dispositions, read_ledger, rollback  # noqa: E402
from cdf_gco_crms.rounds.round_expansion import build_round1  # noqa: E402
from conftest import base_obs  # noqa: E402
from test_word_lifecycle import build_reviewed_doc  # noqa: E402

DEPT = "الحوكمة والامتثال"
NOW = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.timezone.utc)
FINAL_READY = {"recommendation": "READY", "mode": "DETERMINISTIC", "status": "OK", "execution_id": None}


# ------------------------------------------------------------------ fixtures
class Signer:
    def __init__(self, key_id="INST-KEY-001", *, synthetic=False, roles=("GCO reviewer",)):
        self.key_id = key_id
        self.priv = Ed25519PrivateKey.generate()
        self.pub = self.priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.synthetic = synthetic
        self.roles = roles

    def store(self, *, status=T.STATUS_ACTIVE, valid_until=None, valid_from=None) -> T.TrustStore:
        store = T.TrustStore()
        store.keys[self.key_id] = T.KeyEntry(self.key_id, self.pub, status, tuple(self.roles), "م. مراجع تجريبي",
                                             valid_from, valid_until, self.synthetic)
        return store

    def decision(self, observation_id, outcome="WITHHELD_FOR_EVIDENCE", *, decision_id="D-1", fingerprint="", role="GCO reviewer",
                 timestamp="2026-10-24T10:00:00+00:00", valid_until=""):
        d = HumanDecision(decision_id, observation_id, outcome, "م. مراجع تجريبي", role, f"DEC-{decision_id}", timestamp,
                          f"E-{decision_id}", "VERIFIED_HUMAN_RECORD", self.key_id, "", fingerprint, valid_until)
        return replace(d, signature_b64=base64.b64encode(self.priv.sign(d.signature_payload())).decode())


def _state(demo=True, n=5, code="LCY"):
    doc = Document(name="وثيقة دورة الإصدار", code=code, owning_department=DEPT, is_demo=demo)
    return build_round1(doc, base_obs(n), date="2026-02-15", document_version="الإصدار 0.1")


def _blocked_execution(tmp_path, st, *, gate="gate"):
    """A deterministic review on a document that omits one clause: one WITHHELD blocker."""
    victim = st.ordered()[2].internal_id
    short = build_reviewed_doc(st, tmp_path / "short.docx", omit=(victim,))
    ex = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / gate).execute(st, short)
    assert ex.blockers and {b["internal_id"] for b in ex.blockers} == {victim}
    return ex, victim, short


# ------------------------------------------------------------------ trust store
def test_trust_store_formats_and_lifecycle_checks():
    s = Signer()
    store = s.store()
    d = s.decision("GCO-LCY-R1-003", fingerprint="f" * 64)
    assert store.check_decision(d, now=NOW, fingerprint="f" * 64) == []
    assert T.R_SIGNATURE in Signer().store().check_decision(d, now=NOW, fingerprint="f" * 64) or \
        T.R_KEY_UNKNOWN in Signer().store().check_decision(d, now=NOW, fingerprint="f" * 64)
    assert store.check_decision(d, now=NOW, fingerprint="0" * 64) == [T.R_STATE_BINDING]
    assert store.check_decision(s.decision("GCO-LCY-R1-003"), now=NOW, fingerprint="f" * 64) == [T.R_STATE_BINDING]
    assert store.check_decision(s.decision("GCO-LCY-R1-003"), now=NOW, fingerprint="f" * 64, institutional=False) == []
    assert store.check_decision(d, now=NOW + dt.timedelta(days=31), fingerprint="f" * 64) == [T.R_DECISION_EXPIRED]
    d2 = s.decision("GCO-LCY-R1-003", fingerprint="f" * 64, valid_until="2026-10-25T00:00:00+00:00")
    assert store.check_decision(d2, now=NOW, fingerprint="f" * 64) == [] and \
        store.check_decision(d2, now=NOW + dt.timedelta(days=2), fingerprint="f" * 64) == [T.R_DECISION_EXPIRED]
    store.revoke(s.key_id, "2026-10-24T11:00:00+00:00")
    assert T.R_KEY_REVOKED in store.check_decision(d, now=NOW, fingerprint="f" * 64)
    assert store.raw_keys() == {} and s.key_id in store.raw_keys(include_inactive=True)
    assert T.R_KEY_EXPIRED in s.store(valid_until="2026-01-01").check_decision(d, now=NOW, fingerprint="f" * 64)
    assert T.R_KEY_NOT_YET_VALID in s.store(valid_from="2026-12-01").check_decision(d, now=NOW, fingerprint="f" * 64)
    assert T.R_ROLE_NOT_PERMITTED in s.store().check_decision(s.decision("GCO-LCY-R1-003", fingerprint="f" * 64, role="Analyst"),
                                                              now=NOW, fingerprint="f" * 64)
    assert T.R_OBSERVATION_BINDING in store.check_decision(d, now=NOW, fingerprint="f" * 64, observation_id="GCO-LCY-R1-001")
    syn = Signer("SYNTHETIC_TEST_KEY", synthetic=True)
    assert T.R_SYNTHETIC_KEY in syn.store().check_decision(syn.decision("x-1", fingerprint="f" * 64), now=NOW, fingerprint="f" * 64)
    assert syn.store().check_decision(syn.decision("x-1", fingerprint="f" * 64), now=NOW, fingerprint="f" * 64, institutional=False) == []
    # legacy format round-trip and v2 persistence
    legacy = T.TrustStore.from_dict({s.key_id: base64.b64encode(s.pub).decode()})
    assert legacy.keys[s.key_id].legacy and legacy.raw_keys()[s.key_id] == s.pub
    again = T.TrustStore.from_dict(store.to_dict())
    assert again.keys[s.key_id].status == T.STATUS_REVOKED
    # a decision signed without the binding cannot be re-targeted: the fingerprint is part of the signature
    tampered = replace(d, review_state_fingerprint="0" * 64)
    with pytest.raises(PermissionError):
        tampered.validate(store.raw_keys(include_inactive=True))


# ------------------------------------------------------------------ the ten mandatory negative tests
def test_negative_1_no_challenge_record(tmp_path):
    st = _state()
    assert G.authorize(st, tmp_path / "gate").reasons == [G.R_NO_RECORD]


def test_negative_2_blocked_challenge(tmp_path):
    st = _state()
    ex, victim, _ = _blocked_execution(tmp_path, st)
    reasons = G.authorize(st, tmp_path / "gate").reasons
    assert any(r.startswith(G.R_BLOCKERS) for r in reasons) and any(r.startswith(G.R_FINAL_REVIEW_NOT_READY) for r in reasons)


def test_negative_3_observation_modified_after_adjudication(tmp_path):
    st = _state()
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, full)
    assert G.authorize(st, tmp_path / "gate").ok
    st.ordered()[0].comment = GText.plain("نص عُدّل بعد الفصل في الاعتراضات.")
    assert G.authorize(st, tmp_path / "gate").reasons == [G.R_NO_RECORD]


def test_negative_4_forged_signature(tmp_path):
    st = _state()
    ex, victim, short = _blocked_execution(tmp_path, st)
    s, other = Signer(), Signer()
    forged = replace(s.decision(victim, fingerprint=ex.fingerprint), signature_b64=other.decision(victim).signature_b64)
    ex2 = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(
        st, short, decisions=[forged], trust=s.store(), now=NOW)
    assert ex2.human_decisions == [] and ex2.rejected_decisions and "SIGNATURE_INVALID" in ex2.rejected_decisions[0]["reason"]
    assert ex2.blockers and not G.authorize(st, tmp_path / "gate", trust_store=s.store(), now=NOW).ok


def test_negative_5_revoked_key(tmp_path):
    st = _state()
    ex, victim, short = _blocked_execution(tmp_path, st)
    s = Signer()
    good = s.decision(victim, fingerprint=ex.fingerprint)
    store = s.store()
    ex2 = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, short, decisions=[good], trust=store, now=NOW)
    assert ex2.human_decisions and ex2.blockers == [] and ex2.status == "CLEAR"
    assert G.authorize(st, tmp_path / "gate", trust_store=store, now=NOW).ok
    store.revoke(s.key_id)
    reasons = G.authorize(st, tmp_path / "gate", trust_store=store, now=NOW).reasons
    assert any(r.startswith(G.R_DECISION_INVALID) and T.R_KEY_REVOKED in r for r in reasons), "revocation is checked again at issue time"
    assert G.authorize(st, tmp_path / "gate", trust_store=None, now=NOW).reasons == [G.R_TRUST_STORE_REQUIRED]


def test_negative_6_expired_authorization(tmp_path):
    st = _state()
    ex, victim, short = _blocked_execution(tmp_path, st)
    s = Signer()
    good = s.decision(victim, fingerprint=ex.fingerprint)
    ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, short, decisions=[good], trust=s.store(), now=NOW)
    assert G.authorize(st, tmp_path / "gate", trust_store=s.store(), now=NOW).ok
    later = NOW + dt.timedelta(days=T.DECISION_VALIDITY_DAYS + 1)
    reasons = G.authorize(st, tmp_path / "gate", trust_store=s.store(), now=later).reasons
    assert any(T.R_DECISION_EXPIRED in r for r in reasons)


def test_negative_7_authorization_reused_for_another_observation(tmp_path):
    st = _state()
    ex, victim, short = _blocked_execution(tmp_path, st)
    s = Signer()
    other_obs = st.ordered()[0].internal_id
    misdirected = s.decision(other_obs, fingerprint=ex.fingerprint)
    ex2 = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, short, decisions=[misdirected], trust=s.store(), now=NOW)
    assert ex2.human_decisions == [] and ex2.blockers, "a decision for another observation clears nothing"
    # and a decision bound to another review state is refused outright
    foreign = s.decision(victim, fingerprint="0" * 64)
    ex3 = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, short, decisions=[foreign], trust=s.store(), now=NOW)
    assert ex3.human_decisions == [] and T.R_STATE_BINDING in ex3.rejected_decisions[0]["reason"]


def test_negative_8_failed_ai_provider(tmp_path):
    st = _state()
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    runner = AgentRunner(MockAdapter(script={}, fail_roles={C.ROLE_BLACK}), TraceWriter())
    ex = ReviewOrchestrator(synthetic_reference_index(), runner=runner, gate_dir=tmp_path / "gate").execute(st, full)
    assert ex.provider_failures >= len(st.observations) and ex.status == "BLOCKED"   # every black team call plus the unscripted final reviewer
    assert any(r.startswith(G.R_PROVIDER_FAILURE) for r in G.authorize(st, tmp_path / "gate").reasons)


def test_negative_9_missing_final_review(tmp_path):
    st = _state()
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    ex = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, full)
    rec_path = G.gate_record_path(ex.fingerprint, tmp_path / "gate")
    d = json.loads(rec_path.read_text(encoding="utf-8")); d["final_review"] = None
    rec_path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert G.R_FINAL_REVIEW_MISSING in G.authorize(st, tmp_path / "gate").reasons
    d["final_review"] = {"recommendation": "READY_WITH_CONDITIONS", "status": "OK", "mode": "MOCK"}
    rec_path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert any(r.startswith(G.R_FINAL_REVIEW_NOT_READY) for r in G.authorize(st, tmp_path / "gate").reasons)


def test_negative_10_synthetic_test_approval_never_issues_institutionally(tmp_path):
    st = _state(demo=False)
    ex, victim, short = _blocked_execution(tmp_path, st)
    syn = Signer("SYNTHETIC_TEST_KEY", synthetic=True)
    d = syn.decision(victim, fingerprint=ex.fingerprint)
    ex2 = ReviewOrchestrator(synthetic_reference_index(), gate_dir=tmp_path / "gate").execute(st, short, decisions=[d], trust=syn.store(), now=NOW)
    assert ex2.human_decisions == [] and T.R_SYNTHETIC_KEY in ex2.rejected_decisions[0]["reason"]
    reasons = G.authorize(st, tmp_path / "gate", trust_store=syn.store(), now=NOW).reasons
    assert G.R_SYNTHETIC in reasons and any(r.startswith(G.R_BLOCKERS) for r in reasons)


# ------------------------------------------------------------------ dispositions (Article 08)
def _revision_execution(tmp_path, st, anchor_needed=True):
    """A mock-live review whose single objection ends UPHELD_WITH_REVISION with a revised text."""
    full = build_reviewed_doc(st, tmp_path / "full.docx")
    from cdf_gco_crms.assurance.evidence import EvidenceRegistry
    reg = EvidenceRegistry(); reg.add_document_text(full)
    target = st.ordered()[1]
    anchor = reg.bind_clause(target.quote)

    def black(p):
        first = p["observation"]["reader_no"] == target.reader_no and not p.get("prior_exchange")
        return {"material_objection": first, "objection_kind": "UNCLEAR_ACTION" if first else "NO_MATERIAL_OBJECTION",
                "challenged_claim": "x", "proposition": "التوصية لا تحدد الإجراء المطلوب من الإدارة تحديداً قابلاً للتنفيذ." if first else "",
                "material_consequence": "تعذر التنفيذ", "evidence_refs": [anchor.id], "existing_controls": [], "requested_correction": "تحديد الإجراء",
                "reasoning_summary": "r", "evidence_limitations": "", "confidence": 0.6}
    revised = "البند لا يحدد الإجراء المطلوب.\nالتوصية: تحديد الإجراء المطلوب والجهة المنفذة ومدة التنفيذ."
    script = {C.ROLE_BLACK: black,
              C.ROLE_RED: {"stance": "REVISE", "objection_accepted": True, "reasoning": "تُراجع الصياغة.", "evidence_refs": [anchor.id],
                           "revised_comment": revised, "revised_quote": None, "route_to": None, "missing_evidence": [], "escalate": False, "new_argument": True},
              C.ROLE_ADJUDICATOR: {"disposition": "UPHELD_WITH_REVISION", "objection_valid": True, "rationale": "r", "decisive_evidence": [anchor.id],
                                   "inadmissible_refs": [], "facts": [], "inferences": [], "unverified_assumptions": [], "remedy_assessment": "ok",
                                   "open_question": None, "escalate": False},
              C.ROLE_EDITORIAL: {"revised_comment": revised, "finding_part": "f", "recommendation_part": "r", "proposed_title": "تحديد الإجراء",
                                 "changes": ["c"], "preserved_references": [], "requires_human_approval": True,
                                 "house_style": {"finding_before_recommendation": True, "no_accusation": True, "action_labelled": True, "within_word_ceiling": True}},
              C.ROLE_FINAL: {"release_recommendation": "READY", "findings": [], "unresolved_critical_objections": [], "contradictions": [],
                             "jurisdiction_consistent": True, "unsupported_or_excessive": [], "summary": "s"}}
    runner = AgentRunner(MockAdapter(script=script), TraceWriter())
    ex = ReviewOrchestrator(synthetic_reference_index(), runner=runner, gate_dir=tmp_path / "gate").execute(st, full)
    return ex, target, revised


def test_apply_dispositions_requires_authorised_decision_and_keeps_history(tmp_path):
    st = _state()
    ex, target, revised = _revision_execution(tmp_path, st)
    assert [o.disposition for e in ex.record.entries for o in e.objections] == ["UPHELD_WITH_REVISION"]
    s = Signer()
    before = plain_text(target.comment)
    # (a) no decision → nothing applied, text untouched
    res0 = apply_dispositions(st, ex.record, [], s.store(), expected_fingerprint=ex.fingerprint, now=NOW)
    assert res0.applied == [] and not res0.changed and plain_text(st.by_id()[target.internal_id].comment) == before
    # (b) a boolean or an unsigned record is rejected
    res1 = apply_dispositions(st, ex.record, [True, {"approved": True}], s.store(), expected_fingerprint=ex.fingerprint, now=NOW)
    assert len(res1.rejected) == 2 and not res1.changed
    # (c) an authorised UPHELD_WITH_REVISION applies the recorded revision to a copy, with ledger and provenance
    d = s.decision(target.internal_id, "UPHELD_WITH_REVISION", fingerprint=ex.fingerprint)
    from cdf_gco_crms.release.dispositions import revision_digest
    obj = next(o for e in ex.record.entries for o in e.objections if e.internal_id == target.internal_id)
    d = replace(d, challenge_id=obj.challenge_id,
                revision_sha256=revision_digest(obj.challenge_id, obj.advocacy.get("revised_comment"), obj.advocacy.get("revised_quote")))
    d = replace(d, signature_b64=base64.b64encode(s.priv.sign(d.signature_payload())).decode())
    ledger = tmp_path / "ledger.jsonl"
    res = apply_dispositions(st, ex.record, [d], s.store(), expected_fingerprint=ex.fingerprint, now=NOW, ledger_path=ledger)
    assert res.applied and res.changed and res.conflicts == []
    assert plain_text(res.state.by_id()[target.internal_id].comment) == revised
    assert plain_text(st.by_id()[target.internal_id].comment) == before, "the input state is never mutated"
    assert res.state.by_id()[target.internal_id].internal_id == target.internal_id
    entries = read_ledger(ledger)
    assert entries[0]["before"]["comment"] == before and entries[0]["after"]["comment"] == revised
    assert entries[0]["decision_id"] == d.decision_id and entries[0]["signing_key_id"] == s.key_id and entries[0]["new_fingerprint"] == res.new_fingerprint
    # (d) the revised state has a new fingerprint: the old gate record no longer applies to it
    assert G.authorize(res.state, tmp_path / "gate").reasons == [G.R_NO_RECORD]
    # (e) rollback restores the original
    back, done = rollback(res.state, entries[0])
    assert done and plain_text(back.by_id()[target.internal_id].comment) == before
    assert G.state_fingerprint(back) == ex.fingerprint
    # (f) a state changed since the challenge is a conflict
    st2 = _state()
    st2.ordered()[0].comment = GText.plain("تغيير لاحق.")
    res2 = apply_dispositions(st2, ex.record, [d], s.store(), expected_fingerprint=ex.fingerprint, now=NOW)
    assert res2.conflicts and res2.applied == []
    # (g) an expired or synthetic-key decision on an institutional document is rejected
    inst = _state(demo=False)
    (tmp_path / "inst").mkdir()
    ex_i, target_i, _ = _revision_execution(tmp_path / "inst", inst)
    syn = Signer("SYNTHETIC_TEST_KEY", synthetic=True)
    res3 = apply_dispositions(inst, ex_i.record, [syn.decision(target_i.internal_id, "UPHELD_WITH_REVISION", fingerprint=ex_i.fingerprint)],
                              syn.store(), expected_fingerprint=ex_i.fingerprint, now=NOW)
    assert res3.applied == [] and T.R_SYNTHETIC_KEY in res3.rejected[0]["reason"]


# ------------------------------------------------------------------ CLI: adjudicate / apply-dispositions / build with trust store
def _run(argv, capsys):
    rc = CLI.main(argv)
    out = capsys.readouterr().out
    return (rc if isinstance(rc, int) else 0), json.loads(out[out.index("{"):])


def test_cli_adjudicate_and_issue_revalidate_decisions_against_the_trust_store(tmp_path, capsys):
    spec = {"document": {"name": "وثيقة دورة الإصدار", "code": "LCY", "cover_version": "الإصدار 0.1", "owning_department": DEPT, "is_demo": True},
            "date": "2026-02-15", "observations": [{"location": o.location, "quote": o.quote,
                                                    "comment": [[s.text, s.bold] for s in o.comment.segments]} for o in base_obs(5)]}
    (tmp_path / "r1.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    rc, rep = _run(["round1", str(tmp_path / "r1.json"), str(tmp_path / "out")], capsys)
    wb = rep["output"]
    st = parse_workbook(wb).state
    victim = st.ordered()[2].internal_id
    short = build_reviewed_doc(st, tmp_path / "short.docx", omit=(victim,))
    gate = str(tmp_path / "gate")
    rc, rep = _run(["review", wb, "--docx", str(short), "--gate-dir", gate, "--synthetic-reference"], capsys)
    assert rc == CLI.RC_FAIL and rep["status"] == "BLOCKED" and rep["final_review"]["recommendation"] == "NOT_READY"
    s = Signer()
    store_path = tmp_path / "trust.json"; store_path.write_text(json.dumps(s.store().to_dict()), encoding="utf-8")
    d = s.decision(victim, fingerprint=rep["fingerprint"], timestamp=dt.datetime.now(dt.timezone.utc).isoformat())
    (tmp_path / "dec.json").write_text(json.dumps([d.__dict__], ensure_ascii=False), encoding="utf-8")
    rc, rep = _run(["adjudicate", wb, str(tmp_path / "dec.json"), "--docx", str(short), "--gate-dir", gate, "--synthetic-reference"], capsys)
    assert rc == CLI.RC_REFUSED, "adjudicate without a trust store is refused"
    rc, rep = _run(["adjudicate", wb, str(tmp_path / "dec.json"), "--docx", str(short), "--gate-dir", gate, "--synthetic-reference",
                    "--trust-store", str(store_path)], capsys)
    assert rc == 0 and rep["status"] == "CLEAR" and rep["human_decisions_applied"] == 1 and rep["final_review"]["recommendation"] == "READY"
    rc, rep = _run(["build-excel", wb, str(tmp_path / "issue"), "--gate-dir", gate], capsys)
    assert rc == CLI.RC_REFUSED and G.R_TRUST_STORE_REQUIRED in rep["gate"]["reasons"]
    rc, rep = _run(["build-excel", wb, str(tmp_path / "issue"), "--gate-dir", gate, "--trust-store", str(store_path)], capsys)
    assert rc == 0 and rep["release_authorized"] and not rep["working_copy"]
    revoked = s.store(); revoked.revoke(s.key_id)
    store_path.write_text(json.dumps(revoked.to_dict()), encoding="utf-8")
    rc, rep = _run(["build-excel", wb, str(tmp_path / "issue2"), "--gate-dir", gate, "--trust-store", str(store_path)], capsys)
    assert rc == CLI.RC_REFUSED and any(T.R_KEY_REVOKED in r for r in rep["gate"]["reasons"])
    bad = [{"decision": True}]
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    rc, rep = _run(["apply-dispositions", wb, str(tmp_path / "bad.json"), str(tmp_path / "ad"), "--docx", str(short), "--gate-dir", gate,
                    "--synthetic-reference", "--trust-store", str(store_path)], capsys)
    assert rc == CLI.RC_REFUSED
