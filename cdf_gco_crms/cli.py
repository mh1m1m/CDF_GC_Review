"""Codex-operable application CLI. No conflicting global executable is installed."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from pydantic import ValidationError
from .execution.contracts import Request, TOOLS
from .execution.service import ApplicationService, Conflict, TERMINAL
from .calibration.store import CalibrationError, AccessDenied

COMMANDS = {
    ("job", "recover"): "cdf_recover_case_jobs",
    ("case", "create"): "cdf_create_case",
    ("case", "status"): "cdf_get_case_status",
    ("case", "import"): "cdf_get_case_status",
    ("review", "run"): "cdf_review_document",
    ("review", "observations"): "cdf_get_observations",
    ("debate", "run"): "cdf_run_multi_agent_debate",
    ("debate", "trace"): "cdf_get_debate_trace",
    ("authority", "check"): "cdf_check_delegated_authority",
    ("organization", "check"): "cdf_get_department_responsibilities",
    ("calibration", "list"): "cdf_get_calibration_history",
    ("calibration", "save"): "cdf_calibrate_observation",
    ("report", "word"): "cdf_generate_word_report",
    ("report", "excel"): "cdf_generate_excel_dashboard",
    ("report", "pdf"): "cdf_generate_pdf_report",
    ("job", "status"): "cdf_get_job_status",
    ("job", "result"): "cdf_get_job_result",
    ("job", "cancel"): "cdf_cancel_job",
    ("artifact", "get"): "cdf_get_artifact",
    ("artifact", "status"): "cdf_get_artifact_status",
    ("executor", "probe"): "cdf_probe_executor",
    ("metrics", None): "cdf_get_dashboard_metrics",
    ("gate", None): "cdf_get_release_gate_status",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "group",
        choices=["init", "status", "acceptance", *sorted({k[0] for k in COMMANDS})],
    )
    parser.add_argument("action", nargs="?")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--case", dest="case_id")
    parser.add_argument("--source", default="synthetic-cooperation-v1")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--executor", default="deterministic")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--idempotency-key")
    parser.add_argument("--job", dest="job_id")
    parser.add_argument("--artifact", dest="artifact_id")
    parser.add_argument("--observation", dest="observation_id")
    parser.add_argument("--decision", default="KEEP_UNCHANGED")
    parser.add_argument("--rationale", default="")
    parser.add_argument("--evidence-hash", dest="expected_evidence_hash")
    parser.add_argument("--query", default="")
    parser.add_argument("--cursor", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--issue", action="store_true")
    args = parser.parse_args(argv)
    if args.group == "acceptance":
        from .acceptance.unified import main as acceptance

        return acceptance(
            ["--report-dir", str(args.output or "build/unified-acceptance")]
        )
    service = None
    try:
        token = os.getenv("CDF_CALIBRATION_DEV_TOKEN", "")
        if len(token) < 32:
            raise AccessDenied("SCOPED_DEVELOPMENT_CREDENTIAL_REQUIRED")
        service = ApplicationService(args.db, token=token)
        principal = service.authenticate(token)
        if args.group in ("init", "status"):
            from .execution.providers import readiness

            result = {
                "ok": True,
                "mode": "PUBLIC_SYNTHETIC_DEMO",
                "private_activation": "DISABLED",
                "database": str(service.store.path),
                "executors": readiness(),
            }
        else:
            tool = COMMANDS.get((args.group, args.action))
            if not tool:
                raise CalibrationError("UNKNOWN_CLI_OPERATION")
            data = {
                key: getattr(args, key)
                for key in Request.model_fields
                if hasattr(args, key)
            }
            if data["source"] == "synthetic":
                data["source"] = "synthetic-cooperation-v1"
            request = Request.model_validate(data)
            result = service.invoke(tool, request, principal, transport="CLI")
            if result["data"].get("job_id") and tool in (
                "cdf_review_document",
                "cdf_run_multi_agent_debate",
                "cdf_generate_word_report",
                "cdf_generate_excel_dashboard",
                "cdf_generate_pdf_report",
                "cdf_probe_executor",
            ):
                from .execution.jobs import launch

                launch(service, result["data"]["job_id"], principal)
            if args.wait and result["data"].get("job_id"):
                deadline = time.monotonic() + args.timeout + 10
                while time.monotonic() < deadline:
                    job = service.job(result["data"]["job_id"], principal, args.case_id)
                    if job["status"] in TERMINAL:
                        result = service.invoke(
                            "cdf_get_job_result",
                            Request(job_id=job["job_id"], case_id=args.case_id),
                            principal,
                            transport="CLI",
                        )
                        break
                    time.sleep(0.15)
                else:
                    raise Conflict("CLIENT_WAIT_TIMEOUT_JOB_REMAINS_PERSISTED")
            if args.output and tool == "cdf_get_artifact":
                import base64, hashlib

                content = bytearray()
                offset = 0
                while True:
                    chunk = service.invoke(
                        tool,
                        Request(
                            artifact_id=args.artifact_id,
                            case_id=args.case_id,
                            cursor=offset,
                        ),
                        principal,
                        transport="CLI",
                    )["data"]
                    content.extend(base64.b64decode(chunk["content_base64"]))
                    if chunk["next_offset"] is None:
                        break
                    offset = chunk["next_offset"]
                if hashlib.sha256(content).hexdigest() != chunk["sha256"]:
                    raise CalibrationError("ARTIFACT_DOWNLOAD_INTEGRITY_FAILED")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_bytes(content)
                result["data"] = {
                    k: v for k, v in chunk.items() if k != "content_base64"
                }
                result["data"]["saved_to"] = str(args.output)
        print(json.dumps(result, ensure_ascii=False))
        job = result.get("data", {}).get("job", {})
        return (
            4
            if job.get("status") in ("FAILED", "CANCELLED", "BLOCKED_AUTHORIZATION")
            else 0
        )
    except (CalibrationError, AccessDenied, ValidationError) as exc:
        code = (
            "INPUT_VALIDATION_FAILED" if isinstance(exc, ValidationError) else str(exc)
        )
        print(
            json.dumps(
                {"ok": False, "error": {"code": code, "type": type(exc).__name__}}
            )
        )
        return (
            3
            if isinstance(exc, AccessDenied)
            else 5 if isinstance(exc, Conflict) else 2
        )
    finally:
        if service:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
