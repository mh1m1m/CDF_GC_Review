"""Execution tracing (Article 16): one sanitised JSON line per agent invocation, plus run-level summaries.

A trace never stores prompt or payload text — only hashes, identifiers, token usage, latency, status and
evidence ids — so it can sit in a public evidence folder without disclosing institutional content.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path

from .contracts import MODE_LIVE, MODES, STATUS_OK, AgentResponse
from .security import sanitize_record

TRACE_SCHEMA = "CDF-AGENT-TRACE-v7.12.1"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class TraceWriter:
    def __init__(self, path=None, *, run_id: str = ""):
        self.path = Path(path) if path else None
        self.run_id = run_id
        self.records: list[dict] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, response: AgentResponse, **extra) -> dict:
        rec = {"schema": TRACE_SCHEMA, "Run_ID": self.run_id, **response.to_record(), **extra}
        rec = sanitize_record(rec)
        self.records.append(rec)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def summary(self) -> dict:
        """Counts by mode and status; live and mock inferences are reported separately, never summed."""
        by_mode = Counter(r["Mode"] for r in self.records)
        by_status = Counter(r["Execution_Status"] for r in self.records)
        live_ok = sum(1 for r in self.records if r["Mode"] == MODE_LIVE and r["Execution_Status"] == STATUS_OK)
        return {"run_id": self.run_id, "invocations": len(self.records),
                "by_mode": {m: by_mode.get(m, 0) for m in MODES}, "by_status": dict(by_status),
                "actual_live_inference_count": live_ok,
                "mock_inference_count": by_mode.get("MOCK", 0),
                "providers": sorted({r["Provider"] for r in self.records}),
                "models": sorted({r["Model"] for r in self.records}),
                "token_usage": {"input": sum(r["Token_Usage"].get("input_tokens", 0) for r in self.records),
                                "output": sum(r["Token_Usage"].get("output_tokens", 0) for r in self.records)},
                "trace_path": str(self.path) if self.path else None}
