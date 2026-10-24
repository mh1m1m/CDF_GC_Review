"""Real persistence/authorization/idempotency boundaries; no paid inference required."""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
import pytest

from cdf_gco_crms.execution.service import ApplicationService, Conflict
from cdf_gco_crms.execution.contracts import Request
from cdf_gco_crms.execution import jobs
from cdf_gco_crms.calibration.store import AccessDenied, CalibrationError


@pytest.fixture
def application(tmp_path, monkeypatch):
    token = secrets.token_urlsafe(36)
    monkeypatch.setenv("CDF_CALIBRATION_DEV_TOKEN", token)
    service = ApplicationService(tmp_path / "public-demo.sqlite", token=token)
    yield service, service.authenticate(token), token
    service.close()


def call(service, p, tool, **kwargs):
    return service.invoke(tool, Request(**kwargs), p)["data"]


def create(service, p, case="SYN-UNIFIED-001"):
    return call(
        service,
        p,
        "cdf_create_case",
        case_id=case,
        idempotency_key="create-key-" + case,
    )


def queue(
    service,
    p,
    case="SYN-UNIFIED-001",
    key="review-key-001",
    executor="mock",
    timeout=60,
):
    return call(
        service,
        p,
        "cdf_review_document",
        case_id=case,
        idempotency_key=key,
        executor=executor,
        timeout=timeout,
    )


def finish(service, p, job):
    jobs.supervise(service.store.path, job["job_id"])
    return call(service, p, "cdf_get_job_result", job_id=job["job_id"])


def test_cli_runs_real_persisted_source_review_and_replays_same_job(application):
    service, p, token = application
    env = {
        **os.environ,
        "CDF_CALIBRATION_DB": str(service.store.path),
        "CDF_CALIBRATION_DEV_TOKEN": token,
    }

    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "cdf_gco_crms.cli", *args, "--json"],
            env=env,
            capture_output=True,
            text=True,
            timeout=70,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    created = cli(
        "case",
        "create",
        "--case",
        "SYN-CLI-COOP",
        "--source",
        "synthetic",
        "--idempotency-key",
        "cli-create-key-001",
    )["data"]
    reviewed = cli(
        "review",
        "run",
        "--case",
        "SYN-CLI-COOP",
        "--executor",
        "mock",
        "--timeout",
        "60",
        "--idempotency-key",
        "cli-review-key-001",
        "--wait",
    )["data"]
    assert (
        reviewed["job"]["status"] == "WAITING_FOR_HUMAN"
        and reviewed["job"]["attempts"] == 1
    )
    replay = cli(
        "review",
        "run",
        "--case",
        "SYN-CLI-COOP",
        "--executor",
        "mock",
        "--timeout",
        "60",
        "--idempotency-key",
        "cli-review-key-001",
    )["data"]
    assert replay["job_id"] == reviewed["job"]["job_id"] and replay["replayed"]
    view = cli("case", "status", "--case", "SYN-CLI-COOP")["data"]
    assert (
        view["source_hash"] == created["source_hash"]
        and len(view["observation_ids"]) == 8
    )
    assert view["run_id"] == reviewed["result"]["run_id"]
    assert {i["stage"] for i in view["agent_status"]} >= {
        "DRAFTING",
        "MAT-01",
        "BLACK_TEAM",
        "MAT-02",
        "RED_ADVOCATE",
        "MAT-03",
        "ADJUDICATOR",
        "FINAL_REVIEWER",
    }
    assert (
        view["actual_live_inference_count"] == 0
        and not view["release_gate"]["authorized"]
    )
    assert len(service.store.db.execute("SELECT * FROM app_jobs").fetchall()) == 1


def test_idempotency_rejects_changed_request_and_active_duplicate(application):
    service, p, _ = application
    create(service, p)
    job = queue(service, p)
    assert queue(service, p)["job_id"] == job["job_id"]
    with pytest.raises(Conflict, match="DIFFERENT_REQUEST"):
        queue(service, p, executor="deterministic")
    with pytest.raises(Conflict, match="ACTIVE_REVIEW"):
        queue(service, p, key="another-review-key")
    assert service.store.db.execute("SELECT COUNT(*) FROM app_jobs").fetchone()[0] == 1


def test_sessions_expiry_roles_scope_and_forged_identity_never_mutate(application):
    service, p, _ = application
    create(service, p)
    other = secrets.token_urlsafe(36)
    service.sessions.register(
        other, principal_id="SYN-OTHER", roles=["CALIBRATION_REVIEWER"]
    )
    outsider = service.authenticate(other)
    with pytest.raises(AccessDenied):
        call(service, outsider, "cdf_get_case_status", case_id="SYN-UNIFIED-001")
    with pytest.raises(AccessDenied):
        call(service, outsider, "cdf_review_document", case_id="SYN-UNIFIED-001")
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Request.model_validate(
            {"case_id": "SYN-UNIFIED-001", "reviewer_id": "SYNTHETIC_ADMIN"}
        )
    with service.store.transaction():
        service.store.db.execute(
            "UPDATE app_sessions SET expires_at=0 WHERE session_id=?",
            (outsider.session_id,),
        )
    with pytest.raises(AccessDenied, match="EXPIRED"):
        service.authenticate(other)
    with pytest.raises(AccessDenied):
        service.authenticate("invalid synthetic credential")


