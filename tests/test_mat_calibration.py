"""Synthetic-only regression tests for MAT calibration events and human control."""
import json
import sqlite3
import pytest

from cdf_gco_crms.calibration.store import (
    CalibrationStore, ReviewerContext, CalibrationError, AccessDenied, StaleCase,
)

SHA = "a" * 64
CASE = [{"observation_id": "OBS-001", "observed_change": "REMOVED_FROM_VERSION",
         "material_categories": ["AML"], "original_text": "Synthetic compliance question"},
        {"observation_id": "OBS-002", "observed_change": "EDITED_IN_PLACE",
         "original_text": "Synthetic recommendation"}]


@pytest.fixture()
def env(tmp_path):
    store = CalibrationStore(tmp_path / "private" / "mat.db")
    admin = ReviewerContext("test-admin", frozenset({"CALIBRATION_ADMIN", "CALIBRATION_REVIEWER", "DNA_RULE_APPROVER"}), True)
    reviewer = ReviewerContext("test-reviewer", frozenset({"CALIBRATION_REVIEWER"}), True)
    digest = store.import_case("CASE-SYN", SHA, CASE, admin)
    yield store, admin, reviewer, digest
    store.close()


def test_absence_is_not_human_withdrawal(env):
    st, admin, reviewer, digest = env
    assert st.case_statistics("CASE-SYN", reviewer)["submitted_observations"] == 0
    assert st.observations("CASE-SYN", reviewer)[0]["observed_change"] == "REMOVED_FROM_VERSION"


def test_unauthenticated_identity_does_not_satisfy_roles(env):
    st, admin, reviewer, digest = env
    spoof = ReviewerContext("claimed-admin", frozenset({"CALIBRATION_REVIEWER", "DNA_RULE_APPROVER"}), False)
    with pytest.raises(AccessDenied):
        st.observations("CASE-SYN", spoof)
    with pytest.raises(AccessDenied):
        st.rule_action("CASE-SYN", "SYN-R1", "APPROVE", "reason", spoof,
                       observation_event_hashes=["bogus"], profile_version="1.0")


def test_material_withdrawal_requires_reason_and_evidence(env):
    st, admin, reviewer, digest = env
    with pytest.raises(CalibrationError, match="WITHDRAWAL_REASON"):
        st.save_decision("CASE-SYN", "OBS-001", "WITHDRAW", "Too broad", digest, reviewer, status="SUBMITTED")
    with pytest.raises(CalibrationError, match="MATERIAL_WITHDRAWAL"):
        st.save_decision("CASE-SYN", "OBS-001", "WITHDRAW", "Evidence reviewed", digest, reviewer,
                         reasons=["W12"], status="SUBMITTED")
    eid = st.save_decision("CASE-SYN", "OBS-001", "WITHDRAW", "Synthetic existing control", digest, reviewer,
                           reasons=["W12"], evidence_refs=["EVIDENCE_GAP:verify"], status="SUBMITTED")
    assert eid and st.case_statistics("CASE-SYN", reviewer)["heightened_review"] == 1
    assert st.verify_chain("CASE-SYN", reviewer)


def test_case_hash_prevents_stale_calibration(env):
    st, admin, reviewer, digest = env
    with pytest.raises(StaleCase):
        st.save_decision("CASE-SYN", "OBS-002", "KEEP_UNCHANGED", "OK", "0" * 64, reviewer, status="SUBMITTED")


def test_no_implicit_rule_approval_from_calibration(env):
    st, admin, reviewer, digest = env
    e = st.save_decision("CASE-SYN", "OBS-002", "KEEP_WITH_REVISIONS", "Synthetic rationale", digest, reviewer, status="SUBMITTED")
    assert st.case_statistics("CASE-SYN", reviewer)["approved_dna_rules"] == 0
    with pytest.raises(AccessDenied):
        st.rule_action("CASE-SYN", "SYN-R1", "APPROVE", "Evidence reason", reviewer,
                       observation_event_hashes=[e], profile_version="1.0")
    with pytest.raises(CalibrationError, match="UNKNOWN_CALIBRATION"):
        st.rule_action("CASE-SYN", "SYN-R1", "APPROVE", "Evidence reason", admin,
                       observation_event_hashes=["f" * 64], profile_version="1.0")
    st.rule_action("CASE-SYN", "SYN-R1", "APPROVE", "Synthetic documented support", admin,
                   observation_event_hashes=[e], profile_version="1.0")
    assert st.case_statistics("CASE-SYN", reviewer)["approved_dna_rules"] == 1


def test_hash_chain_detects_post_hoc_tampering(env):
    st, admin, reviewer, digest = env
    st.save_decision("CASE-SYN", "OBS-002", "SHORTEN", "Remove redundant preface", digest, reviewer, status="SUBMITTED")
    assert st.verify_chain("CASE-SYN", reviewer)
    with st.db:
        st.db.execute("UPDATE events SET payload_json=? WHERE event_type='OBSERVATION_CALIBRATION'",
                      (json.dumps({"decision": "WITHDRAW"}),))
    assert not st.verify_chain("CASE-SYN", reviewer)


def test_editing_is_append_only(env):
    st, admin, reviewer, digest = env
    st.save_decision("CASE-SYN", "OBS-002", "SHORTEN", "First", digest, reviewer, status="DRAFT")
    st.save_decision("CASE-SYN", "OBS-002", "KEEP_WITH_REVISIONS", "Second", digest, reviewer, status="SUBMITTED")
    ev = [x for x in st.events("CASE-SYN", reviewer) if x["event_type"] == "OBSERVATION_CALIBRATION"]
    assert len(ev) == 2 and st.verify_chain("CASE-SYN", reviewer)
    assert st.case_statistics("CASE-SYN", reviewer)["submitted_observations"] == 1


def test_duplicate_observation_and_fabricated_withdrawal_blocked(tmp_path):
    store = CalibrationStore(tmp_path / "private.db")
    admin = ReviewerContext("admin", frozenset({"CALIBRATION_ADMIN"}), True)
    with pytest.raises(CalibrationError, match="DUPLICATE"):
        store.import_case("x", SHA, CASE + [CASE[0]], admin)
    bad = [{**CASE[0], "human_decision": "WITHDRAW"}]
    with pytest.raises(CalibrationError, match="ABSENCE_IS_NOT"):
        store.import_case("x", SHA, bad, admin)
    store.close()
