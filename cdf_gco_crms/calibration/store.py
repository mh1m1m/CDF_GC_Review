"""Private MAT human calibration persistence and fail-closed decision policy.

Library module only. A trusted calling application MUST authenticate the reviewer and
authorize their roles before constructing ReviewerContext. Do not expose directly via HTTP.
No institutional case data belongs in the public GitHub repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

DECISIONS = frozenset({
    "KEEP_UNCHANGED", "KEEP_WITH_REVISIONS", "STRENGTHEN", "SOFTEN",
    "SHORTEN", "EXPAND", "CONVERT_TO_QUESTION", "CONVERT_TO_RECOMMENDATION",
    "NARROW_SCOPE", "MERGE_WITH_ANOTHER", "REQUEST_MORE_EVIDENCE",
    "ESCALATE", "WITHDRAW",
})
REASONS = frozenset(f"W{i:02d}" for i in range(1, 16))
MATERIAL_CATEGORIES = frozenset({
    "REGULATORY", "AML", "FINANCIAL_CRIME", "DATA_PROTECTION",
    "DELEGATED_AUTHORITY", "SEGREGATION_OF_DUTIES", "FINANCIAL_EXPOSURE",
    "AUDIT_RIGHTS", "CONTROL_FAILURE", "CONTRACTUAL_LIABILITY",
})
RULE_ACTIONS = frozenset({"APPROVE", "APPROVE_WITH_CHANGES", "REJECT", "DEFER", "REQUEST_MORE_EVIDENCE"})


class CalibrationError(ValueError):
    pass


class StaleCase(CalibrationError):
    pass


class AccessDenied(CalibrationError):
    pass


@dataclass(frozen=True)
class ReviewerContext:
    """Identity/roles verified outside this module by a trusted auth boundary."""
    reviewer_id: str
    roles: frozenset[str]
    authenticated: bool = False

    def require(self, role: str):
        if not self.authenticated or not self.reviewer_id or role not in self.roles:
            raise AccessDenied("AUTHENTICATED_ROLE_REQUIRED")


def canonical(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(data: Any) -> str:
    return sha256(canonical(data).encode("utf-8")).hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class CalibrationStore:
    """SQLite event log. Local pilot only; external DB controls backups/access."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if self.path == Path(":memory:").resolve():
            raise CalibrationError("MEMORY_DB_DISALLOWED_FOR_AUDIT")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.is_symlink():
            raise CalibrationError("SYMLINK_DB_DISALLOWED")
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                source_hash TEXT NOT NULL,
                evidence_hash TEXT NOT NULL,
                observations_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES cases(case_id),
                observation_id TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_case ON events(case_id, event_id);
            CREATE TABLE IF NOT EXISTS case_grants (case_id TEXT NOT NULL REFERENCES cases(case_id), reviewer_id TEXT NOT NULL, PRIMARY KEY(case_id, reviewer_id));
        """)
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def close(self):
        self.db.close()

    def import_case(self, case_id: str, source_hash: str, evidence: list[dict], reviewer: ReviewerContext):
        reviewer.require("CALIBRATION_ADMIN")
        if not case_id or len(source_hash) != 64 or any(ch not in "0123456789abcdef" for ch in source_hash):
            raise CalibrationError("INVALID_SOURCE_SHA256")
        if not evidence or not all(isinstance(x, dict) and x.get("observation_id") for x in evidence):
            raise CalibrationError("INVALID_EVIDENCE")
        ids = [x["observation_id"] for x in evidence]
        if len(set(ids)) != len(ids):
            raise CalibrationError("DUPLICATE_OBSERVATION")
        for item in evidence:
            if item.get("observed_change") == "REMOVED_FROM_VERSION" and item.get("human_decision") == "WITHDRAW":
                raise CalibrationError("ABSENCE_IS_NOT_HUMAN_WITHDRAWAL")
        digest = fingerprint(evidence)
        with self.db:
            self.db.execute("INSERT INTO cases VALUES (?,?,?,?,?)",
                            (case_id, source_hash, digest, canonical(evidence), now_utc()))
            self._append(case_id, None, "CASE_IMPORTED", {"source_hash": source_hash, "evidence_hash": digest}, reviewer.reviewer_id)
            self.db.execute("INSERT INTO case_grants (case_id, reviewer_id) VALUES (?, ?)", (case_id, reviewer.reviewer_id))
        return digest

    def _case(self, case_id: str):
        row = self.db.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if row is None:
            raise CalibrationError("CASE_NOT_FOUND")
        return row

    def _append(self, case_id, obs_id, kind, payload, actor):
        prev = self.db.execute(
            "SELECT event_hash FROM events WHERE case_id=? ORDER BY event_id DESC LIMIT 1", (case_id,)
        ).fetchone()
        previous = prev["event_hash"] if prev else "GENESIS"
        timestamp = now_utc()
        material = {"case_id": case_id, "observation_id": obs_id, "event_type": kind,
                    "payload": payload, "actor": actor, "created_at": timestamp, "previous_hash": previous}
        digest = fingerprint(material)
        self.db.execute("INSERT INTO events(case_id,observation_id,event_type,payload_json,actor,created_at,previous_hash,event_hash) VALUES (?,?,?,?,?,?,?,?)",
                        (case_id, obs_id, kind, canonical(payload), actor, timestamp, previous, digest))
        return digest

    def observations(self, case_id: str, reviewer: ReviewerContext) -> list[dict]:
        reviewer.require("CALIBRATION_REVIEWER")
        return json.loads(self._case(case_id)["observations_json"])

    def save_decision(self, case_id: str, observation_id: str, decision: str, rationale: str,
                      expected_evidence_hash: str, reviewer: ReviewerContext, *,
                      reasons: list[str] | None = None, evidence_refs: list[str] | None = None,
                      material_categories: list[str] | None = None, status: str = "DRAFT"):
        reviewer.require("CALIBRATION_REVIEWER")
        row = self._case(case_id)
        if row["evidence_hash"] != expected_evidence_hash:
            raise StaleCase("EVIDENCE_HASH_CHANGED")
        items = json.loads(row["observations_json"])
        obs = next((o for o in items if o["observation_id"] == observation_id), None)
        if obs is None:
            raise CalibrationError("OBSERVATION_NOT_FOUND")
        if decision not in DECISIONS:
            raise CalibrationError("INVALID_DECISION")
        if status not in ("DRAFT", "SUBMITTED"):
            raise CalibrationError("INVALID_STATUS")
        if status == "SUBMITTED" and not rationale.strip():
            raise CalibrationError("RATIONALE_REQUIRED")
        reasons = reasons or []
        evidence_refs = evidence_refs or []
        categories = frozenset(material_categories or []).union(obs.get("material_categories", []))
        if any(x not in REASONS for x in reasons):
            raise CalibrationError("INVALID_REASON_CODE")
        if not categories.issubset(MATERIAL_CATEGORIES):
            raise CalibrationError("INVALID_MATERIAL_CATEGORY")
        if decision == "WITHDRAW" and status == "SUBMITTED":
            if not reasons or not rationale.strip():
                raise CalibrationError("WITHDRAWAL_REASON_REQUIRED")
            if categories and not evidence_refs:
                raise CalibrationError("MATERIAL_WITHDRAWAL_REQUIRES_EVIDENCE_OR_GAP")
        payload = {"decision": decision, "rationale": rationale, "reasons": reasons,
                   "evidence_refs": evidence_refs, "material_categories": sorted(categories),
                   "status": status, "evidence_hash": expected_evidence_hash,
                   "heightened_review": bool(decision == "WITHDRAW" and categories)}
        with self.db:
            return self._append(case_id, observation_id, "OBSERVATION_CALIBRATION", payload, reviewer.reviewer_id)

    def rule_action(self, case_id: str, rule_id: str, action: str, rationale: str,
                    reviewer: ReviewerContext, *, observation_event_hashes: list[str],
                    profile_version: str):
        reviewer.require("DNA_RULE_APPROVER")
        self._case(case_id)
        if action not in RULE_ACTIONS or not rule_id or not profile_version or not rationale.strip():
            raise CalibrationError("INVALID_RULE_APPROVAL")
        event_hashes = {x["event_hash"] for x in self.db.execute(
            "SELECT event_hash FROM events WHERE case_id=? AND event_type='OBSERVATION_CALIBRATION'",
            (case_id,))}
        if not observation_event_hashes or not set(observation_event_hashes).issubset(event_hashes):
            raise CalibrationError("UNKNOWN_CALIBRATION_EVIDENCE")
        payload = {"rule_id": rule_id, "action": action, "rationale": rationale,
                   "observation_event_hashes": sorted(set(observation_event_hashes)),
                   "profile_version": profile_version}
        with self.db:
            return self._append(case_id, None, "DNA_RULE_REVIEW", payload, reviewer.reviewer_id)

    def events(self, case_id: str, reviewer: ReviewerContext):
        reviewer.require("CALIBRATION_REVIEWER")
        self._case(case_id)
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM events WHERE case_id=? ORDER BY event_id", (case_id,))]

    def verify_chain(self, case_id: str, reviewer: ReviewerContext) -> bool:
        events = self.events(case_id, reviewer)
        previous = "GENESIS"
        for e in events:
            material = {"case_id": e["case_id"], "observation_id": e["observation_id"],
                        "event_type": e["event_type"], "payload": json.loads(e["payload_json"]),
                        "actor": e["actor"], "created_at": e["created_at"], "previous_hash": previous}
            if e["previous_hash"] != previous or e["event_hash"] != fingerprint(material):
                return False
            previous = e["event_hash"]
        return True

    def case_statistics(self, case_id: str, reviewer: ReviewerContext):
        items = self.observations(case_id, reviewer)
        events = self.events(case_id, reviewer)
        submitted = [e for e in events if e["event_type"] == "OBSERVATION_CALIBRATION"
                     and json.loads(e["payload_json"])["status"] == "SUBMITTED"]
        latest = {}
        for e in submitted:
            latest[e["observation_id"]] = json.loads(e["payload_json"])
        return {"observation_count": len(items), "submitted_observations": len(latest),
                "pending_observations": len(items) - len(latest),
                "withdrawal_proposals": sum(d["decision"] == "WITHDRAW" for d in latest.values()),
                "heightened_review": sum(bool(d["heightened_review"]) for d in latest.values()),
                "approved_dna_rules": sum(e["event_type"] == "DNA_RULE_REVIEW" and
                        json.loads(e["payload_json"])["action"] in ("APPROVE", "APPROVE_WITH_CHANGES") for e in events),
                "audit_chain_valid": self.verify_chain(case_id, reviewer)}