def test_atomic_publication_rollback_preserves_no_observation_or_grant(
    application, monkeypatch
):
    service, p, _ = application
    create(service, p)
    job = queue(service, p)
    with service.store.transaction():
        service.store.db.execute(
            "UPDATE app_jobs SET status='RUNNING',lease_token='test-lease',lease_until=?,deadline=? WHERE job_id=?",
            (time.time() + 30, time.time() + 30, job["job_id"]),
        )
    from cdf_gco_crms.intelligence.service import IntelligenceService

    def reject(*args, **kwargs):
        raise CalibrationError("SYNTHETIC_FORCED_PUBLICATION_REJECTION")

    monkeypatch.setattr(IntelligenceService, "capture", reject)
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        jobs.compute(service.store.path, job["job_id"], "test-lease", directory)
    assert service.job(job["job_id"], p)["status"] == "FAILED"
    assert not service.store.db.execute("SELECT 1 FROM cases").fetchone()
    assert not service.store.db.execute("SELECT 1 FROM case_grants").fetchone()
    assert not service.store.db.execute("SELECT 1 FROM executive_runs").fetchone()
    assert (
        service.store.db.execute("SELECT COUNT(*) FROM app_agent_attempts").fetchone()[
            0
        ]
        > 0
    )


def test_material_calibration_and_issue_guard_are_shared(application):
    service, p, _ = application
    create(service, p)
    finish(service, p, queue(service, p))
    view = service.view("SYN-UNIFIED-001", p)
    request = {
        "case_id": view["case_id"],
        "observation_id": view["observation_ids"][-1],
        "expected_evidence_hash": view["evidence_hash"],
        "decision": "WITHDRAW",
        "rationale": "Synthetic unsupported withdrawal",
        "reasons": ["W12"],
        "idempotency_key": "withdraw-key-001",
    }
    with pytest.raises(CalibrationError, match="MATERIAL"):
        call(service, p, "cdf_calibrate_observation", **request)
    with pytest.raises(AccessDenied, match="CENTRAL_RELEASE"):
        call(
            service, p, "cdf_generate_word_report", case_id=view["case_id"], issue=True
        )
    assert (
        call(service, p, "cdf_get_release_gate_status", case_id=view["case_id"])[
            "official_issue_authorized"
        ]
        is False
    )
    assert not any(
        e["event_type"] == "OBSERVATION_CALIBRATION"
        for e in service.calibration.events(view["case_id"], p.reviewer)
    )


def test_cancel_before_start_and_stale_recovery_never_replays_provider(application):
    service, p, _ = application
    create(service, p)
    job = queue(service, p)
    cancelled = call(
        service,
        p,
        "cdf_cancel_job",
        job_id=job["job_id"],
        idempotency_key="cancel-key-001",
    )
    assert cancelled["status"] == "CANCELLED"
    jobs.supervise(service.store.path, job["job_id"])
    assert service.job(job["job_id"], p)["attempts"] == 0
    second = queue(service, p, key="review-key-002")
    with service.store.transaction():
        service.store.db.execute(
            "UPDATE app_jobs SET status='RUNNING',lease_until=0 WHERE job_id=?",
            (second["job_id"],),
        )
    recovered = call(
        service,
        p,
        "cdf_recover_case_jobs",
        case_id=second["case_id"],
        idempotency_key="recover-key-001",
    )
    assert (
        recovered["stale_failed_without_replay"] == 1
        and service.job(second["job_id"], p)["status"] == "FAILED"
    )
    assert not service.store.db.execute("SELECT 1 FROM executive_runs").fetchone()
    assert not service.store.db.execute("SELECT 1 FROM app_agent_attempts").fetchone()


def test_requested_live_executor_never_downgrades_to_mock(application, monkeypatch):
    service, p, _ = application
    create(service, p)
    monkeypatch.delenv("CDF_ENABLE_PROVIDER_API", raising=False)
    result = finish(service, p, queue(service, p, executor="openai"))
    assert (
        result["job"]["status"] == "FAILED"
        and result["job"]["error_code"] == "EXECUTION_POLICY_BLOCKED"
    )
    assert result["job"]["error_stage"] == "EXECUTOR_SELECTION"
    assert result["agent_attempts"] == []
    assert not service.store.db.execute("SELECT 1 FROM executive_runs").fetchone()


