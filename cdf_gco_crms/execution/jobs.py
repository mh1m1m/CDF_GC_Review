"""Durable SQLite jobs with separate supervised workers and atomic publication.

A stale/ambiguous provider job is failed, never automatically replayed. Idempotency
prevents duplicate accepted operations; external exactly-once inference is not claimed.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess  # nosec B404
import sys
import tempfile
import time
import uuid
import psutil

from .service import ApplicationService, TERMINAL
from .contracts import Request
from ..calibration.store import AccessDenied, CalibrationError, canonical, now_utc
from ..agents.tracing import TraceWriter

ROOT = Path(__file__).resolve().parents[2]


def kill_tree(pid):
    try:
        root = psutil.Process(pid)
        children = root.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        root.kill()
        psutil.wait_procs([root, *children], timeout=3)
    except psutil.NoSuchProcess:
        pass


def inline_runner() -> bool:
    """Serverless hosts (Vercel functions) kill detached processes when the response ends, so jobs run inside
    the request there: CDF_JOB_RUNNER=inline. The claim, lease, authorization and publication steps are the same."""
    return os.getenv("CDF_JOB_RUNNER", "").strip().lower() == "inline"


def launch(service, job_id, principal):
    job = service.job(job_id, principal)
    if job["status"] != "QUEUED":
        return
    if inline_runner():
        supervise(service.store.path, job_id, inline=True)
        return None
    # No user-supplied executable, shell, path or credential argument.
    process = subprocess.Popen(
        [
            sys.executable,  # nosec B603
            "-m",
            "cdf_gco_crms.execution.jobs",
            "supervise",
            "--db",
            str(service.store.path),
            "--job",
            job_id,
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return process.pid


def recover_stale(service, *, case_id=None):
    with service.store.transaction():
        if case_id:
            rows = service.store.db.execute(
                "SELECT job_id FROM app_jobs WHERE case_id=? AND status='RUNNING' AND lease_until<?",
                (case_id, time.time()),
            ).fetchall()
        else:
            rows = service.store.db.execute(
                "SELECT job_id FROM app_jobs WHERE status='RUNNING' AND lease_until<?",
                (time.time(),),
            ).fetchall()
        for row in rows:
            service.store.db.execute(
                "UPDATE app_jobs SET status='FAILED',error_code='STALE_EXECUTION_OUTCOME_UNKNOWN_NO_AUTOMATIC_REPLAY',finished_at=? WHERE job_id=? AND status='RUNNING'",
                (now_utc(), row[0]),
            )
            service.store.db.execute(
                "UPDATE app_agent_attempts SET status='OUTCOME_UNKNOWN',finished_at=? WHERE job_id=? AND status='STARTED'",
                (now_utc(), row[0]),
            )
    return len(rows)


def supervise(database, job_id, *, inline=False):
    service = ApplicationService(database)
    lease = uuid.uuid4().hex
    try:
        with service.store.transaction():
            row = service.store.db.execute(
                "SELECT * FROM app_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or row["status"] != "QUEUED":
                return 0
            try:
                p = service.sessions.resolve_id(row["session_id"])
                service.authorize_case(
                    row["case_id"],
                    p,
                    (
                        "CALIBRATION_ADMIN"
                        if row["kind"] in ("review", "debate", "probe")
                        else "CALIBRATION_REVIEWER"
                    ),
                )
            except AccessDenied:
                service.store.db.execute(
                    "UPDATE app_jobs SET status='BLOCKED_AUTHORIZATION',error_code='AUTHORIZATION_LOST_BEFORE_EXECUTION',finished_at=? WHERE job_id=?",
                    (now_utc(), job_id),
                )
                return 3
            timeout = json.loads(row["request_json"])["timeout"]
            deadline = time.time() + timeout
            changed = service.store.db.execute(
                "UPDATE app_jobs SET status='RUNNING',started_at=?,deadline=?,lease_token=?,lease_until=?,attempts=attempts+1 WHERE job_id=? AND status='QUEUED'",
                (now_utc(), deadline, lease, time.time() + 15, job_id),
            ).rowcount
            if changed != 1:
                return 0
        if inline:
            with tempfile.TemporaryDirectory(prefix="cdf-job-") as workspace:
                try:
                    compute(database, job_id, lease, workspace)
                except Exception as exc:  # noqa: BLE001 - the job is marked failed below; the cause is logged
                    logging.getLogger(__name__).warning("inline job %s raised %s", job_id, type(exc).__name__)
            current = service.store.db.execute("SELECT status FROM app_jobs WHERE job_id=?", (job_id,)).fetchone()
            if current["status"] == "RUNNING":
                fail(service, job_id, lease, "WORKER_EXITED_WITHOUT_PUBLICATION")
            return 0
        with tempfile.TemporaryDirectory(prefix="cdf-job-") as workspace:
            process = subprocess.Popen(
                [
                    sys.executable,  # nosec B603
                    "-m",
                    "cdf_gco_crms.execution.jobs",
                    "compute",
                    "--db",
                    str(service.store.path),
                    "--job",
                    job_id,
                    "--lease",
                    lease,
                    "--workspace",
                    workspace,
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            while process.poll() is None:
                current = service.store.db.execute(
                    "SELECT status,session_id FROM app_jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                expired = time.time() > deadline
                try:
                    service.sessions.resolve_id(current["session_id"])
                    auth = True
                except AccessDenied:
                    auth = False
                if current["status"] != "RUNNING" or expired or not auth:
                    kill_tree(process.pid)
                    process.wait(timeout=5)
                    if current["status"] == "RUNNING":
                        status = "FAILED" if expired else "BLOCKED_AUTHORIZATION"
                        code = (
                            "JOB_TIMEOUT_OUTCOME_UNKNOWN"
                            if expired
                            else "AUTHORIZATION_LOST_DURING_EXECUTION"
                        )
                        fail(service, job_id, lease, code, status=status)
                    break
                with service.store.transaction():
                    service.store.db.execute(
                        "UPDATE app_jobs SET lease_until=? WHERE job_id=? AND status='RUNNING' AND lease_token=?",
                        (time.time() + 15, job_id, lease),
                    )
                time.sleep(0.15)
            current = service.store.db.execute(
                "SELECT status FROM app_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if current["status"] == "RUNNING":
                fail(service, job_id, lease, "WORKER_EXITED_WITHOUT_PUBLICATION")
    finally:
        service.close()
    return 0


def fail(service, job_id, lease, code, *, stage=None, status="FAILED"):
    with service.store.transaction():
        if stage is None:
            attempt = service.store.db.execute(
                "SELECT role FROM app_agent_attempts WHERE job_id=? AND status='STARTED' ORDER BY started_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            stage = attempt["role"] if attempt else "SUPERVISION"
        service.store.db.execute(
            "UPDATE app_jobs SET status=?,error_code=?,error_stage=?,finished_at=? WHERE job_id=? AND status='RUNNING' AND lease_token=?",
            (status, code, stage, now_utc(), job_id, lease),
        )
        service.store.db.execute(
            "UPDATE app_agent_attempts SET status='OUTCOME_UNKNOWN',finished_at=? WHERE job_id=? AND status='STARTED'",
            (now_utc(), job_id),
        )


class JobTrace(TraceWriter):
    def __init__(self, service, job_id):
        super().__init__()
        self.service = service
        self.job_id = job_id

    def started(self, request, execution_id, source):
        with self.service.store.transaction():
            self.service.store.db.execute(
                "INSERT INTO app_agent_attempts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    execution_id,
                    self.job_id,
                    request.role,
                    source,
                    request.prompt_hash,
                    "STARTED",
                    now_utc(),
                    None,
                    None,
                ),
            )

    def record(self, response, **extra):
        result = super().record(response, Application_Job_ID=self.job_id, **extra)
        with self.service.store.transaction():
            self.service.store.db.execute(
                "UPDATE app_agent_attempts SET status=?,finished_at=?,receipt_json=? WHERE execution_id=?",
                (response.status, now_utc(), canonical(result), response.execution_id),
            )
        return result

    def progress(self, execution_id, snapshot):
        with self.service.store.transaction():
            self.service.store.db.execute(
                "UPDATE app_agent_attempts SET receipt_json=? WHERE execution_id=? AND status='STARTED'",
                (
                    canonical({"diagnostic_only": True, "cli_diagnostic": snapshot}),
                    execution_id,
                ),
            )


def compute(database, job_id, lease, workspace):
    service = ApplicationService(database)
    directory = Path(workspace)
    failure_stage = "JOB_AUTHORIZATION_AND_SOURCE_VALIDATION"
    try:
        job = service.store.db.execute(
            "SELECT * FROM app_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if job is None or job["status"] != "RUNNING" or job["lease_token"] != lease:
            return 0
        principal = service.sessions.resolve_id(job["session_id"])
        role = (
            "CALIBRATION_ADMIN"
            if job["kind"] in ("review", "debate", "probe")
            else "CALIBRATION_REVIEWER"
        )
        service.authorize_case(job["case_id"], principal, role)
        request = Request.model_validate_json(job["request_json"])
        intake = service.store.db.execute(
            "SELECT * FROM app_cases WHERE case_id=?", (job["case_id"],)
        ).fetchone()
        if hashlib.sha256(intake["document_blob"]).hexdigest() != intake["source_hash"]:
            raise CalibrationError("CASE_SOURCE_INTEGRITY_FAILED")
        execution = None
        trace = None
        content = None
        result = {}
        if job["kind"] in ("review", "debate", "probe"):
            from .synthetic import analyze_source, review_state, mock_script
            from .providers import select_executor
            from ..agents import AgentRunner
            from ..agents.mat_advisor import MatAdvisor
            from ..agents.mat_profile import load_profile, synthetic_fixture_path
            from ..agents.orchestrator import ReviewOrchestrator
            from ..references.synthetic_index import synthetic_reference_index

            observations = analyze_source(job["case_id"], intake["document_blob"])
            existing = service.store.db.execute(
                "SELECT observations_json FROM cases WHERE case_id=?", (job["case_id"],)
            ).fetchone()
            from ..calibration.store import normalize_evidence

            if existing and json.loads(existing[0]) != normalize_evidence(observations):
                raise CalibrationError("OBSERVATION_VERSION_MISMATCH")
            state = review_state(job["case_id"], observations)
            source = directory / "SYNTHETIC-cooperation.docx"
            source.write_bytes(intake["document_blob"])
            failure_stage = "EXECUTOR_SELECTION"
            provider = select_executor(
                request.executor,
                timeout=max(
                    1, min(request.timeout, 120, int(job["deadline"] - time.time()) - 5)
                ),
            )
            trace = JobTrace(service, job_id)
            runner = (
                AgentRunner(
                    provider, trace, max_attempts=1, invocation_observer=trace.started
                )
                if provider
                else None
            )
            profile = load_profile(synthetic_fixture_path())
            from ..institutional.providers import PublicSyntheticProvider

            catalog = PublicSyntheticProvider().catalog()

            def enrich(review_state, registry):
                for observation in observations:
                    for aid in observation["authority_reference_ids"]:
                        item = next(a for a in catalog["authorities"] if a["id"] == aid)
                        text = (
                            item["title"]
                            + "; "
                            + "; ".join(
                                body + ": " + role
                                for body, role in item["roles"].items()
                            )
                        )
                        evidence = registry.add_policy(
                            "SYNTHETIC " + aid,
                            text,
                            approval_status="UNVERIFIED",
                            applicability="NOT_ESTABLISHED",
                            file="SYNTHETIC_REFERENCE_FIXTURE",
                            sha256=hashlib.sha256(canonical(item).encode()).hexdigest(),
                            location="page " + str(item["page"]),
                            version="SYN-v1",
                        )
                        registry.attach_basis(
                            observation["observation_id"], evidence.id
                        )
                    for uid in observation["department_reference_ids"]:
                        unit = next(u for u in catalog["units"] if u["id"] == uid)
                        evidence = registry.add_policy(
                            "SYNTHETIC " + uid,
                            unit["name"] + ": " + "; ".join(unit["tasks"]),
                            approval_status="UNVERIFIED",
                            applicability="NOT_ESTABLISHED",
                            file="SYNTHETIC_REFERENCE_FIXTURE",
                            sha256=hashlib.sha256(canonical(unit).encode()).hexdigest(),
                            location="page " + str(unit["page"]),
                            version="SYN-v1",
                        )
                        registry.attach_basis(
                            observation["observation_id"], evidence.id
                        )

            engine = ReviewOrchestrator(
                synthetic_reference_index(),
                runner=runner,
                gate_dir=directory / "gate",
                mat_profile=profile,
                reference_enricher=enrich,
            )
            if request.executor == "mock":
                engine.mat = MatAdvisor(
                    profile, None
                )  # explicitly recorded deterministic MAT, never a live downgrade
            if job["kind"] == "probe":
                if runner is None:
                    raise CalibrationError("INFERENCE_PROBE_REQUIRES_EXPLICIT_EXECUTOR")
                from ..agents import contracts as C

                failure_stage = "DRAFTING"
                response = runner.run(
                    C.ROLE_DRAFTING,
                    "Review only this fictional clause. Return structured advisory findings; never authorize issuance.",
                    {
                        "label": "SYNTHETIC",
                        "case_id": job["case_id"],
                        "clause": observations[0]["quote"],
                        "evidence": [],
                    },
                    max_tokens=1024,
                )
                result = {
                    "case_id": job["case_id"],
                    "probe": response.to_record(),
                    "output": response.output,
                    "actual_provider_api_inference": response.is_live,
                }
                if not response.ok:
                    raise CalibrationError("INFERENCE_PROBE_FAILED")
            else:
                failure_stage = "ORCHESTRATION"
                execution = engine.execute(state, source, draft=True)
                result = {
                    "case_id": job["case_id"],
                    "run_id": execution.run_id,
                    "trace_count": len(trace.records),
                    "executor": request.executor,
                    "execution_sources": execution.trace_summary.get("by_source", {}),
                    "actual_live_inference_count": execution.trace_summary.get(
                        "actual_live_inference_count", 0
                    ),
                }
        else:
            from ..intelligence.exports import export_dashboard

            data = service.intelligence.dashboard(job["case_id"], principal.reviewer)
            state_hash = service.state_hash(job["case_id"], principal)
            failure_stage = "DRAFT_EXPORT"
            content = export_dashboard(data, job["kind"])
            result = {
                "case_id": job["case_id"],
                "kind": job["kind"],
                "state_hash": state_hash,
            }
        failure_stage = "ATOMIC_PUBLICATION"
        with service.store.transaction():
            # Writer lock + lease/session/scope check before any state/artifact becomes visible.
            changed = service.store.db.execute(
                "UPDATE app_jobs SET lease_until=lease_until WHERE job_id=? AND status='RUNNING' AND lease_token=? AND deadline>? AND lease_until>?",
                (job_id, lease, time.time(), time.time()),
            ).rowcount
            if changed != 1:
                raise CalibrationError("JOB_LEASE_OR_DEADLINE_LOST")
            principal = service.sessions.resolve_id(job["session_id"])
            service.authorize_case(job["case_id"], principal, role)
            status = "COMPLETED"
            error = None
            stage = None
            if execution is not None:
                if not existing:
                    service.calibration.import_case(
                        job["case_id"],
                        intake["source_hash"],
                        observations,
                        principal.reviewer,
                    )
                service.intelligence.capture(
                    job["case_id"],
                    execution,
                    trace.records,
                    principal.reviewer,
                    gate_dir=directory / "gate",
                )
                failed = next(
                    (
                        o
                        for o in execution.role_outcomes
                        if o["status"] not in ("OK", "NOT_RUN")
                    ),
                    None,
                )
                status = "FAILED" if failed else "WAITING_FOR_HUMAN"
                error = "AGENT_STAGE_FAILED" if failed else None
                stage = failed.get("stage", failed["role"]) if failed else None
            if content is not None:
                if service.state_hash(job["case_id"], principal) != state_hash:
                    raise CalibrationError("CASE_CHANGED_DURING_EXPORT")
                artifact_id = "ART-" + uuid.uuid4().hex
                service.store.db.execute(
                    "INSERT INTO app_artifacts VALUES (?,?,?,?,?,?,?,?)",
                    (
                        artifact_id,
                        job["case_id"],
                        job_id,
                        job["kind"],
                        hashlib.sha256(content).hexdigest(),
                        content,
                        now_utc(),
                        state_hash,
                    ),
                )
                result["artifact_id"] = artifact_id
            if execution is not None:
                service.store._append(
                    job["case_id"],
                    None,
                    "UNIFIED_JOB_PUBLISHED",
                    {"job_id": job_id, "run_id": execution.run_id, "status": status},
                    principal.reviewer.reviewer_id,
                )
            service._audit("JOB_PUBLICATION", request, principal, "WORKER", result)
            service.store.db.execute(
                "UPDATE app_jobs SET status=?,finished_at=?,run_id=?,result_json=?,error_code=?,error_stage=? WHERE job_id=? AND lease_token=?",
                (
                    status,
                    now_utc(),
                    execution.run_id if execution else None,
                    canonical(result),
                    error,
                    stage,
                    job_id,
                    lease,
                ),
            )
    except AccessDenied:
        fail(
            service,
            job_id,
            lease,
            "AUTHORIZATION_REJECTED",
            status="BLOCKED_AUTHORIZATION",
            stage=failure_stage,
        )
    except Exception as exc:
        from ..agents.providers.base import ProviderFailure

        code = (
            exc.kind
            if isinstance(exc, ProviderFailure)
            else str(exc) if isinstance(exc, CalibrationError) else type(exc).__name__
        )
        fail(service, job_id, lease, code, stage=failure_stage)
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["supervise", "compute"])
    parser.add_argument("--db", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--lease")
    parser.add_argument("--workspace")
    args = parser.parse_args()
    raise SystemExit(
        supervise(args.db, args.job)
        if args.command == "supervise"
        else compute(args.db, args.job, args.lease, args.workspace)
    )
