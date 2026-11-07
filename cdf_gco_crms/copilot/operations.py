"""Local operational measurements and offline staging recovery; no deployment switch."""

import hashlib, json, shutil, sqlite3, time, uuid
from pathlib import Path
from ..calibration.store import (
    AccessDenied,
    CalibrationError,
    canonical,
    now_utc,
    fingerprint,
)
from ..execution.providers import readiness


class OperationsService:
    def __init__(self, app):
        self.app = app
        app.store.db.executescript(
            """CREATE TABLE IF NOT EXISTS cp_metrics(id INTEGER PRIMARY KEY,operation TEXT NOT NULL,status TEXT NOT NULL,duration_ms REAL NOT NULL,error_code TEXT,at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cp_backups(backup_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cp_rates(session_id TEXT NOT NULL,window INTEGER NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(session_id,window));
        CREATE TABLE IF NOT EXISTS cp_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
        """
        )
        with app.store.transaction():
            app.store.db.execute(
                "INSERT OR IGNORE INTO cp_migrations VALUES (1,?)", (now_utc(),)
            )

    def rate(self, p):
        with self.app.lock, self.app.store.transaction():
            window = int(time.time() // 60)
            self.app.store.db.execute(
                "DELETE FROM cp_rates WHERE window<?", (window - 2,)
            )
            self.app.store.db.execute(
                "INSERT INTO cp_rates VALUES (?,?,1) ON CONFLICT(session_id,window) DO UPDATE SET count=count+1",
                (p.session_id, window),
            )
            count = self.app.store.db.execute(
                "SELECT count FROM cp_rates WHERE session_id=? AND window=?",
                (p.session_id, window),
            ).fetchone()[0]
        if count > 120:
            raise CalibrationError("RATE_LIMIT_EXCEEDED")

    def metric(self, operation, status, duration_ms, error_code=None):
        # Dimensions are server enums/codes, never raw exception bodies, prompts or tokens.
        with self.app.lock, self.app.store.transaction():
            self.app.store.db.execute(
                "INSERT INTO cp_metrics(operation,status,duration_ms,error_code,at) VALUES (?,?,?,?,?)",
                (operation, status, round(duration_ms, 3), error_code, now_utc()),
            )

    @staticmethod
    def audit_valid(db):
        previous = "GENESIS"
        for row in db.execute("SELECT * FROM app_audit ORDER BY event_id"):
            record = dict(row)
            body = {
                key: record[key]
                for key in (
                    "case_id",
                    "operation",
                    "principal_id",
                    "client_id",
                    "transport",
                    "request_hash",
                    "result_hash",
                    "created_at",
                    "previous_hash",
                )
            }
            if (
                body["previous_hash"] != previous
                or fingerprint(body) != record["event_hash"]
            ):
                return False
            previous = record["event_hash"]
        return True

    def dispatch(self, action, r, p):
        a = self.app
        p.reviewer.require("CALIBRATION_ADMIN")
        if action == "executors":
            result = readiness()
            for name, item in result.items():
                item.update(
                    authenticated="NOT_VERIFIED",
                    tested="NO_COMPLETION_RECEIPT_IN_THIS_REGISTRY",
                    cost=None,
                )
            return {
                "executors": result,
                "limitations": [
                    "CONFIGURED_IS_NOT_AUTHENTICATED",
                    "CONSUMER_LOGIN_IS_NOT_INSTITUTIONAL_AUTHORIZATION",
                    "NO_AUTOMATIC_SUBSTITUTION",
                ],
            }
        if action == "health":
            counts = {
                row["status"]: row["n"]
                for row in a.store.db.execute(
                    "SELECT status,COUNT(*) n FROM app_jobs GROUP BY status"
                )
            }
            durations = []
            queue = []
            by_kind = {}
            from datetime import datetime

            for row in a.store.db.execute(
                "SELECT kind,executor,created_at,started_at,finished_at FROM app_jobs"
            ):
                if row["started_at"]:
                    queue.append(
                        (
                            datetime.fromisoformat(row["started_at"])
                            - datetime.fromisoformat(row["created_at"])
                        ).total_seconds()
                    )
                if row["finished_at"] and row["started_at"]:
                    durations.append(
                        (
                            datetime.fromisoformat(row["finished_at"])
                            - datetime.fromisoformat(row["started_at"])
                        ).total_seconds()
                    )
                    key = row["kind"] + "/" + row["executor"]
                    by_kind.setdefault(key, []).append(durations[-1])
            integrity = a.store.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            audit = self.audit_valid(a.store.db)
            events = [
                dict(row)
                for row in a.store.db.execute(
                    "SELECT operation,status,COUNT(*) count,AVG(duration_ms) mean_duration_ms FROM cp_metrics GROUP BY operation,status"
                )
            ]
            return {
                "status": "AVAILABLE" if integrity and audit else "DEGRADED",
                "database_integrity": integrity,
                "audit_chain_integrity": audit,
                "job_counts": counts,
                "mean_queue_seconds": sum(queue) / len(queue) if queue else None,
                "job_duration_by_kind": {
                    key: {
                        "samples": len(values),
                        "mean_seconds": sum(values) / len(values),
                    }
                    for key, values in by_kind.items()
                },
                "mean_execution_seconds": (
                    sum(durations) / len(durations) if durations else None
                ),
                "metrics": events,
                "human_backlog": sum(
                    json.loads(row[0])["status"] == "WAITING_FOR_HUMAN"
                    for row in a.store.db.execute("SELECT state_json FROM cp_workflows")
                ),
                "private_activation": "DISABLED",
                "provider_api_inference_count": a.store.db.execute(
                    "SELECT COUNT(*) FROM app_agent_attempts WHERE source='PROVIDER_API' AND status='OK'"
                ).fetchone()[0],
                "production_readiness": "PENDING_AUTHORIZATION",
                "schema_version": 1,
            }
        # Backup is server-side only and is never a downloadable public artifact.
        ids = {
            row[0]
            for row in a.store.db.execute(
                "SELECT case_id FROM cases UNION SELECT case_id FROM app_cases"
            )
        }
        for case in ids:
            a.authorize_case(case, p, "CALIBRATION_ADMIN")
        directory = a.store.path.parent / "managed-backups"
        directory.mkdir(mode=0o700, exist_ok=True)
        if action == "backup":
            identifier = "BACKUP-" + uuid.uuid4().hex
            path = directory / (identifier + ".sqlite")
            source = sqlite3.connect("file:" + str(a.store.path) + "?mode=ro", uri=True)
            destination = sqlite3.connect(path)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            a.store.db.execute(
                "INSERT INTO cp_backups VALUES (?,?,?)", (identifier, digest, now_utc())
            )
            return {
                "backup_id": identifier,
                "sha256": digest,
                "public_download": False,
                "scope": "ALL_CASES_EXPLICITLY_AUTHORIZED_LOCAL_BACKUP",
            }
        row = a.store.db.execute(
            "SELECT * FROM cp_backups WHERE backup_id=?", (r.backup_id,)
        ).fetchone()
        if row is None:
            raise CalibrationError("BACKUP_NOT_FOUND")
        source = directory / (r.backup_id + ".sqlite")
        if (
            source.is_symlink()
            or hashlib.sha256(source.read_bytes()).hexdigest() != row["sha256"]
        ):
            raise CalibrationError("BACKUP_INTEGRITY_FAILED")
        target = directory / ("staging-" + uuid.uuid4().hex + ".sqlite")
        shutil.copyfile(source, target)
        restored = sqlite3.connect(target)
        restored.row_factory = sqlite3.Row
        try:
            if (
                restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or restored.execute("PRAGMA foreign_key_check").fetchone()
            ):
                raise CalibrationError("RESTORE_INTEGRITY_FAILED")
            if not self.audit_valid(restored):
                raise CalibrationError("RESTORE_AUDIT_CHAIN_INVALID")
            restored.execute("UPDATE app_sessions SET revoked=1")
            restored.commit()
        finally:
            restored.close()
        return {
            "backup_id": r.backup_id,
            "verification": "PASS",
            "staging_id": target.stem,
            "active_database_overwritten": False,
            "restored_sessions_revoked": True,
            "jobs_automatically_replayed": False,
        }
