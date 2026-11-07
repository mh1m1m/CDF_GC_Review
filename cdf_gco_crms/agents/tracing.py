"""Execution tracing (Article 16): one sanitised JSON line per agent invocation, plus run-level summaries.

A trace never stores prompt or payload text — only hashes, identifiers, token usage, latency, status and
evidence ids — so it can sit in a public evidence folder without disclosing institutional content.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path

from . import provenance as PV
from .contracts import MODES, STATUS_OK, AgentResponse
from .security import sanitize_record

TRACE_SCHEMA = "CDF-AGENT-TRACE-v7.12.2"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class TraceWriter:
    def __init__(self, path=None, *, run_id: str = ""):
        self.path = Path(path) if path else None
        self.run_id = run_id
        self.records: list[dict] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def head_hash(self) -> str | None:
        return self.records[-1]["line_hash"] if self.records else None

    def record(self, response: AgentResponse, **extra) -> dict:
        rec = {"schema": TRACE_SCHEMA, **response.to_record(), **extra}
        rec["Run_ID"] = response.run_id or self.run_id
        rec = sanitize_record(rec)
        rec["prev_hash"] = self.head_hash or PV.GENESIS         # hash chain: a later edit breaks verification
        rec["line_hash"] = PV.line_hash(rec)
        self.records.append(rec)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def summary(self) -> dict:
        """Counts by mode and status; live and mock inferences are reported separately, never summed."""
        by_mode = Counter(r["Mode"] for r in self.records)
        by_status = Counter(r["Execution_Status"] for r in self.records)
        by_source = Counter(r.get("Execution_Source", "FAILED") for r in self.records)
        live_ok = sum(1 for r in self.records if PV.is_trusted_live(r.get("Execution_Source", ""), r["Execution_Status"]))
        return {"run_id": self.run_id, "invocations": len(self.records),
                "by_mode": {m: by_mode.get(m, 0) for m in MODES}, "by_status": dict(by_status),
                "by_source": {s: by_source.get(s, 0) for s in PV.SOURCES},
                "actual_live_inference_count": live_ok,                       # PROVIDER_API + OK only
                "simulated_live_count": by_source.get(PV.SOURCE_SIMULATED_LIVE, 0),
                "cached_replay_count": by_source.get(PV.SOURCE_CACHED, 0),
                "mock_inference_count": by_source.get(PV.SOURCE_MOCK, 0),
                "trace_head_hash": self.head_hash,
                "providers": sorted({r["Provider"] for r in self.records}),
                "models": sorted({r["Model"] for r in self.records}),
                "token_usage": {"input": sum(r["Token_Usage"].get("input_tokens", 0) for r in self.records),
                                "output": sum(r["Token_Usage"].get("output_tokens", 0) for r in self.records)},
                "trace_path": str(self.path) if self.path else None}
