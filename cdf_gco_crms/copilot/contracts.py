from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ..execution.contracts import Executor

Operation = Literal[
    "catalog",
    "plan",
    "start",
    "status",
    "resume",
    "cancel",
    "ask",
    "knowledge",
    "quality",
    "decision",
    "decisions",
    "memory",
    "calibration",
    "ingest",
    "documents",
    "correct",
    "health",
    "executors",
    "backup",
    "restore_verify",
    "history",
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    case_id: str | None = Field(default=None, pattern=r"^(SYN|UPL)-[A-Za-z0-9_-]{1,100}$")
    text: str = Field(default="", max_length=4000)
    executor: Executor = "deterministic"
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    workflow_id: str | None = Field(default=None, pattern=r"^WF-[a-f0-9]{32}$")
    expected_version: str | None = Field(default=None, max_length=80)
    confirm_human: bool = False
    retry: bool = False
    rationale: str = Field(default="", max_length=4000)
    query: str = Field(default="", max_length=240)
    domain: Literal["all", "authority", "responsibility"] = "all"
    scenario_id: (
        Literal["DOA_CONFLICT", "DEPARTMENT_OVERLAP", "STALE_SOURCE"] | None
    ) = None
    observation_id: str | None = Field(
        default=None, pattern=r"^(SYN|GCO)-[A-Za-z0-9_-]{1,120}$"
    )
    action: Literal[
        "ACCEPT",
        "REVISE",
        "REJECT",
        "MORE_EVIDENCE",
        "MERGE",
        "RECLASSIFY",
        "ESCALATE",
        "DISSENT",
        "DEFER",
        "CLOSE",
    ] = "ACCEPT"
    expected_evidence_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    final_wording: str = Field(default="", max_length=8000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=40)
    reasons: list[str] = Field(default_factory=list, max_length=20)
    material_categories: list[str] = Field(default_factory=list, max_length=20)
    merge_target_id: str | None = Field(default=None, max_length=120)
    case_ids: list[str] = Field(default_factory=list, max_length=20)
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=100)
    format: Literal["text", "pdf", "docx", "xlsx", "image"] = "text"
    content_base64: str = Field(default="", max_length=80000)
    synthetic: bool = False
    document_id: str | None = Field(default=None, pattern=r"^DOC-[a-f0-9]{32}$")
    anchor_id: str | None = Field(default=None, max_length=100)
    corrected_text: str = Field(default="", max_length=8000)
    backup_id: str | None = Field(default=None, pattern=r"^BACKUP-[a-f0-9]{32}$")


ROLE_ADMIN = {
    "start",
    "resume",
    "cancel",
    "ingest",
    "correct",
    "health",
    "executors",
    "backup",
    "restore_verify",
}
MUTATIONS = {
    "start",
    "resume",
    "cancel",
    "decision",
    "ingest",
    "correct",
    "backup",
    "restore_verify",
}
