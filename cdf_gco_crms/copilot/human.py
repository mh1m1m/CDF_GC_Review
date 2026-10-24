"""Append-only synthetic human review; no signature, disposition or policy promotion."""

import json, uuid, os
from datetime import datetime, timedelta, timezone
from ..calibration.store import CalibrationError, canonical, fingerprint, now_utc
from ..execution.service import Conflict


class HumanReviewService:
    def __init__(self, app):
        self.app = app
        app.store.db.executescript(
            """
        CREATE TABLE IF NOT EXISTS cp_human(event_hash TEXT PRIMARY KEY,case_id TEXT NOT NULL,observation_id TEXT NOT NULL,
          previous_version TEXT NOT NULL,actor TEXT NOT NULL,at TEXT NOT NULL,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cp_human_keys(actor TEXT NOT NULL,idem_key TEXT NOT NULL,request_hash TEXT NOT NULL,event_hash TEXT NOT NULL,PRIMARY KEY(actor,idem_key));
        """
        )

    def records(self, case_id, p):
        self.app.authorize_case(case_id, p)
        return [
            dict(r)
            for r in self.app.store.db.execute(
                "SELECT * FROM cp_human WHERE case_id=? ORDER BY at,event_hash",
                (case_id,),
            )
        ]

    def versions(self, case_id, p):
        latest = {}
        for row in self.records(case_id, p):
            latest[row["observation_id"]] = row
        # Legacy calibration writes must invalidate an already opened new-workbench form.
        for event in self.app.calibration.events(case_id, p.reviewer):
            if event["event_type"] == "OBSERVATION_CALIBRATION" and event[
                "created_at"
            ] > latest.get(event["observation_id"], {}).get("at", ""):
                payload = json.loads(event["payload_json"])
                latest[event["observation_id"]] = {
                    "event_hash": event["event_hash"],
                    "at": event["created_at"],
                    "payload_json": canonical(
                        {
                            "action": payload["decision"],
                            "rationale": payload["rationale"],
                            "scope": "LEGACY_CALIBRATION_RECORD",
                        }
                    ),
                }
        return latest

    def dispatch(self, action, r, p):
        a = self.app
        if action in ("memory", "calibration"):
            cases = r.case_ids or (
                [r.case_id]
                if r.case_id
                else [x["case_id"] for x in a.calibration.list_cases(p.reviewer)][:20]
            )
            records = []
            days = int(os.getenv("CDF_CASE_MEMORY_RETENTION_DAYS", "365"))
            if not 1 <= days <= 3650:
                raise CalibrationError("INVALID_MEMORY_RETENTION_CONFIGURATION")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            for case in cases:
                a.authorize_case(case, p)
                for record in self.records(case, p):
                    if record["at"] < cutoff:
                        continue
                    payload = json.loads(record["payload_json"])
                    records.append(
                        {
                            "case_id": case,
                            "observation_id": record["observation_id"],
                            "version": record["event_hash"],
                            "actor": record["actor"],
                            "timestamp": record["at"],
                            "action": payload["action"],
                            "final_wording": payload["final_wording"],
                            "rationale": payload["rationale"],
                            "source_quote": payload["original_observation"].get(
                                "quote"
                            ),
                            "source_location": payload["original_observation"].get(
                                "location"
                            ),
                            "evidence_refs": payload["evidence_refs"],
                            "evidence_hash": a.store._case(case)["evidence_hash"],
                            "classification": "HISTORICAL_ILLUSTRATIVE_NOT_AUTHORITY",
                            "institutional_approval": False,
                        }
                    )
            counts = {}
            for item in records:
                counts[item["action"]] = counts.get(item["action"], 0) + 1
            return {
                "records": records[r.cursor : r.cursor + r.limit],
                "total": len(records),
                "action_counts": counts,
                "profile_status": "PROVISIONAL_NOT_APPROVED",
                "validated_human_alignment": None,
                "binding_institutional_rule": False,
                "limitations": [
                    "SYNTHETIC_LOCAL_IDENTITIES",
                    "EXPLICIT_PROFILE_PROMOTION_REQUIRED",
                ],
            }
        if action == "decisions":
            case = a.calibration.case(r.case_id, p.reviewer)
            latest = self.versions(r.case_id, p)
            return {
                "case_id": r.case_id,
                "evidence_hash": case["evidence_hash"],
                "records": [
                    {
                        "observation": o,
                        "version": latest.get(o["observation_id"], {}).get(
                            "event_hash", "NONE"
                        ),
                        "review": (
                            json.loads(latest[o["observation_id"]]["payload_json"])
                            if o["observation_id"] in latest
                            else None
                        ),
                    }
                    for o in case["observations"]
                ],
            }
        if not r.idempotency_key or not r.observation_id or r.expected_version is None:
            raise CalibrationError("DECISION_VERSION_AND_IDEMPOTENCY_REQUIRED")
        digest = fingerprint(r.model_dump())
        old = a.store.db.execute(
            "SELECT * FROM cp_human_keys WHERE actor=? AND idem_key=?",
            (p.reviewer.reviewer_id, r.idempotency_key),
        ).fetchone()
        if old:
            if old["request_hash"] != digest:
                raise Conflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST")
            return {
                "event_hash": old["event_hash"],
                "replayed": True,
                "institutional_approval": False,
            }
        case = a.calibration.case(r.case_id, p.reviewer)
        observation = next(
            (
                o
                for o in case["observations"]
                if o["observation_id"] == r.observation_id
            ),
            None,
        )
        if not observation:
            raise CalibrationError("OBSERVATION_NOT_FOUND")
        previous = (
            self.versions(r.case_id, p)
            .get(r.observation_id, {})
            .get("event_hash", "NONE")
        )
        if previous != r.expected_version:
            raise Conflict("HUMAN_DECISION_VERSION_CHANGED")
        if not r.rationale.strip():
            raise CalibrationError("RATIONALE_REQUIRED")
        if r.action == "REVISE" and not r.final_wording.strip():
            raise CalibrationError("FINAL_WORDING_REQUIRED")
        if r.action == "MERGE" and (
            r.merge_target_id == r.observation_id
            or r.merge_target_id
            not in [o["observation_id"] for o in case["observations"]]
        ):
            raise CalibrationError("VALID_SAME_CASE_MERGE_TARGET_REQUIRED")
        decision = {
            "ACCEPT": "KEEP_UNCHANGED",
            "REVISE": "KEEP_WITH_REVISIONS",
            "REJECT": "WITHDRAW",
            "MORE_EVIDENCE": "REQUEST_MORE_EVIDENCE",
            "MERGE": "MERGE_WITH_ANOTHER",
            "RECLASSIFY": "KEEP_UNCHANGED",
            "ESCALATE": "ESCALATE",
            "DISSENT": "ESCALATE",
            "DEFER": "REQUEST_MORE_EVIDENCE",
            "CLOSE": "KEEP_UNCHANGED",
        }[r.action]
        a.calibration.decision(
            r.case_id,
            r.observation_id,
            {
                "decision": decision,
                "rationale": r.rationale,
                "expected_evidence_hash": r.expected_evidence_hash,
                "status": "SUBMITTED",
                "reasons": r.reasons,
                "evidence_refs": r.evidence_refs,
                "material_categories": r.material_categories,
            },
            p.reviewer,
        )
        payload = {
            "action": r.action,
            "original_observation": observation,
            "proposed_change": r.final_wording,
            "final_wording": r.final_wording or observation.get("original_text", ""),
            "rationale": r.rationale,
            "evidence_refs": r.evidence_refs,
            "material_categories": sorted(
                set(observation.get("material_categories", []) + r.material_categories)
            ),
            "merge_target_id": r.merge_target_id,
            "human_identity_assurance": "SYNTHETIC_SESSION_NOT_VERIFIED_PERSON",
            "scope": "SYNTHETIC_REVIEW_RECORD_NOT_SIGNED_RELEASE_APPROVAL",
        }
        at = now_utc()
        event = fingerprint(
            {
                "case_id": r.case_id,
                "observation_id": r.observation_id,
                "previous": previous,
                "actor": p.reviewer.reviewer_id,
                "at": at,
                "payload": payload,
            }
        )
        a.store.db.execute(
            "INSERT INTO cp_human VALUES (?,?,?,?,?,?,?)",
            (
                event,
                r.case_id,
                r.observation_id,
                previous,
                p.reviewer.reviewer_id,
                at,
                canonical(payload),
            ),
        )
        a.store.db.execute(
            "INSERT INTO cp_human_keys VALUES (?,?,?,?)",
            (p.reviewer.reviewer_id, r.idempotency_key, digest, event),
        )
        a.store._append(
            r.case_id,
            r.observation_id,
            "HUMAN_REVIEW",
            {"version": event, "action": r.action, "institutional_approval": False},
            p.reviewer.reviewer_id,
        )
        return {
            "event_hash": event,
            "version": event,
            "case_id": r.case_id,
            "observation_id": r.observation_id,
            "action": r.action,
            "institutional_approval": False,
            "original_preserved": True,
        }