def test_artifact_hash_chunks_and_case_scope(application):
    service, p, _ = application
    create(service, p)
    finish(service, p, queue(service, p))
    exported = call(
        service,
        p,
        "cdf_generate_excel_dashboard",
        case_id="SYN-UNIFIED-001",
        idempotency_key="excel-key-001",
    )
    result = finish(service, p, exported)
    aid = result["result"]["artifact_id"]
    import base64

    contents = bytearray()
    offset = 0
    while True:
        chunk = call(service, p, "cdf_get_artifact", artifact_id=aid, cursor=offset)
        contents.extend(base64.b64decode(chunk["content_base64"]))
        if chunk["next_offset"] is None:
            break
        offset = chunk["next_offset"]
    assert (
        hashlib.sha256(contents).hexdigest() == chunk["sha256"]
        and contents[:2] == b"PK"
    )
    create(service, p, "SYN-ANOTHER-CASE")
    with pytest.raises(AccessDenied, match="CROSS_CASE_ARTIFACT"):
        call(
            service, p, "cdf_get_artifact", artifact_id=aid, case_id="SYN-ANOTHER-CASE"
        )
    with service.store.transaction():
        service.store.db.execute(
            "UPDATE app_artifacts SET content=? WHERE artifact_id=?",
            (b"SYNTHETIC CORRUPTION", aid),
        )
    with pytest.raises(CalibrationError, match="INTEGRITY"):
        call(service, p, "cdf_get_artifact", artifact_id=aid)


@pytest.mark.parametrize("interruption", ["timeout", "cancel", "expire"])
def test_running_supervisor_kills_real_descendants_without_publication(
    application, monkeypatch, tmp_path, interruption
):
    import threading
    import psutil

    service, p, _ = application
    create(service, p)
    job = queue(
        service,
        p,
        executor="deterministic",
        timeout=1 if interruption == "timeout" else 30,
    )
    pid_file = tmp_path / "controlled-child.pid"
    real_popen = subprocess.Popen
    script = "import subprocess,sys,time; from pathlib import Path; child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
    parents = []

    def controlled_child(*args, **kwargs):
        process = real_popen(
            [sys.executable, "-c", script, str(pid_file)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        parents.append(process)
        return process

    monkeypatch.setattr(jobs.subprocess, "Popen", controlled_child)
    thread = threading.Thread(
        target=jobs.supervise, args=(service.store.path, job["job_id"])
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists()
    descendant = int(pid_file.read_text())
    if interruption == "cancel":
        call(
            service,
            p,
            "cdf_cancel_job",
            job_id=job["job_id"],
            idempotency_key="running-cancel-001",
        )
    elif interruption == "expire":
        with service.store.transaction():
            service.store.db.execute(
                "UPDATE app_sessions SET expires_at=0 WHERE session_id=?",
                (p.session_id,),
            )
    thread.join(timeout=8)
    assert not thread.is_alive()
    row = service.store.db.execute(
        "SELECT status,error_code,attempts FROM app_jobs WHERE job_id=?",
        (job["job_id"],),
    ).fetchone()
    assert (
        row["status"]
        == {
            "timeout": "FAILED",
            "cancel": "CANCELLED",
            "expire": "BLOCKED_AUTHORIZATION",
        }[interruption]
    )
    assert row["attempts"] == 1 and parents[0].poll() is not None
    try:
        assert psutil.Process(descendant).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        pass  # A fully reaped descendant is the expected successful outcome.
    assert not service.store.db.execute("SELECT 1 FROM executive_runs").fetchone()


def test_wrong_role_calibration_is_denied_even_with_case_grant(application):
    service, p, _ = application
    create(service, p)
    finish(service, p, queue(service, p))
    token = secrets.token_urlsafe(36)
    service.sessions.register(token, principal_id="SYN-OBSERVER", roles=[])
    observer = service.authenticate(token)
    with service.store.transaction():
        service.store.db.execute(
            "INSERT INTO case_grants VALUES (?,?)", ("SYN-UNIFIED-001", "SYN-OBSERVER")
        )
    view = service.view("SYN-UNIFIED-001", p)
    with pytest.raises(AccessDenied):
        call(
            service,
            observer,
            "cdf_calibrate_observation",
            case_id=view["case_id"],
            observation_id=view["observation_ids"][0],
            expected_evidence_hash=view["evidence_hash"],
            rationale="Synthetic wrong role",
        )


def test_actual_independent_mcp_protocol_shared_cli_case(tmp_path):
    import asyncio
    from cdf_gco_crms.acceptance.unified import Acceptance, serving, free_port

    token = secrets.token_urlsafe(36)
    env = {
        **os.environ,
        "CDF_OPERATION_MODE": "PUBLIC_SYNTHETIC_DEMO",
        "CDF_CALIBRATION_DB": str(tmp_path / "protocol.sqlite"),
        "CDF_CALIBRATION_DEV_TOKEN": token,
    }
    output = tmp_path / "evidence"
    output.mkdir()
    acceptance = Acceptance(output, env)
    acceptance.phase_cli([])
    port = free_port()
    with serving(
        [
            sys.executable,
            "-m",
            "cdf_gco_crms.interfaces.mcp_server",
            "--port",
            str(port),
        ],
        env,
        f"http://127.0.0.1:{port}/health",
        tmp_path / "mcp.log",
    ):
        asyncio.run(acceptance.phase_mcp(f"http://127.0.0.1:{port}/mcp"))
    assert acceptance.mcp_fields == acceptance.canonical
    assert (
        len(json.loads((output / "mcp-tool-discovery.json").read_text())["tools"]) == 24
    )
