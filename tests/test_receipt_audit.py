"""A failed persisted execution can verify locally without becoming live evidence."""

import json
import secrets
import pytest
from cdf_gco_crms.execution.service import ApplicationService
from cdf_gco_crms.execution.contracts import Request
from cdf_gco_crms.execution.jobs import JobTrace
from cdf_gco_crms.execution.receipt_audit import evidence_labels, verify
from cdf_gco_crms.agents.runner import AgentRunner
from cdf_gco_crms.agents.contracts import ROLE_DRAFTING
from cdf_gco_crms.agents.providers.base import ProviderAdapter, ProviderFailure


def test_failed_receipt_binds_source_attempt_and_hash_chain_and_rejects_tamper(
    tmp_path,
):
    app = ApplicationService(
        tmp_path / "synthetic.sqlite", token=secrets.token_urlsafe(36)
    )
    row = app.store.db.execute("SELECT session_id FROM app_sessions").fetchone()
    p = app.sessions.resolve_id(row[0])
    case = "SYN-AUDIT-001"
    app.invoke(
        "cdf_create_case", Request(case_id=case, idempotency_key="receipt-case-001"), p
    )
    job = app.invoke(
        "cdf_probe_executor",
        Request(
            case_id=case, executor="codex-cli", idempotency_key="receipt-probe-001"
        ),
        p,
    )["data"]

    class Failed(ProviderAdapter):
        def complete(self, request):
            raise ProviderFailure("Synthetic local test failure", kind="LOCAL_TEST")

    trace = JobTrace(app, job["job_id"])
    runner = AgentRunner(
        Failed(), trace, max_attempts=1, invocation_observer=trace.started
    )
    runner.run(ROLE_DRAFTING, "Synthetic", {"label": "SYNTHETIC"})
    result = verify(app.store.path, case)
    assert result["attempts_checked"] == 1 and result["local_integrity"] == "PASS"
    assert (
        result["provider_api_completions"] == 0
        and result["native_cli_completions"] == 0
    )
    assert result["live_execution_evidence"] == "BLOCKED_EXTERNAL_NO_COMPLETION"
    with app.store.transaction():
        app.store.db.execute("UPDATE app_agent_attempts SET prompt_hash='tampered'")
    with pytest.raises(ValueError, match="ATTEMPT_BINDING_MISMATCH"):
        verify(app.store.path, case)
    app.close()


def test_cli_completions_never_carry_the_live_evidence_label():
    """D16: a supervised CLI completion is not provider-API inference evidence."""
    assert evidence_labels(0, 3) == {"live_execution_evidence": "BLOCKED_EXTERNAL_NO_COMPLETION",
                                     "supervised_cli_evidence": "CLI_COMPLETION_PRESENT_NOT_PROVIDER_API_EVIDENCE"}
    assert evidence_labels(1, 0)["live_execution_evidence"] == "PROVIDER_API_PRESENT_REQUIRES_EXTERNAL_RECONCILIATION"
    assert evidence_labels(0, 0) == {"live_execution_evidence": "BLOCKED_EXTERNAL_NO_COMPLETION", "supervised_cli_evidence": "NONE"}
