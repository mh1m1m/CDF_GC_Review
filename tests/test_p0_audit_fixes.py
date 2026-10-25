"""Negative regressions for the 2026-10-25 P0 audit findings (D1 is covered in test_institutional_modes).

Each test reproduces the reported bypass and asserts it now fails closed.
"""
import secrets

import pytest

from cdf_gco_crms.agents import provenance as PV
from cdf_gco_crms.agents.providers.anthropic_adapter import AnthropicAdapter
from cdf_gco_crms.agents.providers.openai_adapter import OpenAIAdapter
from cdf_gco_crms.assurance import safe_xml
from cdf_gco_crms.calibration.store import (
    AccessDenied, CalibrationError, CalibrationStore, ReviewerContext,
)
from cdf_gco_crms.release import attestation as ATT

SHA = "b" * 64


# ---------------------------------------------------------------- D2 / D3 provider endpoint and provider list
def test_sdk_base_url_override_never_reaches_trusted_adapter(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-synthetic-not-a-credential")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-credential")
    import openai

    built = {}
    real = openai.OpenAI

    def capture(**kwargs):
        built.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(openai, "OpenAI", capture)
    adapter = OpenAIAdapter()
    with pytest.raises(Exception):
        adapter.complete(type("R", (), {"model": None, "system": "", "user_text": "", "max_tokens": 1,
                                        "role": "X", "schema": {}})())
    assert built["base_url"] == "https://api.openai.com/v1"
    assert str(adapter._client.base_url).rstrip("/") == "https://api.openai.com/v1"
    anthropic_adapter = AnthropicAdapter()
    assert str(anthropic_adapter._get_client().base_url).rstrip("/") == "https://api.anthropic.com"


def test_adapter_with_unofficial_endpoint_is_not_provider_api():
    adapter = OpenAIAdapter()
    assert PV.classify_adapter(adapter) == PV.SOURCE_PROVIDER_API
    adapter.endpoint = "http://127.0.0.1:9/v1"
    assert PV.classify_adapter(adapter) == PV.SOURCE_PROVIDER_API_UNTRUSTED


def test_provenance_and_attestation_share_one_provider_list():
    trusted_names = {cls.name for cls in PV.trusted_live_adapter_types()}
    assert trusted_names == set(PV.LIVE_PROVIDERS) == set(ATT.KNOWN_LIVE_PROVIDERS)
    for cls in PV.trusted_live_adapter_types():
        assert cls.endpoint == PV.official_endpoint(cls.name)


def _receipt(**overrides):
    record = {"Agent_Role": "DRAFTER", "Mode": "LIVE", "Execution_Source": "PROVIDER_API",
              "Provider_Request_ID": "req_1", "Execution_Status": "OK", "Provider": "openai",
              "Invocation_ID": "resp_1", "Response_Hash": "c" * 64, "Provider_Endpoint": "https://api.openai.com/v1"}
    record.update(overrides)
    return ATT.receipt_problems(record, role="DRAFTER")


def test_attestation_binds_invocation_prefix_and_endpoint_to_the_provider():
    assert _receipt() == []
    assert ATT.R_RECEIPT_INVOCATION in _receipt(Invocation_ID="msg_1")      # Anthropic id on an OpenAI receipt
    assert ATT.R_RECEIPT_ENDPOINT in _receipt(Provider_Endpoint="http://127.0.0.1:9/v1")
    assert ATT.R_RECEIPT_PROVIDER in _receipt(Provider="local-stub")


# ---------------------------------------------------------------- D5 / D6 / D8 calibration gate
@pytest.fixture()
def store(tmp_path):
    st = CalibrationStore(tmp_path / "private" / "mat.db")
    admin = ReviewerContext("test-admin", frozenset({"CALIBRATION_ADMIN", "CALIBRATION_REVIEWER"}), True)
    yield st, admin
    st.close()


def test_import_recomputes_materiality_server_side(store):
    st, admin = store
    st.import_case("CASE-D5", SHA, [{"observation_id": "OBS-1", "observed_change": "REMOVED_FROM_VERSION",
                                     "material_categories": [],
                                     "original_text": "نوصي باستثناء متطلبات مكافحة غسل الأموال"}], admin)
    assert "AML" in st.observations("CASE-D5", admin)[0]["material_categories"]


