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
from contextlib import contextmanager
import uuid
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
REVIEW_OUTCOMES = frozenset({"APPROVED", "RETURNED"})
UNSET = object()                # "the caller did not say which decision it read" (see save_decision)


UNKNOWN_REASON = "W15"          # "reason not known": never enough on its own to withdraw a material observation
GAP_PREFIX = "GAP:"             # a declared evidence gap, e.g. "GAP: signed minutes not yet received"
MIN_SUBSTANTIVE_LETTERS = 12


def _substantive(text: str) -> bool:
    return sum(ch.isalpha() for ch in text or "") >= MIN_SUBSTANTIVE_LETTERS


def _valid_evidence_ref(ref) -> bool:
    if not isinstance(ref, str) or not ref.strip():
        return False
    ref = ref.strip()
    return _substantive(ref[len(GAP_PREFIX):]) if ref.upper().startswith(GAP_PREFIX) else len(ref) >= 3


class CalibrationError(ValueError):
    pass


def normalize_evidence(evidence: list[dict]) -> list[dict]:
    """Server-side import rules for observation evidence (deterministic, so re-imports compare equal)."""
    from .materiality import material_review_flags
    normalized = []
    for item in evidence:
        if item.get("observed_change") == "REMOVED_FROM_VERSION" and item.get("human_decision") == "WITHDRAW":
            raise CalibrationError("ABSENCE_IS_NOT_HUMAN_WITHDRAWAL")
        if item.get("documented_withdrawal", False) is not False:
            # Only a submitted human decision documents a withdrawal; an import cannot pre-mark one.
            raise CalibrationError("DOCUMENTED_WITHDRAWAL_CANNOT_BE_IMPORTED")
        supplied = item.get("material_categories") or []
        if not isinstance(supplied, list) or not set(supplied).issubset(MATERIAL_CATEGORIES):
            raise CalibrationError("INVALID_MATERIAL_CATEGORY")
        # Review flags are recomputed here; a caller can add categories but never remove them.
        text = item.get("original_text") or item.get("text") or ""
        flags = material_review_flags(text, item.get("document_anchor"),
                                      absent=item.get("observed_change") == "REMOVED_FROM_VERSION")
        normalized.append({**item, "material_categories": sorted(set(supplied).union(flags))})
    return normalized


class StaleCase(CalibrationError):
    pass


