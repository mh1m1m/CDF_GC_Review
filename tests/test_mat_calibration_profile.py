"""Synthetic MAT calibration analytics, candidate profile and auditable rollback tests."""
import json

import pytest

from cdf_gco_crms.calibration.store import CalibrationStore, ReviewerContext, CalibrationError
from cdf_gco_crms.calibration.analytics import analyze
from cdf_gco_crms.calibration.profile_compiler import compile_candidate
from cdf_gco_crms.agents.mat_profile import load_profile


@pytest.fixture
def private_case(tmp_path):
    s = CalibrationStore(tmp_path / "private" / "mat.sqlite")
    admin = ReviewerContext("SYNTHETIC_ADMIN",
        frozenset({"CALIBRATION_ADMIN", "CALIBRATION_REVIEWER", "DNA_RULE_APPROVER"}), True)
    source = [
        {"observation_id": "SYN-OBS-001", "original_text": "Synthetic directive one",
         "reviewed_text": "Is approval documented?", "observed_change": "CONVERT_TO_QUESTION",
         "primary_type_original": "DIRECT_RECOMMENDATION",
         "primary_type_reviewed": "DIRECT_QUESTION"},
        {"observation_id": "SYN-OBS-002", "original_text": "Synthetic recommendation",
         "reviewed_text": "", "observed_change": "REMOVED_FROM_VERSION",
         "primary_type_original": "DIRECT_RECOMMENDATION",
         "material_categories": ["AML"]},
    ]
    source_hash = s.import_case("SYN-CASE-001", "a" * 64, source, admin)
    yield s, admin, source_hash
    s.close()


def test_analytics_denominator_excludes_empty_comments(private_case):
    st, user, digest = private_case
    data = analyze(st, "SYN-CASE-001", user)
    assert data["observation_units"] == 2
    assert data["original_distribution"]["denominator"] == 2
    assert data["reviewed_distribution"]["denominator"] == 1
    assert data["original_distribution"]["recommendation_count"] == 2
    assert data["reviewed_distribution"]["question_count"] == 1
    assert data["unresolved_absences"] == 1
    assert data["human_calibrated_withdrawals"] == 0


def test_compile_is_not_possible_without_submitted_decision(private_case):
    st, user, digest = private_case
    with pytest.raises(CalibrationError, match="SUBMITTED_CALIBRATION"):
        compile_candidate(st, "SYN-CASE-001", user)
    st.save_decision("SYN-CASE-001", "SYN-OBS-001", "CONVERT_TO_QUESTION",
                     "Synthetic business verification", digest, user, status="DRAFT")
    with pytest.raises(CalibrationError, match="SUBMITTED_CALIBRATION"):
        compile_candidate(st, "SYN-CASE-001", user)


def test_profile_compile_separate_rule_approval_and_no_binding(private_case, tmp_path):
    st, user, digest = private_case
    eid = st.save_decision("SYN-CASE-001", "SYN-OBS-001", "CONVERT_TO_QUESTION",
                           "Synthetic business verification", digest, user, status="SUBMITTED")
    with pytest.raises(CalibrationError, match="APPROVED_SYNTHETIC_RULE"):
        compile_candidate(st, "SYN-CASE-001", user)
    st.rule_action("SYN-CASE-001", "SYN-S01", "APPROVE", "Use for demo only",
                   user, observation_event_hashes=[eid], profile_version="0.1.0-synthetic")
    result=compile_candidate(st, "SYN-CASE-001", user)
    assert result["status"]=="PROVISIONAL"
    version=result["profile_version"]
    profile=st.synthetic_profile_document("SYN-CASE-001", version, user)
    assert profile["synthetic"] is True
    assert profile["human_approval_status"]=="NOT_APPROVED"
    assert profile["status"]=="PROVISIONAL"
    assert not any(r["mat_explicitly_approved"] for r in profile["selection_rules"])
    path=tmp_path/"synthetic_compiled.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    loaded=load_profile(path)
    assert loaded.binding_allowed is False
    assert loaded.rule_status("SYN-S01")["use"]=="ADVISORY"
    assert st.verify_chain("SYN-CASE-001",user)


def test_activation_history_and_rollback_event(private_case):
    st,user,digest=private_case
    e=st.save_decision("SYN-CASE-001", "SYN-OBS-001", "KEEP_WITH_REVISIONS",
                       "Synthetic rationale", digest, user, status="SUBMITTED")
    st.rule_action("SYN-CASE-001", "SYN-S01", "APPROVE", "Synthetic review",
                   user, observation_event_hashes=[e], profile_version="0.1.0-synthetic")
    first=compile_candidate(st,"SYN-CASE-001",user)
    st.activate_synthetic_profile("SYN-CASE-001",first["profile_version"],user)
    versions=st.profile_versions("SYN-CASE-001",user)
    assert len(versions)==1 and versions[0]["active"]
    with pytest.raises(CalibrationError, match="PROFILE_VERSION_NOT_FOUND"):
        st.activate_synthetic_profile("SYN-CASE-001","unknown",user)
    assert st.verify_chain("SYN-CASE-001",user)


def test_draft_evidence_cannot_approve_rule(private_case):
    st,user,digest=private_case
    e=st.save_decision("SYN-CASE-001", "SYN-OBS-001", "KEEP_UNCHANGED",
                       "Draft", digest, user, status="DRAFT")
    with pytest.raises(CalibrationError, match="UNKNOWN_CALIBRATION_EVIDENCE"):
        st.rule_action("SYN-CASE-001", "SYN-S01", "APPROVE", "Must be submitted",
                       user, observation_event_hashes=[e], profile_version="0.1.0-synthetic")