def test_import_rejects_unknown_category_and_premarked_withdrawal(store):
    st, admin = store
    with pytest.raises(CalibrationError, match="INVALID_MATERIAL_CATEGORY"):
        st.import_case("CASE-D5B", SHA, [{"observation_id": "OBS-1", "material_categories": ["NOT_A_CATEGORY"]}], admin)
    with pytest.raises(CalibrationError, match="DOCUMENTED_WITHDRAWAL_CANNOT_BE_IMPORTED"):
        st.import_case("CASE-D8", SHA, [{"observation_id": "OBS-1", "observed_change": "REMOVED_FROM_VERSION",
                                         "documented_withdrawal": True}], admin)


@pytest.fixture()
def material_case(store):
    st, admin = store
    digest = st.import_case("CASE-D6", SHA, [{"observation_id": "OBS-1", "observed_change": "REMOVED_FROM_VERSION",
                                              "original_text": "حق الاطلاع للمراجعين"}], admin)
    return st, admin, digest


GOOD_RATIONALE = "The counterparty confirmed audit access in the signed side letter."


@pytest.mark.parametrize("rationale,reasons,refs,code", [
    (".", ["W03"], ["DOC-17"], "SUBSTANTIVE_RATIONALE"),
    (GOOD_RATIONALE, ["W15"], ["DOC-17"], "SPECIFIC_REASON"),
    (GOOD_RATIONALE, ["W03"], [""], "EVIDENCE_OR_GAP"),
    (GOOD_RATIONALE, ["W03"], ["GAP:"], "EVIDENCE_OR_GAP"),
    (GOOD_RATIONALE, ["W03"], [], "EVIDENCE_OR_GAP"),
])
def test_material_withdrawal_needs_structured_reason_and_evidence(material_case, rationale, reasons, refs, code):
    st, admin, digest = material_case
    with pytest.raises(CalibrationError, match=code):
        st.save_decision("CASE-D6", "OBS-1", "WITHDRAW", rationale, digest, admin,
                         reasons=reasons, evidence_refs=refs, status="SUBMITTED")


def test_material_withdrawal_with_declared_gap_is_recorded(material_case):
    st, admin, digest = material_case
    st.save_decision("CASE-D6", "OBS-1", "WITHDRAW", GOOD_RATIONALE, digest, admin, reasons=["W03"],
                     evidence_refs=["GAP: signed side letter requested from the business owner"], status="SUBMITTED")
    assert st.case_statistics("CASE-D6", admin)["heightened_review"] == 1


# ---------------------------------------------------------------- D7 no defaulted decision over CLI/MCP
def test_operation_contract_never_defaults_a_submitted_decision():
    from cdf_gco_crms.execution.contracts import Request

    r = Request(case_id="SYN-D7", rationale="only a rationale")
    assert r.decision is None and r.status == "DRAFT"


def test_calibrate_without_explicit_decision_is_refused(tmp_path, monkeypatch):
    from cdf_gco_crms.execution.contracts import Request
    from cdf_gco_crms.execution.jobs import supervise
    from cdf_gco_crms.execution.service import ApplicationService

    token = secrets.token_urlsafe(36)
    monkeypatch.setenv("CDF_CALIBRATION_DEV_TOKEN", token)
    app = ApplicationService(tmp_path / "synthetic.sqlite", token=token)
    try:
        p = app.authenticate(token)
        app.invoke("cdf_create_case", Request(case_id="SYN-D7", idempotency_key="create-d7-001"), p)
        job = app.invoke("cdf_review_document", Request(case_id="SYN-D7", idempotency_key="review-d7-001"), p)["data"]
        supervise(app.store.path, job["job_id"])
        view = app.view("SYN-D7", p)
        with pytest.raises(CalibrationError, match="EXPLICIT_CALIBRATION_DECISION_REQUIRED"):
            app.invoke("cdf_calibrate_observation", Request(
                case_id="SYN-D7", observation_id=view["observation_ids"][0],
                expected_evidence_hash=view["evidence_hash"], rationale="only a rationale",
                idempotency_key="calibrate-d7-001"), p)
    finally:
        app.close()


