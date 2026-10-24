"""Typed, bounded public-synthetic tool contracts. Client identities are never inputs."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Executor = Literal[
    "deterministic", "mock", "codex-cli", "claude-cli", "openai", "anthropic"
]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str | None = Field(default=None, pattern=r"^SYN-[A-Za-z0-9_-]{1,100}$")
    source: Literal["synthetic-cooperation-v1"] = "synthetic-cooperation-v1"
    executor: Executor = "deterministic"
    timeout: int = Field(default=180, ge=1, le=600)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    job_id: str | None = Field(default=None, pattern=r"^JOB-[a-f0-9]{32}$")
    artifact_id: str | None = Field(default=None, pattern=r"^ART-[a-f0-9]{32}$")
    observation_id: str | None = Field(
        default=None, pattern=r"^SYN-[A-Za-z0-9_-]{1,120}$"
    )
    decision: Literal[
        "KEEP_UNCHANGED",
        "KEEP_WITH_REVISIONS",
        "STRENGTHEN",
        "SOFTEN",
        "SHORTEN",
        "EXPAND",
        "CONVERT_TO_QUESTION",
        "CONVERT_TO_RECOMMENDATION",
        "NARROW_SCOPE",
        "MERGE_WITH_ANOTHER",
        "WITHDRAW",
        "ESCALATE",
        "REQUEST_MORE_EVIDENCE",
    ] = "KEEP_UNCHANGED"
    rationale: str = Field(default="", max_length=4000)
    expected_evidence_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    status: Literal["DRAFT", "SUBMITTED"] = "SUBMITTED"
    reasons: list[str] = Field(default_factory=list, max_length=20)
    evidence_refs: list[str] = Field(default_factory=list, max_length=40)
    query: str = Field(default="", max_length=240)
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    issue: bool = False


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    operation: str
    data: dict = Field(default_factory=dict)
    error: dict | None = None


TOOLS = {
    "cdf_recover_case_jobs": ("recover", "CALIBRATION_ADMIN", True),
    "cdf_probe_executor": ("probe", "CALIBRATION_ADMIN", True),
    "cdf_create_case": ("create", "CALIBRATION_ADMIN", True),
    "cdf_review_document": ("review", "CALIBRATION_ADMIN", True),
    "cdf_get_case_status": ("case", "CALIBRATION_REVIEWER", False),
    "cdf_get_observations": ("observations", "CALIBRATION_REVIEWER", False),
    "cdf_run_multi_agent_debate": ("debate", "CALIBRATION_ADMIN", True),
    "cdf_get_debate_trace": ("trace", "CALIBRATION_REVIEWER", False),
    "cdf_get_job_status": ("job", "CALIBRATION_REVIEWER", False),
    "cdf_get_job_result": ("job_result", "CALIBRATION_REVIEWER", False),
    "cdf_cancel_job": ("cancel", "CALIBRATION_ADMIN", True),
    "cdf_check_delegated_authority": ("authority", "CALIBRATION_REVIEWER", False),
    "cdf_get_department_responsibilities": (
        "organization",
        "CALIBRATION_REVIEWER",
        False,
    ),
    "cdf_get_reference_status": ("references", "CALIBRATION_REVIEWER", False),
    "cdf_get_calibration_history": ("history", "CALIBRATION_REVIEWER", False),
    "cdf_calibrate_observation": ("calibrate", "CALIBRATION_REVIEWER", True),
    "cdf_get_dashboard_metrics": ("metrics", "CALIBRATION_REVIEWER", False),
    "cdf_get_release_gate_status": ("gate", "CALIBRATION_REVIEWER", False),
    "cdf_generate_word_report": ("docx", "CALIBRATION_REVIEWER", True),
    "cdf_generate_excel_dashboard": ("xlsx", "CALIBRATION_REVIEWER", True),
    "cdf_generate_pdf_report": ("pdf", "CALIBRATION_REVIEWER", True),
    "cdf_get_artifact": ("artifact", "CALIBRATION_REVIEWER", False),
    "cdf_get_artifact_status": ("artifact_status", "CALIBRATION_REVIEWER", False),
}
