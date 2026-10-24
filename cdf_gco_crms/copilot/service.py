"""Bounded intent router and durable composition; never a second agent engine."""

import json, re, time, uuid
from pydantic import ValidationError
from ..calibration.store import (
    AccessDenied,
    CalibrationError,
    canonical,
    fingerprint,
    now_utc,
)
from ..execution.contracts import Request
from ..execution.service import Conflict, TERMINAL
from .contracts import Input, ROLE_ADMIN, MUTATIONS
from .human import HumanReviewService
from .intelligence import KnowledgeService
from .ingestion import IngestionService
from .operations import OperationsService

TEMPLATES = {
    "agreement_review": {
        "executable": True,
        "stages": [
            "GCO",
            "MAT-01",
            "BLACK_TEAM",
            "MAT-02",
            "RED_ADVOCATE",
            "MAT-03",
            "ADJUDICATOR",
            "FINAL_REVIEWER",
        ],
        "source": "FIXED_SYNTHETIC_COOPERATION_ONLY",
        "human_checkpoint": True,
    },
    "policy_review": {"executable": False},
    "governance_framework_review": {"executable": False},
    "committee_charter_review": {"executable": False},
    "delegated_authority_analysis": {"executable": True},
    "organizational_responsibility_review": {"executable": True},
    "internal_control_review": {"executable": True},
    "operational_risk_review": {"executable": True},
    "human_calibration_review": {"executable": True},
    "executive_reporting": {"executable": True},
    "case_summary": {"executable": True},
}


