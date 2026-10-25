"""Authoritative, mode-isolated application operations shared by every interface."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

from ..calibration.store import (
    CalibrationStore,
    CalibrationError,
    AccessDenied,
    canonical,
    fingerprint,
    now_utc,
)
from ..calibration.service import CalibrationService
from ..institutional.isolation import require_public_runtime, bind_public_database
from ..institutional.providers import PublicSyntheticProvider, ReferenceLookupService
from ..intelligence.service import IntelligenceService
from .auth import DevelopmentSessions, Principal
from .contracts import Request, Result, TOOLS

TERMINAL = {
    "COMPLETED",
    "WAITING_FOR_HUMAN",
    "FAILED",
    "CANCELLED",
    "BLOCKED_AUTHORIZATION",
}
MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


class Conflict(CalibrationError):
    pass


class ApplicationService:
    def __init__(self, path=None, *, store=None, token=None):
        database = Path(
            path
            or (
                store.path
                if store
                else os.getenv(
                    "CDF_CALIBRATION_DB", "build/public-demo/mat-calibration-dev.sqlite"
                )
            )
        ).resolve()
        require_public_runtime(
            os.getenv("CDF_OPERATION_MODE", "PUBLIC_SYNTHETIC_DEMO"), database
        )
        self.store = store or CalibrationStore(database)
        bind_public_database(self.store)
        self.calibration = CalibrationService(self.store)
        self.intelligence = IntelligenceService(self.calibration)
        self.lock = threading.RLock()
        self.store.db.executescript(
            """
          CREATE TABLE IF NOT EXISTS app_cases(case_id TEXT PRIMARY KEY,source_hash TEXT NOT NULL,
            document_blob BLOB NOT NULL,source_kind TEXT NOT NULL,created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS app_case_grants(case_id TEXT NOT NULL REFERENCES app_cases(case_id),principal_id TEXT NOT NULL,
            PRIMARY KEY(case_id,principal_id));
          CREATE TABLE IF NOT EXISTS app_operations(principal_id TEXT NOT NULL,operation TEXT NOT NULL,idem_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,result_json TEXT NOT NULL,PRIMARY KEY(principal_id,operation,idem_key));
          CREATE TABLE IF NOT EXISTS app_jobs(job_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES app_cases(case_id),
            kind TEXT NOT NULL,executor TEXT NOT NULL,status TEXT NOT NULL,session_id TEXT NOT NULL,principal_id TEXT NOT NULL,
            request_json TEXT NOT NULL,request_hash TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,
            deadline REAL,lease_token TEXT,lease_until REAL,run_id TEXT,result_json TEXT,error_code TEXT,error_stage TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0);
          CREATE UNIQUE INDEX IF NOT EXISTS one_active_review ON app_jobs(case_id)
            WHERE kind IN ('review','debate') AND status IN ('QUEUED','RUNNING');
          CREATE TABLE IF NOT EXISTS app_artifacts(artifact_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,
            job_id TEXT NOT NULL REFERENCES app_jobs(job_id),kind TEXT NOT NULL,sha256 TEXT NOT NULL,
            content BLOB NOT NULL,created_at TEXT NOT NULL,state_hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS app_agent_attempts(execution_id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES app_jobs(job_id),
            role TEXT NOT NULL,source TEXT NOT NULL,prompt_hash TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,receipt_json TEXT);
          CREATE TABLE IF NOT EXISTS app_audit(event_id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT,
            operation TEXT NOT NULL,principal_id TEXT NOT NULL,client_id TEXT NOT NULL,transport TEXT NOT NULL,
            request_hash TEXT NOT NULL,result_hash TEXT NOT NULL,created_at TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL);
        """
        )
        self.sessions = DevelopmentSessions(self.store)
        credential = (
            token if token is not None else os.getenv("CDF_CALIBRATION_DEV_TOKEN", "")
        )
        if credential:
            self.sessions.register(
                credential, ttl=int(os.getenv("CDF_DEV_SESSION_TTL_SECONDS", "3600"))
            )

    def close(self):
        self.store.close()

    def authenticate(self, token):
        with self.lock:
            return self.sessions.resolve(token)

    def authorize_case(self, case_id, principal, role="CALIBRATION_REVIEWER"):
        principal.reviewer.require(role)
        app_grant = self.store.db.execute(
            "SELECT 1 FROM app_case_grants WHERE case_id=? AND principal_id=?",
            (case_id, principal.reviewer.reviewer_id),
        ).fetchone()
        if (
            app_grant
            and not self.store.db.execute(
                "SELECT 1 FROM cases WHERE case_id=?", (case_id,)
            ).fetchone()
        ):
            return
        self.calibration.authorize(case_id, principal.reviewer, role)

    def _audit(self, operation, request, principal, transport, result):
        previous = self.store.db.execute(
            "SELECT event_hash FROM app_audit ORDER BY event_id DESC LIMIT 1"
        ).fetchone()
        material = {
            "case_id": request.case_id,
            "operation": operation,
            "principal_id": principal.reviewer.reviewer_id,
            "client_id": principal.client_id,
            "transport": transport,
            "request_hash": fingerprint(request.model_dump()),
            "result_hash": fingerprint(result),
            "created_at": now_utc(),
            "previous_hash": previous[0] if previous else "GENESIS",
        }
        digest = fingerprint(material)
        self.store.db.execute(
            "INSERT INTO app_audit(case_id,operation,principal_id,client_id,transport,request_hash,result_hash,created_at,previous_hash,event_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*material.values(), digest),
        )

    def invoke(self, tool, request: Request, principal: Principal, *, transport="CLI"):
        if tool not in TOOLS:
            raise CalibrationError("UNKNOWN_OPERATION")
        action, role, mutation = TOOLS[tool]
        # Authenticate and authorize inside the same writer transaction as the
        # audited operation, including when another worker has just committed.
        with self.lock, self.store.transaction():
            principal = self.sessions.resolve_id(principal.session_id)
            principal.reviewer.require(role)
            if str(request.case_id or "").startswith("UPL-"):
                from ..documents.policy import is_uploaded_case
                if not is_uploaded_case(request.case_id):
                    raise AccessDenied("DOCUMENT_UPLOADS_DISABLED")
                if action in ("create", "recover", "review", "debate", "probe"):
                    # An uploaded document is reviewed by the review worker, never by the synthetic job runner.
                    raise CalibrationError("UPLOADED_CASES_ARE_REVIEWED_FROM_THE_DOCUMENTS_PAGE")
            if request.issue:
                raise AccessDenied(
                    "CENTRAL_RELEASE_AUTHORIZATION_REQUIRED_NEW_EXPORTS_ARE_DRAFT_ONLY"
                )
            if (action == "calibrate" and str(transport).upper().startswith("MCP")
                    and getattr(request, "status", "DRAFT") != "DRAFT"):
                # A model client may propose a calibration draft; only a direct human interface submits one.
                raise AccessDenied("SUBMITTED_DECISION_REQUIRES_DIRECT_HUMAN_INTERFACE")
            if action not in (
                "create",
                "job",
                "job_result",
                "cancel",
                "artifact",
                "artifact_status",
            ):
                if not request.case_id:
                    raise CalibrationError("CASE_ID_REQUIRED")
                self.authorize_case(request.case_id, principal, role)
            if mutation:
                key = request.idempotency_key or "AUTO-" + uuid.uuid4().hex
                request = request.model_copy(update={"idempotency_key": key})
                digest = fingerprint(request.model_dump())
                with self.store.transaction():
                    # Acquire the writer before checking replay to serialize independent clients.
                    self.store.db.execute(
                        "UPDATE app_sessions SET revoked=revoked WHERE session_id=?",
                        (principal.session_id,),
                    )
                    old = self.store.db.execute(
                        "SELECT * FROM app_operations WHERE principal_id=? AND operation=? AND idem_key=?",
                        (principal.reviewer.reviewer_id, tool, key),
                    ).fetchone()
                    if old:
                        if old["request_hash"] != digest:
                            raise Conflict(
                                "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"
                            )
                        cached = json.loads(old["result_json"])
                        if cached["data"].get("job_id"):
                            cached["data"].update(
                                self.job(
                                    cached["data"]["job_id"], principal, request.case_id
                                )
                            )
                        cached["data"]["replayed"] = True
                        return cached
                    data = self._perform(action, request, principal)
                    result = Result(
                        ok=True, operation=tool, data={**data, "idempotency_key": key}
                    ).model_dump()
                    self._audit(tool, request, principal, transport, result)
                    self.store.db.execute(
                        "INSERT INTO app_operations VALUES (?,?,?,?,?)",
                        (
                            principal.reviewer.reviewer_id,
                            tool,
                            key,
                            digest,
                            canonical(result),
                        ),
                    )
                    return result
            with self.store.transaction():
                data = self._perform(action, request, principal)
                result = Result(ok=True, operation=tool, data=data).model_dump()
                self._audit(tool, request, principal, transport, result)
                return result

    def _perform(self, action, r, p):
        if action == "create":
            from .synthetic import source_bytes

            case_id = r.case_id or "SYN-COOPERATION-001"
            if not case_id.startswith("SYN-"):
                raise AccessDenied("PUBLIC_SYNTHETIC_CASE_REQUIRED")
            if self.store.db.execute(
                "SELECT 1 FROM app_cases WHERE case_id=?", (case_id,)
            ).fetchone():
                self.authorize_case(case_id, p, "CALIBRATION_ADMIN")
                raise Conflict("CASE_ALREADY_EXISTS_USE_ORIGINAL_IDEMPOTENCY_KEY")
            if self.store.db.execute(
                "SELECT 1 FROM cases WHERE case_id=?", (case_id,)
            ).fetchone():
                raise Conflict("EXISTING_CALIBRATION_CASE_CANNOT_BE_REPLACED")
            content = source_bytes()
            digest = hashlib.sha256(content).hexdigest()
            self.store.db.execute(
                "INSERT INTO app_cases VALUES (?,?,?,?,?)",
                (case_id, digest, content, r.source, now_utc()),
            )
            self.store.db.execute(
                "INSERT INTO app_case_grants VALUES (?,?)",
                (case_id, p.reviewer.reviewer_id),
            )
            return {
                "case_id": case_id,
                "source_hash": digest,
                "source_imported": True,
                "phase": "INTAKE",
                "synthetic": True,
            }
        if action == "recover":
            from .jobs import recover_stale, launch

            failed = recover_stale(self, case_id=r.case_id)
            pending = [
                row[0]
                for row in self.store.db.execute(
                    "SELECT job_id FROM app_jobs WHERE case_id=? AND status='QUEUED'",
                    (r.case_id,),
                )
            ]
            for job_id in pending:
                launch(self, job_id, p)
            return {
                "case_id": r.case_id,
                "stale_failed_without_replay": failed,
                "queued_resumed": pending,
            }
        if action in ("review", "debate", "docx", "xlsx", "pdf", "probe"):
            if (
                action == "debate"
                and not self.store.db.execute(
                    "SELECT 1 FROM cases WHERE case_id=?", (r.case_id,)
                ).fetchone()
            ):
                raise CalibrationError("REVIEW_REQUIRED_BEFORE_DEBATE")
            if not self.store.db.execute(
                "SELECT 1 FROM app_cases WHERE case_id=?", (r.case_id,)
            ).fetchone():
                raise CalibrationError("SOURCE_DOCUMENT_NOT_IMPORTED")
            if (
                action in MEDIA
                and not self.store.db.execute(
                    "SELECT 1 FROM executive_runs WHERE case_id=?", (r.case_id,)
                ).fetchone()
            ):
                raise CalibrationError("CAPTURED_REVIEW_REQUIRED_FOR_REPORT")
            job_id = "JOB-" + uuid.uuid4().hex
            try:
                self.store.db.execute(
                    "INSERT INTO app_jobs(job_id,case_id,kind,executor,status,session_id,principal_id,request_json,request_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        r.case_id,
                        action,
                        r.executor,
                        "QUEUED",
                        p.session_id,
                        p.reviewer.reviewer_id,
                        r.model_dump_json(),
                        fingerprint(r.model_dump()),
                        now_utc(),
                    ),
                )
            except __import__("sqlite3").IntegrityError as exc:
                raise Conflict("CASE_HAS_ACTIVE_REVIEW_OR_DEBATE") from exc
            return self.job(job_id, p, r.case_id)
        if action in ("job", "job_result", "cancel"):
            row = self._job_row(r.job_id, p, r.case_id)
            if action == "cancel":
                self.authorize_case(row["case_id"], p, "CALIBRATION_ADMIN")
                if row["status"] not in ("QUEUED", "RUNNING"):
                    raise Conflict("JOB_NO_LONGER_CANCELLABLE")
                self.store.db.execute(
                    "UPDATE app_agent_attempts SET status='OUTCOME_UNKNOWN',finished_at=? WHERE job_id=? AND status='STARTED'",
                    (now_utc(), r.job_id),
                )
                self.store.db.execute(
                    "UPDATE app_jobs SET status='CANCELLED',cancel_requested=1,finished_at=?,error_code='CANCELLED_BY_AUTHORIZED_USER' WHERE job_id=? AND status IN ('QUEUED','RUNNING')",
                    (now_utc(), r.job_id),
                )
            if action == "job_result":
                if row["status"] not in TERMINAL:
                    raise Conflict("JOB_RESULT_NOT_READY")
                return {
                    "job": self.job(r.job_id, p, r.case_id),
                    "result": json.loads(row["result_json"] or "{}"),
                    "agent_attempts": [
                        {
                            **{
                                key: attempt[key]
                                for key in (
                                    "execution_id",
                                    "role",
                                    "source",
                                    "status",
                                    "started_at",
                                    "finished_at",
                                )
                            },
                            "receipt": (
                                json.loads(attempt["receipt_json"])
                                if attempt["receipt_json"]
                                else None
                            ),
                        }
                        for attempt in self.store.db.execute(
                            "SELECT * FROM app_agent_attempts WHERE job_id=? ORDER BY started_at,execution_id",
                            (r.job_id,),
                        )
                    ],
                }
            return self.job(r.job_id, p, r.case_id)
        if action in ("artifact", "artifact_status"):
            row = self._artifact_row(r.artifact_id, p, r.case_id)
            content = row["content"]
            if hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise CalibrationError("ARTIFACT_INTEGRITY_FAILED")
            result = self.artifact_metadata(row)
            if action == "artifact":
                if r.cursor > len(content):
                    raise CalibrationError("ARTIFACT_OFFSET_OUT_OF_RANGE")
                chunk = content[r.cursor : r.cursor + 32768]
                result.update(
                    content_base64=base64.b64encode(chunk).decode(),
                    offset=r.cursor,
                    bytes_returned=len(chunk),
                    next_offset=(
                        r.cursor + len(chunk)
                        if r.cursor + len(chunk) < len(content)
                        else None
                    ),
                )
            return result
        if action == "case":
            return self.view(r.case_id, p)
        if action == "observations":
            items = self.calibration.case(r.case_id, p.reviewer)["observations"]
            return {
                "case_id": r.case_id,
                "observations": items[r.cursor : r.cursor + r.limit],
                "total": len(items),
                "next_cursor": (
                    r.cursor + r.limit if r.cursor + r.limit < len(items) else None
                ),
            }
        if action == "trace":
            snapshot = self.intelligence._snapshot(r.case_id)
            if snapshot is None:
                return {"case_id": r.case_id, "run_id": None, "trace": [], "total": 0}
            traces = snapshot.trace_records
            return {
                "case_id": r.case_id,
                "run_id": snapshot.run_id,
                "trace": traces[r.cursor : r.cursor + r.limit],
                "total": len(traces),
                "next_cursor": (
                    r.cursor + r.limit if r.cursor + r.limit < len(traces) else None
                ),
                "execution": snapshot.execution if r.cursor == 0 else None,
            }
        if action == "metrics":
            dashboard = self.intelligence.dashboard(r.case_id, p.reviewer)
            return {
                "case_id": r.case_id,
                "run_id": dashboard["run_id"],
                "metrics": dashboard["metrics"],
                "state_hash": self.state_hash(r.case_id, p),
            }
        if action == "gate":
            return {
                "case_id": r.case_id,
                "release_gate": self.intelligence.dashboard(r.case_id, p.reviewer)[
                    "release_gate"
                ],
                "official_issue_authorized": False,
            }
        if action == "history":
            events = self.calibration.events(r.case_id, p.reviewer)
            return {
                "case_id": r.case_id,
                "events": events[r.cursor : r.cursor + r.limit],
                "total": len(events),
            }
        if action == "calibrate":
            if r.decision is None:
                raise CalibrationError("EXPLICIT_CALIBRATION_DECISION_REQUIRED")
            body = {
                k: getattr(r, k)
                for k in (
                    "decision",
                    "rationale",
                    "expected_evidence_hash",
                    "status",
                    "reasons",
                    "evidence_refs",
                )
            }
            digest = self.calibration.decision(
                r.case_id, r.observation_id, body, p.reviewer
            )
            return {
                "case_id": r.case_id,
                "observation_id": r.observation_id,
                "event_hash": digest,
                "status": r.status,
                "institutional_approval": False,
            }
        lookup = ReferenceLookupService(PublicSyntheticProvider())
        if action == "authority":
            return {
                "case_id": r.case_id,
                "authorities": lookup.authorities(r.query, limit=r.limit),
                "synthetic": True,
                "binding_authority": False,
            }
        if action == "organization":
            return {
                "case_id": r.case_id,
                "responsibilities": lookup.responsibilities(r.query, limit=r.limit),
                "synthetic": True,
            }
        if action == "references":
            return {
                "case_id": r.case_id,
                "sources": PublicSyntheticProvider().catalog()["sources"],
                "private_access": "DISABLED",
            }
        raise CalibrationError("UNIMPLEMENTED_OPERATION")

    def _job_row(self, job_id, p, case_id=None):
        row = self.store.db.execute(
            "SELECT * FROM app_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            raise CalibrationError("JOB_NOT_FOUND")
        if case_id and case_id != row["case_id"]:
            raise AccessDenied("CROSS_CASE_JOB_ACCESS_DENIED")
        self.authorize_case(row["case_id"], p)
        return row

    def job(self, job_id, p, case_id=None):
        row = self._job_row(job_id, p, case_id)
        return {
            k: row[k]
            for k in (
                "job_id",
                "case_id",
                "kind",
                "executor",
                "status",
                "created_at",
                "started_at",
                "finished_at",
                "run_id",
                "error_code",
                "error_stage",
                "attempts",
            )
        }

    def _artifact_row(self, artifact_id, p, case_id=None):
        row = self.store.db.execute(
            "SELECT * FROM app_artifacts WHERE artifact_id=?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise CalibrationError("ARTIFACT_NOT_FOUND")
        if case_id and case_id != row["case_id"]:
            raise AccessDenied("CROSS_CASE_ARTIFACT_ACCESS_DENIED")
        self.authorize_case(row["case_id"], p)
        return row

    @staticmethod
    def artifact_metadata(row):
        return {
            "artifact_id": row["artifact_id"],
            "case_id": row["case_id"],
            "job_id": row["job_id"],
            "kind": row["kind"],
            "sha256": row["sha256"],
            "bytes": len(row["content"]),
            "media_type": MEDIA[row["kind"]],
            "filename": "INTERNAL_DRAFT__executive." + row["kind"],
            "created_at": row["created_at"],
            "state_hash": row["state_hash"],
            "draft": True,
            "official_issue_authorized": False,
            "download_path": "/api/artifacts/" + row["artifact_id"] + "/content",
        }

    def state_hash(self, case_id, p):
        self.authorize_case(case_id, p)
        case = self.calibration.case(case_id, p.reviewer)
        snapshot = self.intelligence._snapshot(case_id)
        return fingerprint(
            {
                "source_hash": case["source_hash"],
                "evidence_hash": case["evidence_hash"],
                "run_id": snapshot.run_id if snapshot else None,
                "calibration_version": next(
                    (
                        e["event_hash"]
                        for e in reversed(self.calibration.events(case_id, p.reviewer))
                        if e["event_type"] == "OBSERVATION_CALIBRATION"
                    ),
                    None,
                ),
            }
        )

    def view(self, case_id, p):
        self.authorize_case(case_id, p)
        intake = self.store.db.execute(
            "SELECT source_hash FROM app_cases WHERE case_id=?", (case_id,)
        ).fetchone()
        reviewed = self.store.db.execute(
            "SELECT 1 FROM cases WHERE case_id=?", (case_id,)
        ).fetchone()
        jobs = [
            self.job(r[0], p, case_id)
            for r in self.store.db.execute(
                "SELECT job_id FROM app_jobs WHERE case_id=? ORDER BY created_at",
                (case_id,),
            )
        ]
        artifacts = [
            self.artifact_metadata(r)
            for r in self.store.db.execute(
                "SELECT * FROM app_artifacts WHERE case_id=? ORDER BY created_at,artifact_id",
                (case_id,),
            )
        ]
        if not reviewed:
            return {
                "case_id": case_id,
                "source_imported": bool(intake),
                "source_hash": intake["source_hash"] if intake else None,
                "phase": "INTAKE",
                "jobs": jobs,
                "artifacts": artifacts,
                "observations": [],
                "observation_ids": [],
            }
        data = self.intelligence.dashboard(case_id, p.reviewer)
        events = self.calibration.events(case_id, p.reviewer)
        return {
            "case_id": case_id,
            "source_imported": bool(intake),
            "source_hash": self.store._case(case_id)["source_hash"],
            "evidence_hash": self.store._case(case_id)["evidence_hash"],
            "phase": "WAITING_FOR_HUMAN",
            "run_id": data["run_id"],
            "observation_ids": [o["observation_id"] for o in data["observations"]],
            "observation_count": data["observation_count"],
            "agent_status": [
                {"stage": i["stage"], "status": i["status"], "source": i["source"]}
                for i in data["invocations"]
            ],
            "evidence_references": sorted(e["id"] for e in data["evidence"]),
            "calibration_version": next(
                (
                    e["event_hash"]
                    for e in reversed(events)
                    if e["event_type"] == "OBSERVATION_CALIBRATION"
                ),
                None,
            ),
            "release_gate": data["release_gate"],
            "metrics": data["metrics"],
            "state_hash": self.state_hash(case_id, p),
            "jobs": jobs,
            "artifacts": artifacts,
            "actual_live_inference_count": data["actual_live_inference_count"],
            "synthetic": True,
        }
