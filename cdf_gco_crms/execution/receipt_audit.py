"""Independent read-only provenance consistency check; no external attestation claim."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from ..agents import provenance as P


def require(condition, code):
    if not condition:
        raise ValueError(code)


def evidence_labels(provider_api_completions: int, native_cli_completions: int) -> dict:
    """Only provider-API completions are live inference evidence. A supervised CLI completion is reported on its own
    and never under the live label: it cannot satisfy provenance or the release attestation."""
    return {
        "live_execution_evidence": ("PROVIDER_API_PRESENT_REQUIRES_EXTERNAL_RECONCILIATION" if provider_api_completions
                                    else "BLOCKED_EXTERNAL_NO_COMPLETION"),
        "supervised_cli_evidence": ("CLI_COMPLETION_PRESENT_NOT_PROVIDER_API_EVIDENCE" if native_cli_completions else "NONE"),
    }


def verify(database, case_id):
    if not case_id.startswith("SYN-"):
        raise ValueError("PUBLIC_SYNTHETIC_CASE_REQUIRED")
    from ..storage import connect

    db = connect(database, readonly=True)
    try:
        require(
            {r[0] for r in db.execute("SELECT mode FROM runtime_mode")}
            == {"PUBLIC_SYNTHETIC_DEMO"},
            "DATABASE_MODE_MISMATCH",
        )
        case = db.execute(
            "SELECT * FROM app_cases WHERE case_id=?", (case_id,)
        ).fetchone()
        require(
            case
            and hashlib.sha256(case["document_blob"]).hexdigest()
            == case["source_hash"],
            "SOURCE_HASH_MISMATCH",
        )
        api, native, unknown, total = (0, 0, 0, 0)
        jobs = []
        for job in db.execute(
            "SELECT job_id,executor,status,error_code FROM app_jobs WHERE case_id=? ORDER BY created_at",
            (case_id,),
        ):
            records = []
            for row in db.execute(
                "SELECT * FROM app_agent_attempts WHERE job_id=? ORDER BY started_at,execution_id",
                (job["job_id"],),
            ):
                total += 1
                receipt = (
                    json.loads(row["receipt_json"]) if row["receipt_json"] else None
                )
                if not receipt or receipt.get("diagnostic_only"):
                    require(
                        row["status"] in ("STARTED", "OUTCOME_UNKNOWN"),
                        "MISSING_TERMINAL_RECEIPT",
                    )
                    unknown += 1
                    continue
                require(
                    receipt["line_hash"] == P.line_hash(receipt),
                    "TRACE_LINE_HASH_MISMATCH",
                )
                require(
                    receipt["Execution_ID"] == row["execution_id"]
                    and receipt["Prompt_Hash"] == row["prompt_hash"],
                    "ATTEMPT_BINDING_MISMATCH",
                )
                require(
                    receipt["Agent_Role"] == row["role"]
                    and receipt["Application_Job_ID"] == job["job_id"],
                    "JOB_ROLE_BINDING_MISMATCH",
                )
                require(
                    receipt["Execution_Status"] == row["status"],
                    "ATTEMPT_STATUS_MISMATCH",
                )
                records.append(receipt)
                if row["status"] == "OK":
                    require(
                        row["source"] == receipt["Execution_Source"],
                        "SUCCESS_SOURCE_MISMATCH",
                    )
                    if row["source"] == "PROVIDER_API":
                        require(
                            receipt.get("Provider_Request_ID")
                            and receipt.get("Invocation_ID"),
                            "API_RECEIPT_MISSING",
                        )
                        api += 1
                    elif row["source"] == "SUPERVISED_CLI":
                        cli = receipt.get("executor_receipt") or {}
                        require(
                            cli.get("inference_verified") is True
                            and cli.get("phase") == "VERIFIED_NATIVE_COMPLETION",
                            "NATIVE_COMPLETION_MISSING",
                        )
                        require(
                            receipt.get("Invocation_ID", "").startswith(
                                ("CODEX:", "CLAUDE:")
                            ),
                            "NATIVE_ID_MISSING",
                        )
                        native += 1
            if records:
                by_previous = {r["prev_hash"]: r for r in records}
                require(len(by_previous) == len(records), "FORKED_TRACE_CHAIN")
                ordered = []
                previous = P.GENESIS
                while previous in by_previous:
                    record = by_previous.pop(previous)
                    ordered.append(record)
                    previous = record["line_hash"]
                require(
                    not by_previous and P.verify_chain(ordered)[0], "BROKEN_TRACE_CHAIN"
                )
            jobs.append(dict(job))
        return {
            "schema": "CDF-RECEIPT-AUDIT-1",
            "case_id": case_id,
            "source_hash": case["source_hash"],
            "local_integrity": "PASS",
            "attempts_checked": total,
            "provider_api_completions": api,
            "native_cli_completions": native,
            "incomplete_attempts": unknown,
            "jobs": jobs,
            "external_provider_reconciliation": "NOT_VERIFIED",
            "actual_chatgpt_registration": "BLOCKED_EXTERNAL",
            "actual_claude_registration": "BLOCKED_EXTERNAL",
            **evidence_labels(api, native),
            "institutional_authorization": "NOT_AUTHORIZED",
        }
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True)
    p.add_argument("--case", required=True)
    args = p.parse_args()
    print(json.dumps(verify(args.db, args.case), indent=2))


if __name__ == "__main__":
    main()
