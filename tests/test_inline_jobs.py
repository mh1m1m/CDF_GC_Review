"""Serverless job runner: CDF_JOB_RUNNER=inline runs the job inside the request and publishes the same result."""
import secrets

from cdf_gco_crms.execution.contracts import Request
from cdf_gco_crms.execution.jobs import launch
from cdf_gco_crms.execution.service import ApplicationService


def test_inline_runner_completes_the_review_without_a_background_process(tmp_path, monkeypatch):
    token = secrets.token_urlsafe(36)
    monkeypatch.setenv("CDF_CALIBRATION_DEV_TOKEN", token)
    monkeypatch.setenv("CDF_JOB_RUNNER", "inline")
    app = ApplicationService(tmp_path / "synthetic.sqlite", token=token)
    try:
        p = app.authenticate(token)
        app.invoke("cdf_create_case", Request(case_id="SYN-INLINE-001", idempotency_key="inline-create-001"), p)
        job = app.invoke("cdf_review_document", Request(case_id="SYN-INLINE-001", idempotency_key="inline-review-001"), p)["data"]
        assert launch(app, job["job_id"], p) is None, "no process id: nothing runs after the response"
        assert app.job(job["job_id"], p)["status"] == "WAITING_FOR_HUMAN"
    finally:
        app.close()
