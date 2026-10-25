"""Audit follow-ups D9–D14 (owner's stack audit, 2026-10-25), synthetic only.

D9  optimistic concurrency on decisions          D10 second-human review of submitted decisions
D11 rule reviews cite current evidence and a real profile version
D13 append-only audit log with a head anchor     D14 latest rule action wins; APPROVE_WITH_CHANGES not counted approved
"""
from __future__ import annotations

import sqlite3

import pytest

from cdf_gco_crms.calibration.profile_compiler import compile_candidate
from cdf_gco_crms.calibration.service import CalibrationService
from cdf_gco_crms.calibration.store import (
    AccessDenied, CalibrationError, CalibrationStore, ReviewerContext, StaleDecision,
)

BASE = "0.1.0-synthetic"
ROLES = frozenset({"CALIBRATION_ADMIN", "CALIBRATION_REVIEWER", "DNA_RULE_APPROVER"})
AML = "قد تقتضي التزامات مكافحة غسل الأموال معرفة المستفيد من العملية."
GOOD = "The safeguard is already imposed by the bank's own statutory regime and the agreement adds nothing."


def _who(name):
    return ReviewerContext(name, ROLES, authenticated=True)


@pytest.fixture()
def env(tmp_path):
    st = CalibrationStore(tmp_path / "cal.sqlite")
    a, b = _who("SYN-REVIEWER-A"), _who("SYN-REVIEWER-B")
    digest = st.import_case("SYN-CASE", "a" * 64, [
        {"observation_id": "SYN-1", "original_text": "النص لا يحدد الجهة المنفذة.", "observed_change": "KEEP_WITH_REVISIONS"},
        {"observation_id": "SYN-2", "original_text": AML, "observed_change": "REMOVED_FROM_VERSION"},
    ], a)
    st.db.execute("INSERT INTO case_grants VALUES ('SYN-CASE', 'SYN-REVIEWER-B')")
    st.db.commit()
    return st, a, b, digest


# ------------------------------------------------------------------ D9
def test_stale_decision_head_is_refused(env):
    st, a, b, digest = env
    assert st.decision_head("SYN-CASE", "SYN-1") is None
    first = st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "Reviewer A", digest, a, status="SUBMITTED", expected_decision_head=None)
    # B read the observation before A's decision existed: B's write must not silently replace A's
    with pytest.raises(StaleDecision, match="DECISION_CHANGED_SINCE_READ"):
        st.save_decision("SYN-CASE", "SYN-1", "KEEP_UNCHANGED", "Reviewer B", digest, b, status="SUBMITTED", expected_decision_head=None)
    # B re-reads and decides knowingly
    second = st.save_decision("SYN-CASE", "SYN-1", "KEEP_UNCHANGED", "Reviewer B", digest, b, status="SUBMITTED",
                              expected_decision_head=first)
    assert st.decision_head("SYN-CASE", "SYN-1") == second


def test_overwriting_another_reviewers_decision_needs_the_head(env):
    st, a, b, digest = env
    st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "Reviewer A", digest, a, status="DRAFT")
    st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "Reviewer A again", digest, a, status="SUBMITTED")   # own decision: allowed
    with pytest.raises(StaleDecision, match="EXPECTED_DECISION_HEAD_REQUIRED"):
        st.save_decision("SYN-CASE", "SYN-1", "EXPAND", "Reviewer B blind", digest, b, status="SUBMITTED")


# ------------------------------------------------------------------ D10
def _material_withdrawal(st, a, digest):
    return st.save_decision("SYN-CASE", "SYN-2", "WITHDRAW", GOOD, digest, a, status="SUBMITTED",
                            reasons=["W04"], evidence_refs=["SYN-EVIDENCE-001"])


def test_material_withdrawal_waits_for_a_second_human(env):
    st, a, b, digest = env
    h = _material_withdrawal(st, a, digest)
    assert st.decision_states("SYN-CASE")["SYN-2"]["status"] == "AWAITING_SECOND_REVIEW"
    assert st.case_statistics("SYN-CASE", a)["awaiting_second_review"] == 1
    with pytest.raises(CalibrationError, match="MATERIAL_WITHDRAWAL_NOT_SECOND_REVIEWED"):
        st.rule_action("SYN-CASE", "SYN-S02", "APPROVE", "Synthetic rule review", a, observation_event_hashes=[h], profile_version=BASE)
    with pytest.raises(AccessDenied, match="SECOND_REVIEWER_MUST_DIFFER"):
        st.review_decision("SYN-CASE", h, "APPROVED", "I approve my own withdrawal decision", a)
    st.review_decision("SYN-CASE", h, "APPROVED", "Checked the cited control independently", b)
    assert st.decision_states("SYN-CASE")["SYN-2"]["status"] == "APPROVED"
    st.rule_action("SYN-CASE", "SYN-S02", "APPROVE", "Synthetic rule review", a, observation_event_hashes=[h], profile_version=BASE)


def test_returned_decision_cannot_support_a_rule_and_drafts_cannot_be_reviewed(env):
    st, a, b, digest = env
    d = st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "Draft only", digest, a, status="DRAFT")
    with pytest.raises(CalibrationError, match="DRAFT_CANNOT_BE_REVIEWED"):
        st.review_decision("SYN-CASE", d, "APPROVED", "Reviewing a draft is not possible", b)
    s = st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "Submitted now", digest, a, status="SUBMITTED")
    st.review_decision("SYN-CASE", s, "RETURNED", "The rationale does not name the redundancy", b)
    assert st.case_statistics("SYN-CASE", a)["returned_decisions"] == 1
    with pytest.raises(CalibrationError, match="RETURNED_DECISION_CANNOT_SUPPORT_RULE"):
        st.rule_action("SYN-CASE", "SYN-S01", "APPROVE", "Synthetic", a, observation_event_hashes=[s], profile_version=BASE)


