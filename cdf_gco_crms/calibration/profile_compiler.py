"""Compile versioned, NON-BINDING synthetic DNA profile snapshots for a local pilot.

Only the institutionally approved, separately attested calibration pipeline may
ever issue a validated, human-approved MAT profile. This module never does that.
"""
from __future__ import annotations

import copy
import hashlib
import json

from .analytics import analyze
from .store import CalibrationError, CalibrationStore, ReviewerContext, canonical
from cdf_gco_crms.agents.mat_profile import load_profile, synthetic_fixture_path


def compile_candidate(store: CalibrationStore, case_id: str, reviewer: ReviewerContext) -> dict:
    reviewer.require("DNA_RULE_APPROVER")
    store._case(case_id)
    if not store.verify_chain(case_id, reviewer):
        raise CalibrationError("AUDIT_CHAIN_FAILED")
    events = store.events(case_id, reviewer)
    submitted = {}
    for event in events:
        if event["event_type"] == "OBSERVATION_CALIBRATION":
            payload = json.loads(event["payload_json"])
            if payload.get("status") == "SUBMITTED":
                submitted[event["event_hash"]] = event
    if not submitted:
        raise CalibrationError("SUBMITTED_CALIBRATION_REQUIRED")
    approved = {}
    for event in events:
        if event["event_type"] != "DNA_RULE_REVIEW":
            continue
        payload = json.loads(event["payload_json"])
        # A later non-approval supersedes the old grant, never resurrect it.
        approved.pop(payload["rule_id"], None)
        if payload.get("action") == "APPROVE":
            ids = payload.get("observation_event_hashes", [])
            if ids and all(x in submitted for x in ids):
                approved[payload["rule_id"]] = list(ids)
    if not approved:
        raise CalibrationError("APPROVED_SYNTHETIC_RULE_REQUIRED")

    profile = copy.deepcopy(load_profile(synthetic_fixture_path()).data)
    included = []
    for rule in profile["selection_rules"] + profile["withdrawal_rules"]:
        rid = rule.get("rule_id")
        if rid in approved:
            # Annotation is evidence, not authority; never grant MAT binding status.
            rule["calibration_event_hashes"] = approved[rid]
            rule["mat_explicitly_approved"] = False
            included.append(rid)
    if not included:
        raise CalibrationError("NO_KNOWN_APPROVED_RULES")
    distribution = analyze(store, case_id, reviewer)
    digest = hashlib.sha256(canonical({
        "case_id": case_id, "approved_rules": included,
        "submitted": sorted(submitted), "rule_evidence": approved,
        "evidence": store._case(case_id)["evidence_hash"]
    }).encode()).hexdigest()
    profile["version"] = "0.1.0-synthetic-cal-" + digest[:16]
    existing = next((p for p in store.profile_versions(case_id, reviewer)
                     if p["profile_version"] == profile["version"]), None)
    if existing:
        store.synthetic_profile_document(case_id, profile["version"], reviewer)  # verify stored integrity
        return {"case_id": case_id, "profile_version": existing["profile_version"],
                "profile_sha256": existing["profile_sha256"], "status": "PROVISIONAL",
                "institutional_approval": "NOT_AUTHORIZED"}
    profile["generated_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    profile["status"] = "PROVISIONAL"
    profile["human_approval_status"] = "NOT_APPROVED"
    profile["synthetic"] = True
    profile["label"] = "SYNTHETIC_LOCAL_DEV_NOT_INSTITUTIONAL"
    profile["evidence_scope"] = "Synthetic single-case calibration, NOT MAT-approved"
    profile["distribution"] = distribution
    profile.setdefault("validation_results", []).append({
        "test": "synthetic-calibration-evidence-review",
        "result": "NOT_A_HUMAN_AUTHORIZATION",
        "rule_ids": included
    })
    return store.save_synthetic_profile(case_id, profile, reviewer)