# ---------------------------------------------------------------- D4 copilot human checkpoint
@pytest.fixture()
def waiting(tmp_path, monkeypatch):
    from cdf_gco_crms.copilot.service import CopilotService
    from cdf_gco_crms.execution.contracts import Request
    from cdf_gco_crms.execution.jobs import supervise
    from cdf_gco_crms.execution.service import ApplicationService

    token = secrets.token_urlsafe(36)
    monkeypatch.setenv("CDF_CALIBRATION_DEV_TOKEN", token)
    monkeypatch.setattr("cdf_gco_crms.execution.jobs.launch", lambda *args: None)
    app = ApplicationService(tmp_path / "synthetic.sqlite", token=token)
    p = app.authenticate(token)
    app.invoke("cdf_create_case", Request(case_id="SYN-D4", idempotency_key="create-d4-001"), p)
    cp = CopilotService(app)

    def call(op, transport="CLI_COPILOT", **body):
        return cp.execute(op, {"case_id": "SYN-D4", **body}, p, transport=transport)["data"]

    state = call("start", text="review agreement", executor="mock", idempotency_key="d4-start-001")
    for index in range(4):
        if state["status"] == "WAITING_FOR_HUMAN":
            break
        step = next(s for s in state["steps"] if s["status"] == "RUNNING")
        supervise(app.store.path, step["job_id"])
        state = call("resume", workflow_id=state["workflow_id"], expected_version=str(state["version"]),
                     idempotency_key=f"d4-resume-{index}")
    assert state["status"] == "WAITING_FOR_HUMAN"
    yield call, state
    app.close()


def _decide(call, record, evidence_hash, key):
    return call("decision", observation_id=record["observation"]["observation_id"], action="ACCEPT",
                expected_version=record["version"], expected_evidence_hash=evidence_hash,
                rationale="Synthetic reviewer retained the observation.", idempotency_key=key)


def _close(call, state, key, transport="CLI_COPILOT"):
    return call("resume", transport=transport, workflow_id=state["workflow_id"],
                expected_version=str(state["version"]), confirm_human=True,
                rationale="Proceed to internal drafts.", idempotency_key=key)


def test_checkpoint_cannot_be_closed_over_mcp(waiting):
    call, state = waiting
    decisions = call("decisions")
    for i, record in enumerate(decisions["records"]):
        _decide(call, record, decisions["evidence_hash"], f"d4-decide-{i:03d}")
    with pytest.raises(AccessDenied, match="DIRECT_HUMAN_INTERFACE"):
        _close(call, state, "d4-close-mcp-001", transport="MCP_COPILOT_STREAMABLE-HTTP")


def test_checkpoint_needs_fresh_decision_on_every_material_observation(waiting):
    call, state = waiting
    decisions = call("decisions")
    assert len(decisions["records"]) > 1
    _decide(call, decisions["records"][0], decisions["evidence_hash"], "d4-decide-first")
    with pytest.raises(CalibrationError, match="EVERY_MATERIAL_OBSERVATION"):
        _close(call, state, "d4-close-partial-001")
    decisions = call("decisions")
    for i, record in enumerate(decisions["records"][1:]):
        _decide(call, record, decisions["evidence_hash"], f"d4-decide-rest-{i:03d}")
    closed = _close(call, state, "d4-close-full-001")
    assert closed["pending_human"] is False


# ---------------------------------------------------------------- D15 wide-encoding DTD
@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32"])
def test_wide_encoded_dtd_is_rejected(encoding):
    payload = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><r>&b;</r>'
    with pytest.raises(safe_xml.ParseError):
        safe_xml.fromstring(payload.encode(encoding))
    if not encoding.startswith("utf-32"):          # expat itself does not read UTF-32
        assert safe_xml.fromstring('<?xml version="1.0"?><r>ok</r>'.encode(encoding)).text == "ok"


def test_model_cannot_record_a_human_decision_over_mcp(waiting):
    """A model client may read decisions, but never author the "human" record a checkpoint relies on."""
    call, state = waiting
    decisions = call("decisions", transport="MCP_COPILOT_STREAMABLE-HTTP")        # reading is allowed
    record = decisions["records"][0]
    with pytest.raises(AccessDenied, match="HUMAN_DECISION_REQUIRES_DIRECT_HUMAN_INTERFACE"):
        call("decision", transport="MCP_COPILOT_STREAMABLE-HTTP", observation_id=record["observation"]["observation_id"],
             action="ACCEPT", expected_version=record["version"], expected_evidence_hash=decisions["evidence_hash"],
             rationale="Model-authored acceptance.", idempotency_key="d4-mcp-decide-001")