class StaleDecision(CalibrationError):
    """Optimistic-concurrency conflict: the observation's latest decision changed since the caller read it."""


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
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)  # API serializes access at the service boundary; not for multi-worker deployments
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
            CREATE TABLE IF NOT EXISTS profile_versions (
                case_id TEXT NOT NULL REFERENCES cases(case_id),
                profile_version TEXT NOT NULL,
                profile_sha256 TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(case_id,profile_version)
            );
            CREATE TABLE IF NOT EXISTS active_profiles (
                case_id TEXT PRIMARY KEY REFERENCES cases(case_id),
                profile_version TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                FOREIGN KEY(case_id, profile_version) REFERENCES profile_versions(case_id,profile_version)
            );
            -- Append-only audit log: rows are never updated or deleted through this store.
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'AUDIT_LOG_APPEND_ONLY'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'AUDIT_LOG_APPEND_ONLY'); END;
            -- Head anchor: event count and last hash per case, so truncating the newest events is detected.
            CREATE TABLE IF NOT EXISTS chain_heads (
                case_id TEXT PRIMARY KEY REFERENCES cases(case_id),
                event_count INTEGER NOT NULL,
                head_hash TEXT NOT NULL
            );
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
        evidence = normalize_evidence(evidence)
        digest = fingerprint(evidence)
        with self.transaction():
            self.db.execute("INSERT INTO cases VALUES (?,?,?,?,?)",
                            (case_id, source_hash, digest, canonical(evidence), now_utc()))
            self._append(case_id, None, "CASE_IMPORTED", {"source_hash": source_hash, "evidence_hash": digest}, reviewer.reviewer_id)
            self.db.execute("INSERT INTO case_grants (case_id, reviewer_id) VALUES (?, ?)", (case_id, reviewer.reviewer_id))
        return digest

    @contextmanager
    def transaction(self):
        """Serialize root read/write units; nested savepoints preserve atomic publication.

        A deferred WAL reader cannot upgrade after another worker commits. Acquire
        the writer before reading so polling/auditing never fails that upgrade.
        """
        if not self.db.in_transaction:
            try:
                self.db.execute('BEGIN IMMEDIATE')
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
            return
        name='cdf_'+uuid.uuid4().hex
        self.db.execute('SAVEPOINT '+name)
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK TO SAVEPOINT '+name)
            self.db.execute('RELEASE SAVEPOINT '+name)
            raise
        else:
            self.db.execute('RELEASE SAVEPOINT '+name)

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
        self.db.execute("INSERT INTO chain_heads VALUES (?, 1, ?) ON CONFLICT(case_id) DO UPDATE SET "
                        "event_count = event_count + 1, head_hash = excluded.head_hash", (case_id, digest))
        return digest

    # ------------------------------------------------------------ derived decision state
    def _decision_events(self, case_id: str, observation_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM events WHERE case_id=? AND event_type='OBSERVATION_CALIBRATION'"
        args: list = [case_id]
        if observation_id is not None:
            sql += " AND observation_id=?"
            args.append(observation_id)
        return [dict(r) | {"payload": json.loads(r["payload_json"])} for r in self.db.execute(sql + " ORDER BY event_id", args)]

    def decision_head(self, case_id: str, observation_id: str) -> str | None:
        """Hash of the observation's latest decision event (drafts included), or None when none exists."""
        events = self._decision_events(case_id, observation_id)
        return events[-1]["event_hash"] if events else None

    def _reviews(self, case_id: str) -> dict[str, dict]:
        """Latest second-human review per decision event hash."""
        out: dict[str, dict] = {}
        for r in self.db.execute("SELECT * FROM events WHERE case_id=? AND event_type='DECISION_REVIEW' ORDER BY event_id", (case_id,)):
            payload = json.loads(r["payload_json"])
            out[payload["decision_event_hash"]] = payload | {"reviewer": r["actor"], "review_event_hash": r["event_hash"]}
        return out

    def decision_states(self, case_id: str) -> dict[str, dict]:
        """Per observation: the latest decision and its effective status.

        DRAFT / SUBMITTED come from the decision itself; APPROVED / RETURNED from a review by a different identity.
        A material withdrawal stays AWAITING_SECOND_REVIEW until such a review approves it.
        """
        reviews = self._reviews(case_id)
        latest: dict[str, dict] = {}
        for e in self._decision_events(case_id):
            latest[e["observation_id"]] = e
        out = {}
        for obs_id, e in latest.items():
            p = e["payload"]
            review = reviews.get(e["event_hash"])
            if p["status"] == "DRAFT":
                status = "DRAFT"
            elif review:
                status = review["outcome"]
            elif p.get("heightened_review"):
                status = "AWAITING_SECOND_REVIEW"
            else:
                status = "SUBMITTED"
            out[obs_id] = {"decision_event_hash": e["event_hash"], "decision": p["decision"], "status": status,
                           "decided_by": e["actor"], "heightened_review": bool(p.get("heightened_review")),
                           "reviewed_by": review["reviewer"] if review else None}
        return out

    def rule_eligible_events(self, case_id: str) -> set[str]:
        """Decision events a rule review may cite: the latest decision of its observation, submitted, and — for a
        material withdrawal — approved by a second human."""
        return {s["decision_event_hash"] for s in self.decision_states(case_id).values()
                if s["status"] in ("SUBMITTED", "APPROVED")}

    def observations(self, case_id: str, reviewer: ReviewerContext) -> list[dict]:
        reviewer.require("CALIBRATION_REVIEWER")
        return json.loads(self._case(case_id)["observations_json"])

    def save_decision(self, case_id: str, observation_id: str, decision: str, rationale: str,
                      expected_evidence_hash: str, reviewer: ReviewerContext, *,
                      reasons: list[str] | None = None, evidence_refs: list[str] | None = None,
                      material_categories: list[str] | None = None, status: str = "DRAFT",
                      expected_decision_head=UNSET):
        """Record a decision. ``expected_decision_head`` is the latest decision hash the caller read (None when it saw
        no decision). A mismatch is refused (``DECISION_CHANGED_SINCE_READ``). A caller that does not say what it
        read may only overwrite its own decisions, never another reviewer's."""
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
        if obs.get("observed_change") == "REMOVED_FROM_VERSION" and not categories:
            categories = categories.union({"CONTROL_FAILURE"})  # absence alone triggers caution, never proves invalidity
        if any(x not in REASONS for x in reasons):
            raise CalibrationError("INVALID_REASON_CODE")
        if not categories.issubset(MATERIAL_CATEGORIES):
            raise CalibrationError("INVALID_MATERIAL_CATEGORY")
        if decision == "WITHDRAW" and status == "SUBMITTED":
            if not reasons or not rationale.strip():
                raise CalibrationError("WITHDRAWAL_REASON_REQUIRED")
            if categories:
                if set(reasons) <= {UNKNOWN_REASON}:
                    raise CalibrationError("MATERIAL_WITHDRAWAL_REQUIRES_SPECIFIC_REASON")
                if not _substantive(rationale):
                    raise CalibrationError("MATERIAL_WITHDRAWAL_REQUIRES_SUBSTANTIVE_RATIONALE")
                if not evidence_refs or not all(_valid_evidence_ref(x) for x in evidence_refs):
                    raise CalibrationError("MATERIAL_WITHDRAWAL_REQUIRES_EVIDENCE_OR_GAP")
        payload = {"decision": decision, "rationale": rationale, "reasons": reasons,
                   "evidence_refs": evidence_refs, "material_categories": sorted(categories),
                   "status": status, "evidence_hash": expected_evidence_hash,
                   "heightened_review": bool(decision == "WITHDRAW" and categories)}
        with self.transaction():
            prior = self._decision_events(case_id, observation_id)
            head = prior[-1]["event_hash"] if prior else None
            if expected_decision_head is not UNSET:
                if expected_decision_head != head:
                    raise StaleDecision("DECISION_CHANGED_SINCE_READ")
            elif any(e["actor"] != reviewer.reviewer_id for e in prior):
                raise StaleDecision("EXPECTED_DECISION_HEAD_REQUIRED")
            return self._append(case_id, observation_id, "OBSERVATION_CALIBRATION", payload, reviewer.reviewer_id)

    def review_decision(self, case_id: str, decision_event_hash: str, outcome: str, rationale: str,
                        reviewer: ReviewerContext) -> str:
        """Second-human review of a submitted decision: APPROVED or RETURNED, by an identity other than the decider.
        Only the observation's latest decision can be reviewed."""
        reviewer.require("CALIBRATION_REVIEWER")
        self._case(case_id)
        if outcome not in REVIEW_OUTCOMES:
            raise CalibrationError("INVALID_REVIEW_OUTCOME")
        if not _substantive(rationale):
            raise CalibrationError("REVIEW_RATIONALE_REQUIRED")
        with self.transaction():
            state = next((s | {"observation_id": o} for o, s in self.decision_states(case_id).items()
                          if s["decision_event_hash"] == decision_event_hash), None)
            if state is None:
                raise CalibrationError("DECISION_NOT_LATEST_OR_UNKNOWN")
            if state["status"] == "DRAFT":
                raise CalibrationError("DRAFT_CANNOT_BE_REVIEWED")
            if state["decided_by"] == reviewer.reviewer_id:
                raise AccessDenied("SECOND_REVIEWER_MUST_DIFFER")
            return self._append(case_id, state["observation_id"], "DECISION_REVIEW",
                                {"decision_event_hash": decision_event_hash, "outcome": outcome, "rationale": rationale},
                                reviewer.reviewer_id)

    def rule_action(self, case_id: str, rule_id: str, action: str, rationale: str,
                    reviewer: ReviewerContext, *, observation_event_hashes: list[str],
                    profile_version: str):
        reviewer.require("DNA_RULE_APPROVER")
        self._case(case_id)
        if action not in RULE_ACTIONS or not rule_id or not profile_version or not rationale.strip():
            raise CalibrationError("INVALID_RULE_APPROVAL")
        if profile_version not in self.known_profile_versions(case_id):
            raise CalibrationError("UNKNOWN_PROFILE_VERSION")
        submitted = {x["event_hash"] for x in self._decision_events(case_id) if x["payload"].get("status") == "SUBMITTED"}
        if not observation_event_hashes or not set(observation_event_hashes).issubset(submitted):
            raise CalibrationError("UNKNOWN_CALIBRATION_EVIDENCE")
        states = {s["decision_event_hash"]: s for s in self.decision_states(case_id).values()}
        for h in observation_event_hashes:
            st = states.get(h)
            if st is None:
                raise CalibrationError("SUPERSEDED_CALIBRATION_EVIDENCE")
            if st["status"] == "AWAITING_SECOND_REVIEW":
                raise CalibrationError("MATERIAL_WITHDRAWAL_NOT_SECOND_REVIEWED")
            if st["status"] == "RETURNED":
                raise CalibrationError("RETURNED_DECISION_CANNOT_SUPPORT_RULE")
        payload = {"rule_id": rule_id, "action": action, "rationale": rationale,
                   "observation_event_hashes": sorted(set(observation_event_hashes)),
                   "profile_version": profile_version}
        with self.transaction():
            return self._append(case_id, None, "DNA_RULE_REVIEW", payload, reviewer.reviewer_id)

    def known_profile_versions(self, case_id: str) -> set[str]:
        """Versions a rule review may target: the base profile the case starts from and every stored version."""
        from cdf_gco_crms.agents.mat_profile import load_profile, synthetic_fixture_path
        versions = {r["profile_version"] for r in self.db.execute("SELECT profile_version FROM profile_versions WHERE case_id=?", (case_id,))}
        versions.add(load_profile(synthetic_fixture_path()).version)
        return versions

    def chain_head(self, case_id: str) -> dict:
        """Event count and head hash, for recording outside this database (the in-database anchor detects
        truncation by this store's users; an external copy detects a privileged rewrite)."""
        row = self.db.execute("SELECT event_count, head_hash FROM chain_heads WHERE case_id=?", (case_id,)).fetchone()
        return {"case_id": case_id, "event_count": row["event_count"] if row else 0, "head_hash": row["head_hash"] if row else "GENESIS"}

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
        anchor = self.chain_head(case_id)
        return anchor["event_count"] == len(events) and anchor["head_hash"] == previous

    def case_statistics(self, case_id: str, reviewer: ReviewerContext):
        items = self.observations(case_id, reviewer)
        events = self.events(case_id, reviewer)
        submitted = [e for e in events if e["event_type"] == "OBSERVATION_CALIBRATION"
                     and json.loads(e["payload_json"])["status"] == "SUBMITTED"]
        latest = {}
        for e in submitted:
            latest[e["observation_id"]] = json.loads(e["payload_json"])
        states = self.decision_states(case_id)
        rule_latest: dict[str, str] = {}
        for e in events:
            if e["event_type"] == "DNA_RULE_REVIEW":
                p = json.loads(e["payload_json"])
                rule_latest[p["rule_id"]] = p["action"]          # the latest review of a rule is the effective one
        return {"observation_count": len(items), "submitted_observations": len(latest),
                "pending_observations": len(items) - len(latest),
                "withdrawal_proposals": sum(d["decision"] == "WITHDRAW" for d in latest.values()),
                "heightened_review": sum(bool(d["heightened_review"]) for d in latest.values()),
                "awaiting_second_review": sum(s["status"] == "AWAITING_SECOND_REVIEW" for s in states.values()),
                "approved_decisions": sum(s["status"] == "APPROVED" for s in states.values()),
                "returned_decisions": sum(s["status"] == "RETURNED" for s in states.values()),
                "approved_dna_rules": sum(a == "APPROVE" for a in rule_latest.values()),
                # APPROVE_WITH_CHANGES needs the changed wording before it can compile (CAL-01); never counted as approved
                "rules_approved_with_changes_pending_wording": sum(a == "APPROVE_WITH_CHANGES" for a in rule_latest.values()),
                "audit_chain_valid": self.verify_chain(case_id, reviewer),
                "audit_chain_head": self.chain_head(case_id)}

    def save_synthetic_profile(self, case_id: str, profile: dict, reviewer: ReviewerContext) -> dict:
        reviewer.require("DNA_RULE_APPROVER")
        self._case(case_id)
        if not profile.get("synthetic") or profile.get("status") != "PROVISIONAL" or profile.get("human_approval_status") != "NOT_APPROVED":
            raise CalibrationError("ONLY_PROVISIONAL_SYNTHETIC_PROFILE_SUPPORTED")
        ver = profile.get("version")
        if not isinstance(ver, str) or not ver:
            raise CalibrationError("PROFILE_VERSION_REQUIRED")
        digest = fingerprint(profile)
        with self.transaction():
            self.db.execute("INSERT INTO profile_versions VALUES (?,?,?,?,?,?)",
                            (case_id, ver, digest, canonical(profile), reviewer.reviewer_id, now_utc()))
            self._append(case_id, None, "SYNTHETIC_PROFILE_COMPILED",
                         {"profile_version": ver, "profile_sha256": digest, "binding_allowed": False}, reviewer.reviewer_id)
        return {"case_id": case_id, "profile_version": ver, "profile_sha256": digest,
                "status": "PROVISIONAL", "institutional_approval": "NOT_AUTHORIZED"}

    def profile_versions(self, case_id: str, reviewer: ReviewerContext) -> list[dict]:
        reviewer.require("CALIBRATION_REVIEWER")
        self._case(case_id)
        active = self.db.execute("SELECT profile_version FROM active_profiles WHERE case_id=?", (case_id,)).fetchone()
        return [{"profile_version": r["profile_version"], "profile_sha256": r["profile_sha256"],
                 "created_by": r["created_by"], "created_at": r["created_at"],
                 "active": bool(active and active["profile_version"] == r["profile_version"])}
                for r in self.db.execute("SELECT * FROM profile_versions WHERE case_id=? ORDER BY created_at,profile_version", (case_id,))]

    def activate_synthetic_profile(self, case_id: str, version: str, reviewer: ReviewerContext) -> dict:
        reviewer.require("DNA_RULE_APPROVER")
        self._case(case_id)
        record = self.db.execute("SELECT profile_sha256,profile_json FROM profile_versions WHERE case_id=? AND profile_version=?",
                                 (case_id, version)).fetchone()
        if record is None:
            raise CalibrationError("PROFILE_VERSION_NOT_FOUND")
        p = json.loads(record["profile_json"])
        if not p.get("synthetic") or p.get("status") != "PROVISIONAL":
            raise CalibrationError("SYNTHETIC_PROVISIONAL_ONLY")
        with self.transaction():
            self.db.execute("INSERT OR REPLACE INTO active_profiles VALUES (?,?,?)", (case_id, version, now_utc()))
            self._append(case_id, None, "SYNTHETIC_PROFILE_ACTIVATED",
                         {"profile_version": version, "profile_sha256": record["profile_sha256"],
                          "institutional_approval": "NOT_AUTHORIZED"}, reviewer.reviewer_id)
        return {"profile_version": version, "active": True, "institutional_approval": "NOT_AUTHORIZED"}

    def synthetic_profile_document(self, case_id: str, version: str, reviewer: ReviewerContext) -> dict:
        reviewer.require("CALIBRATION_REVIEWER")
        self._case(case_id)
        row = self.db.execute("SELECT profile_sha256,profile_json FROM profile_versions WHERE case_id=? AND profile_version=?",
                              (case_id, version)).fetchone()
        if row is None:
            raise CalibrationError("PROFILE_VERSION_NOT_FOUND")
        content = json.loads(row["profile_json"])
        if fingerprint(content) != row["profile_sha256"] or not content.get("synthetic"):
            raise CalibrationError("INVALID_SYNTHETIC_PROFILE_INTEGRITY")
        return content