# ------------------------------------------------------------------ D11
def test_rule_review_refuses_superseded_evidence_and_unknown_profile_version(env):
    st, a, b, digest = env
    old = st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "First view", digest, a, status="SUBMITTED")
    new = st.save_decision("SYN-CASE", "SYN-1", "KEEP_UNCHANGED", "Changed my view", digest, a, status="SUBMITTED")
    with pytest.raises(CalibrationError, match="SUPERSEDED_CALIBRATION_EVIDENCE"):
        st.rule_action("SYN-CASE", "SYN-S01", "APPROVE", "Synthetic", a, observation_event_hashes=[old], profile_version=BASE)
    with pytest.raises(CalibrationError, match="UNKNOWN_PROFILE_VERSION"):
        st.rule_action("SYN-CASE", "SYN-S01", "APPROVE", "Synthetic", a, observation_event_hashes=[new], profile_version="PROVISIONAL-v1")
    st.rule_action("SYN-CASE", "SYN-S01", "APPROVE", "Synthetic", a, observation_event_hashes=[new], profile_version=BASE)


def test_compiler_ignores_rules_whose_evidence_was_superseded(env):
    st, a, b, digest = env
    old = st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "First view", digest, a, status="SUBMITTED")
    st.rule_action("SYN-CASE", "SYN-S01", "APPROVE", "Synthetic", a, observation_event_hashes=[old], profile_version=BASE)
    st.save_decision("SYN-CASE", "SYN-1", "KEEP_UNCHANGED", "Changed my view", digest, a, status="SUBMITTED")
    with pytest.raises(CalibrationError, match="APPROVED_SYNTHETIC_RULE_REQUIRED|NO_KNOWN_APPROVED_RULES"):
        compile_candidate(st, "SYN-CASE", a)


def test_service_exposes_decision_head_state_and_eligible_events(env):
    st, a, b, digest = env
    svc = CalibrationService(st)
    h = svc.decision("SYN-CASE", "SYN-1", {"decision": "SHORTEN", "rationale": "x", "expected_evidence_hash": digest,
                                           "status": "SUBMITTED", "expected_decision_head": None}, a)
    case = svc.case("SYN-CASE", a)
    o = {x["observation_id"]: x for x in case["observations"]}
    assert o["SYN-1"]["decision_head"] == h and o["SYN-1"]["decision_state"]["status"] == "SUBMITTED"
    assert o["SYN-2"]["decision_head"] is None and h in case["rule_eligible_events"] and BASE in case["profile_versions_known"]
    with pytest.raises(StaleDecision):
        svc.decision("SYN-CASE", "SYN-1", {"decision": "EXPAND", "rationale": "x", "expected_evidence_hash": digest,
                                           "status": "SUBMITTED", "expected_decision_head": None}, b)
    svc.review_decision("SYN-CASE", {"decision_event_hash": h, "outcome": "APPROVED", "rationale": "Second reviewer agrees fully"}, b)


# ------------------------------------------------------------------ D13
def test_audit_log_is_append_only_and_truncation_is_detected(env):
    st, a, b, digest = env
    st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "Reviewer A", digest, a, status="SUBMITTED")
    head = st.chain_head("SYN-CASE")
    assert head["event_count"] == 2 and st.verify_chain("SYN-CASE", a)
    with pytest.raises(sqlite3.IntegrityError, match="AUDIT_LOG_APPEND_ONLY"):
        with st.db:
            st.db.execute("DELETE FROM events WHERE case_id='SYN-CASE'")
    # a privileged writer drops the trigger and removes the newest event: the head anchor no longer matches
    with st.db:
        st.db.execute("DROP TRIGGER events_no_delete")
        st.db.execute("DELETE FROM events WHERE event_id=(SELECT MAX(event_id) FROM events)")
    assert not st.verify_chain("SYN-CASE", a)
    assert st.case_statistics("SYN-CASE", a)["audit_chain_head"] == head, "the anchor keeps the pre-truncation head for comparison"


# ------------------------------------------------------------------ D14
def test_latest_rule_action_wins_and_changes_are_not_counted_approved(env):
    st, a, b, digest = env
    e = st.save_decision("SYN-CASE", "SYN-1", "SHORTEN", "Reviewer A", digest, a, status="SUBMITTED")
    st.rule_action("SYN-CASE", "SYN-S01", "APPROVE", "Synthetic", a, observation_event_hashes=[e], profile_version=BASE)
    st.rule_action("SYN-CASE", "SYN-S02", "APPROVE_WITH_CHANGES", "Synthetic", a, observation_event_hashes=[e], profile_version=BASE)
    stats = st.case_statistics("SYN-CASE", a)
    assert stats["approved_dna_rules"] == 1 and stats["rules_approved_with_changes_pending_wording"] == 1
    st.rule_action("SYN-CASE", "SYN-S01", "REJECT", "Later rejection", a, observation_event_hashes=[e], profile_version=BASE)
    assert st.case_statistics("SYN-CASE", a)["approved_dna_rules"] == 0
