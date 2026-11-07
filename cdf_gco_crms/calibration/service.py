"""MAT calibration service: explicit case permissions and normalized response contracts.

The API boundary is LOCAL-DEVELOPMENT ONLY until institutional identity,
case entitlement provisioning, and trusted deployment controls exist.
"""
from __future__ import annotations

import json
from .store import CalibrationError, CalibrationStore, ReviewerContext, AccessDenied


def _roles(user):
    return set(user.roles)


class CalibrationService:
    def __init__(self, store: CalibrationStore, case_grants: dict[str, set[str]] | None = None):
        self.store = store
        self.case_grants = case_grants if case_grants is not None else {}  # optional in-memory test grants, never a substitute for DB grants

    def authorize(self, case_id: str, user: ReviewerContext, required: str = "CALIBRATION_REVIEWER"):
        user.require(required)
        grants = self.case_grants.get(case_id, set())
        db_grant = self.store.db.execute("SELECT 1 FROM case_grants WHERE case_id=? AND reviewer_id=?", (case_id, user.reviewer_id)).fetchone()
        if user.reviewer_id not in grants and not db_grant:
            raise AccessDenied("CASE_ACCESS_DENIED")

    def import_case(self, case_id, source_hash, evidence, user):
        user.require("CALIBRATION_ADMIN")
        result = self.store.import_case(case_id, source_hash, evidence, user)
        return {"case_id": case_id, "evidence_hash": result, "observations": len(evidence)}

    def list_cases(self, user):
        user.require("CALIBRATION_REVIEWER")
        # Fail closed: no discoverable case list without explicit grants.
        result = []
        ids = {row["case_id"] for row in self.store.db.execute("SELECT case_id FROM case_grants WHERE reviewer_id=?", (user.reviewer_id,))}
        ids.update(k for k, users in self.case_grants.items() if user.reviewer_id in users)
        for case_id in sorted(ids):
            row = self.store._case(case_id)
            result.append({"case_id": case_id, "evidence_hash": row["evidence_hash"],
                           "source_hash": row["source_hash"],
                           "stats": self.store.case_statistics(case_id, user)})
        return result

    def case(self, case_id, user):
        self.authorize(case_id, user)
        row = self.store._case(case_id)
        return {"case_id": case_id, "source_hash": row["source_hash"],
                "evidence_hash": row["evidence_hash"],
                "observations": self.store.observations(case_id, user),
                "statistics": self.store.case_statistics(case_id, user)}

    def decision(self, case_id, observation_id, request: dict, user):
        self.authorize(case_id, user)
        keyset = {"decision", "rationale", "expected_evidence_hash", "status",
                  "reasons", "evidence_refs", "material_categories"}
        if set(request) - keyset:
            raise CalibrationError("UNKNOWN_FIELDS")
        return self.store.save_decision(
            case_id, observation_id, request["decision"], request.get("rationale", ""),
            request["expected_evidence_hash"], user,
            reasons=request.get("reasons"), evidence_refs=request.get("evidence_refs"),
            material_categories=request.get("material_categories"),
            status=request.get("status", "DRAFT"),
        )

    def rule(self, case_id, rule_id, request, user):
        self.authorize(case_id, user, required="DNA_RULE_APPROVER")
        return self.store.rule_action(
            case_id, rule_id, request["action"], request["rationale"], user,
            observation_event_hashes=request["observation_event_hashes"],
            profile_version=request["profile_version"],
        )

    def events(self, case_id, user):
        self.authorize(case_id, user)
        return self.store.events(case_id, user)

    def compile_profile(self, case_id, user):
        self.authorize(case_id, user, required="DNA_RULE_APPROVER")
        from .profile_compiler import compile_candidate
        return compile_candidate(self.store, case_id, user)

    def profiles(self, case_id, user):
        self.authorize(case_id, user)
        return self.store.profile_versions(case_id, user)

    def activate_profile(self, case_id, version, user):
        self.authorize(case_id, user, required="DNA_RULE_APPROVER")
        return self.store.activate_synthetic_profile(case_id, version, user)

    def profile_document(self, case_id, version, user):
        self.authorize(case_id, user)
        return self.store.synthetic_profile_document(case_id, version, user)