class CopilotService:
    def __init__(self, app):
        self.app = app
        self.human = HumanReviewService(app)
        self.knowledge = KnowledgeService(app)
        self.ingestion = IngestionService(app)
        self.operations = OperationsService(app)
        app.store.db.executescript(
            """CREATE TABLE IF NOT EXISTS cp_workflows(workflow_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,owner TEXT NOT NULL,state_json TEXT NOT NULL,version INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cp_keys(actor TEXT NOT NULL,operation TEXT NOT NULL,idem_key TEXT NOT NULL,request_hash TEXT NOT NULL,result_json TEXT NOT NULL,PRIMARY KEY(actor,operation,idem_key));"""
        )

    def execute(self, operation, body, principal, *, transport="CLI"):
        from typing import get_args
        from .contracts import Operation

        if operation not in get_args(Operation):
            raise CalibrationError("UNSUPPORTED_COPILOT_OPERATION")
        r = Input.model_validate(body)
        start = time.monotonic()
        p = (
            self.app.authenticate_from_principal(principal)
            if hasattr(self.app, "authenticate_from_principal")
            else self.app.sessions.resolve_id(principal.session_id)
        )
        self.operations.rate(p)
        try:
            with self.app.lock, self.app.store.transaction():
                p = self.app.sessions.resolve_id(p.session_id)
                p.reviewer.require(
                    "CALIBRATION_ADMIN"
                    if operation in ROLE_ADMIN
                    else "CALIBRATION_REVIEWER"
                )
                case = r.case_id
                if case is None:
                    matches = set(re.findall(r"SYN-[A-Za-z0-9_-]+", r.text))
                    if len(matches) == 1:
                        case = next(iter(matches))
                        r = r.model_copy(update={"case_id": case})
                if operation not in (
                    "catalog",
                    "health",
                    "executors",
                    "backup",
                    "restore_verify",
                    "memory",
                    "calibration",
                ):
                    if not case:
                        return {
                            "ok": True,
                            "operation": operation,
                            "data": {
                                "status": "NEEDS_PARAMETER",
                                "parameter": "case_id",
                                "message": "حدد معرف القضية المصرح بها.",
                            },
                        }
                    self.app.authorize_case(
                        case,
                        p,
                        (
                            "CALIBRATION_ADMIN"
                            if operation in ROLE_ADMIN
                            else "CALIBRATION_REVIEWER"
                        ),
                    )
                key = r.idempotency_key
                if operation in MUTATIONS and not key:
                    raise CalibrationError("IDEMPOTENCY_KEY_REQUIRED")
                digest = fingerprint(r.model_dump())
                old = (
                    self.app.store.db.execute(
                        "SELECT * FROM cp_keys WHERE actor=? AND operation=? AND idem_key=?",
                        (p.reviewer.reviewer_id, operation, key),
                    ).fetchone()
                    if operation in MUTATIONS
                    else None
                )
                if old:
                    if old["request_hash"] != digest:
                        raise Conflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST")
                    data = json.loads(old["result_json"])
                    if data.get("workflow_id"):
                        data = self._workflow(data["workflow_id"], r, p)
                    data["replayed"] = True
                else:
                    data = self._perform(operation, r, p)
                    self.app._audit(
                        "COPILOT_" + operation,
                        Request(case_id=case, rationale=digest, idempotency_key=key),
                        p,
                        transport,
                        data,
                    )
                    if operation in MUTATIONS:
                        self.app.store.db.execute(
                            "INSERT INTO cp_keys VALUES (?,?,?,?,?)",
                            (
                                p.reviewer.reviewer_id,
                                operation,
                                key,
                                digest,
                                canonical(
                                    {
                                        k: v
                                        for k, v in data.items()
                                        if k != "_launch_job_ids"
                                    }
                                ),
                            ),
                        )
            launch_ids = data.pop("_launch_job_ids", [])
            from ..execution.jobs import launch

            for job_id in launch_ids:
                launch(self.app, job_id, p)
            self.operations.metric(operation, "OK", (time.monotonic() - start) * 1000)
            return {"ok": True, "operation": operation, "data": data}
        except (CalibrationError, AccessDenied, ValidationError) as exc:
            self.operations.metric(
                operation,
                "DENIED" if isinstance(exc, AccessDenied) else "ERROR",
                (time.monotonic() - start) * 1000,
                type(exc).__name__,
            )
            raise

    def plan(self, r, p):
        text = r.text.casefold()
        if any(
            re.search(pattern, text)
            for pattern in [
                r"ignore.{0,30}instructions",
                r"bypass.{0,30}approval",
                r"override.{0,30}approval",
                r"تجاوز.{0,30}موافق",
                r"api[_ ]key",
                r"private reference",
                r"issue (official|final)",
                r"اعتمد نهائ",
                r"نفذ.*أمر",
            ]
        ):
            return {
                "status": "BLOCKED",
                "reason": "UNTRUSTED_INSTRUCTIONS_CANNOT_CREATE_AUTHORITY",
                "steps": [],
                "source": "DETERMINISTIC_INTENT_ROUTER",
            }
        if re.search(r"\b(accept|reject|revise|approve)\b|اقبل|ارفض|اعتمد", text):
            return {
                "status": "HUMAN_INPUT_REQUIRED",
                "reason": "USE_VERSIONED_HUMAN_DECISION_FORM",
                "steps": [],
                "source": "DETERMINISTIC_INTENT_ROUTER",
            }
        if re.search(r"policy review|review.*policy|مراجعة.*سياس", text):
            template = "policy_review"
        elif re.search(r"charter|ميثاق", text):
            template = "committee_charter_review"
        elif re.search(r"framework|إطار", text):
            template = "governance_framework_review"
        elif re.search(
            r"authority|delegat|تفويض|صلاحية|صلاحيات", text
        ) and not re.search(r"agreement|اتفاق", text):
            template = "delegated_authority_analysis"
        elif re.search(r"department|responsib|مسؤول|مهام", text) and not re.search(
            r"agreement|اتفاق", text
        ):
            template = "organizational_responsibility_review"
        elif re.search(r"calibrat|معاير", text):
            template = "human_calibration_review"
        elif re.search(r"risk|مخاطر", text) and not re.search(r"agreement|اتفاق", text):
            template = "operational_risk_review"
        elif re.search(r"quality|control|جودة|ضوابط", text) and not re.search(
            r"agreement|اتفاق", text
        ):
            template = "internal_control_review"
        elif re.search(
            r"unresolved|findings|observations|ملاحظات|مادية", text
        ) and not re.search(r"debate|نقاش", text):
            template = "case_summary"
        elif re.search(
            r"export|report|word|excel|تقرير|تقارير", text
        ) and not re.search(r"review|راجع|مراجعة", text):
            template = "executive_reporting"
        elif re.search(r"review|agreement|debate|راجع|مراجعة|اتفاق|نقاش", text):
            template = "agreement_review"
        else:
            return {
                "status": "UNSUPPORTED",
                "reason": "BOUNDED_INTENT_NOT_RECOGNIZED",
                "steps": [],
                "source": "DETERMINISTIC_INTENT_ROUTER",
            }
        if not TEMPLATES[template]["executable"]:
            return {
                "status": "BLOCKED",
                "template": template,
                "reason": "TEMPLATE_REQUIRES_INSTITUTIONAL_VALIDATION_AND_SUPPORTED_SOURCE",
                "steps": [],
            }
        if re.search(r"observations?\s+\d|الملاحظات?\s*\d", text):
            return {
                "status": "UNSUPPORTED",
                "reason": "TARGETED_SUBSET_DEBATE_NOT_IMPLEMENTED_FULL_CASE_REQUIRED",
                "steps": [],
            }
        if template == "agreement_review":
            steps = [
                "cdf_check_delegated_authority",
                "cdf_get_department_responsibilities",
                "cdf_review_document",
                "cdf_run_multi_agent_debate",
                "HUMAN_CHECKPOINT",
                "cdf_generate_word_report",
                "cdf_generate_excel_dashboard",
            ]
        elif template == "delegated_authority_analysis":
            steps = ["knowledge:authority"]
        elif template == "organizational_responsibility_review":
            steps = ["knowledge:responsibility"]
        elif template in (
            "internal_control_review",
            "operational_risk_review",
            "case_summary",
        ):
            steps = ["quality"]
        elif template == "human_calibration_review":
            steps = ["decisions", "calibration"]
        else:
            steps = ["cdf_generate_word_report", "cdf_generate_excel_dashboard"] + (
                ["cdf_generate_pdf_report"] if "pdf" in text else []
            )
        if template == "agreement_review" and "pdf" in text:
            steps.append("cdf_generate_pdf_report")
        return {
            "status": "READY",
            "template": template,
            "case_id": r.case_id,
            "executor": r.executor,
            "source": "DETERMINISTIC_INTENT_ROUTER",
            "steps": [{"tool": s, "status": "PENDING"} for s in steps],
            "limitations": [
                "SYNTHETIC_LOCAL_OPERATION",
                "MAT_ADVISORY_ONLY",
                "NO_ISSUANCE_AUTHORITY",
                "UNKNOWN_INTENTS_RETURN_UNSUPPORTED",
            ],
        }

    def _workflow(self, identifier, r, p):
        row = self.app.store.db.execute(
            "SELECT * FROM cp_workflows WHERE workflow_id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise CalibrationError("WORKFLOW_NOT_FOUND")
        if r.case_id != row["case_id"]:
            raise AccessDenied("CROSS_CASE_WORKFLOW_ACCESS_DENIED")
        self.app.authorize_case(row["case_id"], p)
        return json.loads(row["state_json"])

    def _save(self, state):
        state["version"] += 1
        state["updated_at"] = now_utc()
        self.app.store.db.execute(
            "UPDATE cp_workflows SET state_json=?,version=?,updated_at=? WHERE workflow_id=?",
            (
                canonical({k: v for k, v in state.items() if k != "_launch_job_ids"}),
                state["version"],
                state["updated_at"],
                state["workflow_id"],
            ),
        )
        return state

    def _advance(self, state, r, p):
        for step in state["steps"]:
            if step["status"] == "DONE":
                continue
            if step["tool"] == "HUMAN_CHECKPOINT":
                if not r.confirm_human:
                    state.update(status="WAITING_FOR_HUMAN", pending_human=True)
                    break
                if not r.rationale.strip() or not self.human.records(r.case_id, p):
                    raise CalibrationError(
                        "PERSISTED_HUMAN_DECISION_AND_RATIONALE_REQUIRED"
                    )
                step.update(
                    status="DONE",
                    actor=p.reviewer.reviewer_id,
                    at=now_utc(),
                    decision_versions=[
                        x["event_hash"] for x in self.human.records(r.case_id, p)
                    ],
                )
                state["pending_human"] = False
                continue
            if step.get("job_id"):
                job = self.app.invoke(
                    "cdf_get_job_status",
                    Request(case_id=r.case_id, job_id=step["job_id"]),
                    p,
                    transport="COPILOT",
                )["data"]
                step["job_status"] = job["status"]
                if job["status"] not in TERMINAL:
                    state["status"] = "WAITING_FOR_JOB"
                    if job["status"] == "QUEUED":
                        state["_launch_job_ids"] = [job["job_id"]]
                    break
                if job["status"] in ("FAILED", "CANCELLED", "BLOCKED_AUTHORIZATION"):
                    if (
                        r.retry
                        and state["executor"] in ("mock", "deterministic")
                        and step.get("retries", 0) < 1
                    ):
                        step["previous_job_id"] = step.pop("job_id")
                        step["retries"] = 1
                    else:
                        state.update(
                            status="FAILED",
                            failure=job["error_code"],
                            retry_policy="EXPLICIT_SYNTHETIC_RETRY_ONLY_NO_AMBIGUOUS_PROVIDER_REPLAY",
                        )
                        break
                else:
                    step.update(
                        status="DONE",
                        result=self.app.invoke(
                            "cdf_get_job_result",
                            Request(case_id=r.case_id, job_id=step["job_id"]),
                            p,
                            transport="COPILOT",
                        )["data"],
                    )
                    continue
            tool = step["tool"]
            if tool.startswith("knowledge:"):
                step.update(
                    status="DONE",
                    result=self.knowledge.dispatch(
                        "knowledge",
                        r.model_copy(update={"domain": tool.split(":")[1]}),
                        p,
                    ),
                )
                continue
            if tool in ("quality", "decisions", "calibration"):
                service = self.knowledge if tool == "quality" else self.human
                step.update(status="DONE", result=service.dispatch(tool, r, p))
                continue
            req = Request(
                case_id=r.case_id,
                executor=(
                    state["executor"]
                    if tool in ("cdf_review_document", "cdf_run_multi_agent_debate")
                    else "deterministic"
                ),
                timeout=180,
                idempotency_key=state["workflow_id"]
                + "-"
                + str(state["steps"].index(step))
                + "-"
                + str(step.get("retries", 0)),
            )
            result = self.app.invoke(tool, req, p, transport="COPILOT")["data"]
            if result.get("job_id"):
                step.update(
                    status="RUNNING",
                    job_id=result["job_id"],
                    job_status=result["status"],
                )
                state.update(
                    status="WAITING_FOR_JOB", _launch_job_ids=[result["job_id"]]
                )
                break
            step.update(status="DONE", result=result)
        else:
            state.update(status="COMPLETED_DRAFT", pending_human=False)
        return self._save(state)

    def _perform(self, op, r, p):
        if op == "catalog":
            return {
                "templates": [
                    {
                        **v,
                        "id": k,
                        "institutionally_validated": False,
                        "failure_conditions": [
                            "AUTHORIZATION_LOST",
                            "SOURCE_OR_EXECUTOR_UNSUPPORTED",
                            "JOB_FAILURE",
                        ],
                        "completion": "DRAFT_OUTPUTS_OR_GROUNDED_RECORDS_ONLY",
                        "required_evidence": "CASE_BOUND_SOURCE_AND_REFERENCES",
                    }
                    for k, v in TEMPLATES.items()
                ],
                "capabilities": [
                    "CONVERSATIONAL_ROUTING",
                    "DURABLE_WORKFLOWS",
                    "GROUNDED_KNOWLEDGE",
                    "VERSIONED_HUMAN_REVIEW",
                    "SUPPLEMENTAL_EXTRACTION",
                    "ADMIN_HEALTH",
                ],
                "private_activation": "DISABLED",
            }
        if op == "plan":
            return self.plan(r, p)
        if op == "ask":
            plan = self.plan(r, p)
            if plan.get("template") in (
                "delegated_authority_analysis",
                "organizational_responsibility_review",
            ):
                return self.knowledge.dispatch(
                    "knowledge",
                    r.model_copy(
                        update={
                            "domain": (
                                "authority"
                                if plan["template"] == "delegated_authority_analysis"
                                else "responsibility"
                            )
                        }
                    ),
                    p,
                )
            if plan["status"] in ("BLOCKED", "UNSUPPORTED", "HUMAN_INPUT_REQUIRED"):
                return plan
            case = self.app.calibration.case(r.case_id, p.reviewer)
            quality = self.knowledge.dispatch("quality", r, p)
            dashboard = self.app.intelligence.dashboard(r.case_id, p.reviewer)
            observations = case["observations"]
            if re.search(r"unresolved|غير المحسوم|غير المعالج", r.text.casefold()):
                observations = [
                    o
                    for o in observations
                    if o["observation_id"] in dashboard["unresolved_material"]
                ]
                quality["assessments"] = [
                    q
                    for q in quality["assessments"]
                    if q["observation_id"] in dashboard["unresolved_material"]
                ]
            return {
                "case_id": r.case_id,
                "classification": "RETRIEVED_CASE_RECORDS_AND_RULE_BASED_SUMMARY",
                "observations": observations[: r.limit],
                "quality": quality,
                "release_gate": self.app.intelligence.dashboard(r.case_id, p.reviewer)[
                    "release_gate"
                ],
                "limitations": [
                    "NO_MODEL_INFERENCE",
                    "MATERIAL_FINDINGS_REQUIRE_HUMAN_REVIEW",
                ],
                "suggested_plan": plan,
            }
        if op == "start":
            plan = self.plan(r, p)
            if plan["status"] != "READY":
                return plan
            identifier = "WF-" + uuid.uuid4().hex
            at = now_utc()
            state = {
                **plan,
                "workflow_id": identifier,
                "owner": p.reviewer.reviewer_id,
                "status": "PLANNED",
                "version": 0,
                "pending_human": False,
                "created_at": at,
                "updated_at": at,
            }
            self.app.store.db.execute(
                "INSERT INTO cp_workflows VALUES (?,?,?,?,?,?,?)",
                (
                    identifier,
                    r.case_id,
                    p.reviewer.reviewer_id,
                    canonical(state),
                    0,
                    at,
                    at,
                ),
            )
            return self._advance(state, r, p)
        if op == "status" and not r.workflow_id:
            return {
                "case_id": r.case_id,
                "workflows": [
                    json.loads(row["state_json"])
                    for row in self.app.store.db.execute(
                        "SELECT state_json FROM cp_workflows WHERE case_id=? ORDER BY created_at DESC LIMIT 30",
                        (r.case_id,),
                    )
                ],
            }
        if op in ("status", "resume", "cancel"):
            state = self._workflow(r.workflow_id, r, p)
            if op == "status":
                for step in state["steps"]:
                    if step.get("job_id"):
                        step["current_job"] = self.app.job(step["job_id"], p, r.case_id)
                return state
            if (
                r.expected_version is None
                or str(state["version"]) != r.expected_version
            ):
                raise Conflict("WORKFLOW_VERSION_CHANGED")
            if op == "cancel":
                for step in state["steps"]:
                    if step.get("job_id") and self.app.job(step["job_id"], p)[
                        "status"
                    ] in ("QUEUED", "RUNNING"):
                        self.app.invoke(
                            "cdf_cancel_job",
                            Request(
                                case_id=r.case_id,
                                job_id=step["job_id"],
                                idempotency_key=state["workflow_id"] + "-cancel",
                            ),
                            p,
                            transport="COPILOT",
                        )
                state["status"] = "CANCELLED"
                return self._save(state)
            if state["status"] == "CANCELLED":
                raise Conflict("CANCELLED_WORKFLOW_CANNOT_RESUME")
            if state["status"] == "COMPLETED_DRAFT":
                return state
            from ..execution.jobs import recover_stale

            recover_stale(self.app, case_id=r.case_id)
            return self._advance(state, r, p)
        if op in ("knowledge", "quality"):
            return self.knowledge.dispatch(op, r, p)
        if op in ("decision", "decisions", "memory", "calibration"):
            return self.human.dispatch(op, r, p)
        if op in ("ingest", "documents", "correct"):
            return self.ingestion.dispatch(op, r, p)
        if op in ("health", "executors", "backup", "restore_verify"):
            return self.operations.dispatch(op, r, p)
        if op == "history":
            jobs = self.app.store.db.execute(
                "SELECT job_id,run_id,status,error_stage FROM app_jobs WHERE case_id=? ORDER BY created_at",
                (r.case_id,),
            ).fetchall()
            return {
                "case_id": r.case_id,
                "jobs": [dict(j) for j in jobs],
                "attempts": [
                    dict(x)
                    for x in self.app.store.db.execute(
                        "SELECT execution_id,job_id,role,source,status,prompt_hash FROM app_agent_attempts WHERE job_id IN (SELECT job_id FROM app_jobs WHERE case_id=?) ORDER BY started_at",
                        (r.case_id,),
                    )
                ],
                "snapshots": [
                    {
                        "run_id": row["run_id"],
                        "snapshot_hash": row["snapshot_hash"],
                        "captured_at": row["captured_at"],
                    }
                    for row in self.app.store.db.execute(
                        "SELECT run_id,snapshot_hash,captured_at FROM executive_runs WHERE case_id=? ORDER BY captured_at",
                        (r.case_id,),
                    )
                ],
                "original_observations_preserved": True,
            }
        raise CalibrationError("UNSUPPORTED_COPILOT_OPERATION")
