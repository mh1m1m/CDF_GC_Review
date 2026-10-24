"""Isolated agent runner (Article 04): one fresh execution context per invocation.

Each ``run`` builds a new request (no shared conversation, no carried-over messages), assigns a unique
Execution_ID, derives the Context_ID from the exact prompt material, calls the provider once (plus bounded
retries for retryable failures), validates the reply against the role schema, records a sanitised trace and
returns an :class:`AgentResponse`. A provider failure, a refusal or a schema violation is returned as a
non-OK response — never as a default result. The runner has no access to any other role's request.
"""
from __future__ import annotations

import json
import time

from .contracts import (
    MODE_DETERMINISTIC, SCHEMAS, STATUS_OK, STATUS_PROVIDER_FAILURE, STATUS_REFUSED, STATUS_SCHEMA_INVALID,
    AgentRequest, AgentResponse, TokenUsage, canonical_json, new_id, sha256_text, validate,
)
from . import provenance as PV
from .providers.base import ProviderAdapter, ProviderFailure
from .security import assert_context_isolated, assert_transmission_allowed
from .tracing import TraceWriter, utc_now


class AgentRunner:
    def __init__(self, provider: ProviderAdapter | None, trace: TraceWriter | None = None, *, max_attempts: int = 2, invocation_observer=None):
        self.provider = provider
        self.invocation_observer=invocation_observer
        self.trace = trace or TraceWriter()
        self.max_attempts = max(1, max_attempts)
        self.execution_source = PV.classify_adapter(provider)     # derived once from the object, never from a label
        self.run_id = self.trace.run_id
        self.fingerprint: str | None = None

    @property
    def available(self) -> bool:
        return self.provider is not None

    @property
    def trusted_live(self) -> bool:
        return self.execution_source == PV.SOURCE_PROVIDER_API

    def bind(self, run_id: str, fingerprint: str | None) -> None:
        """Bind every following invocation to a run and the review-state fingerprint it serves."""
        self.run_id = run_id
        self.trace.run_id = run_id
        self.fingerprint = fingerprint

    def _stamp(self, resp: AgentResponse, request: AgentRequest, *, provider_request_id=None, failed=False) -> AgentResponse:
        resp.execution_source = PV.SOURCE_FAILED if failed else self.execution_source
        resp.provider_request_id = provider_request_id if self.execution_source == PV.SOURCE_PROVIDER_API else None
        resp.system_hash = PV.system_hash(request.system)
        resp.fingerprint = self.fingerprint
        resp.run_id = self.run_id
        return resp

    def run(self, role: str, system: str, payload: dict, *, schema: dict | None = None, max_tokens: int = 4096,
            agent_id: str | None = None, model: str | None = None, **trace_extra) -> AgentResponse:
        schema = schema or SCHEMAS[role]
        assert_context_isolated(payload)
        request = AgentRequest(role=role, system=system, payload=payload, schema=schema,
                               agent_id=agent_id or f"AGENT-{role}", max_tokens=max_tokens, model=model)
        execution_id = new_id("EXEC")
        if self.provider is None:
            resp = self._stamp(self._failure(request, execution_id, "no provider configured", "none", "none", MODE_DETERMINISTIC), request, failed=True)
            self.trace.record(resp, **trace_extra)
            return resp
        assert_transmission_allowed(payload, self.provider)
        if self.invocation_observer:
            self.invocation_observer(request,execution_id,self.execution_source)
        if self.execution_source == PV.SOURCE_SUPERVISED_CLI and hasattr(self.trace, "progress"):
            self.provider.progress_observer = lambda snapshot: self.trace.progress(execution_id, snapshot)
        started = time.perf_counter()
        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = self.provider.complete(request)
            except ProviderFailure as exc:
                last_error = f"{exc.kind}: {exc}"
                if exc.retryable and attempt < self.max_attempts:
                    continue
                resp = self._stamp(self._failure(request, execution_id, last_error, self.provider.name, self.provider.model,
                                                 self.provider.mode, latency_ms=int((time.perf_counter() - started) * 1000)),
                                   request, failed=True)
                self.trace.record(resp, attempts=attempt, executor_diagnostic=exc.diagnostics, **trace_extra)
                return resp
            latency = int((time.perf_counter() - started) * 1000)
            if result.refused:
                resp = AgentResponse(role, request.agent_id, execution_id, request.context_id, self.provider.mode,
                                     self.provider.name, result.model, STATUS_REFUSED, None, request.prompt_hash,
                                     sha256_text(""), result.invocation_id, utc_now(), latency, result.usage,
                                     error=f"provider refusal: {result.refusal_category}")
                self._stamp(resp, request, provider_request_id=result.provider_request_id, failed=True)
                self.trace.record(resp, attempts=attempt, **trace_extra)
                return resp
            output, errors = _parse(result.text, schema)
            status = STATUS_OK if not errors else STATUS_SCHEMA_INVALID
            resp = AgentResponse(role, request.agent_id, execution_id, request.context_id, self.provider.mode,
                                 self.provider.name, result.model, status, output if status == STATUS_OK else None,
                                 request.prompt_hash, sha256_text(result.text), result.invocation_id, utc_now(), latency,
                                 result.usage, error=None if not errors else "schema validation failed",
                                 schema_errors=errors, evidence_refs=_evidence_refs(output) if output else [])
            self._stamp(resp, request, provider_request_id=result.provider_request_id, failed=bool(errors))
            self.trace.record(resp, attempts=attempt, executor_receipt=result.execution_receipt, **trace_extra)
            return resp
        resp = self._stamp(self._failure(request, execution_id, last_error or "exhausted", self.provider.name, self.provider.model,
                                         self.provider.mode), request, failed=True)
        self.trace.record(resp, **trace_extra)
        return resp

    @staticmethod
    def _failure(request: AgentRequest, execution_id: str, error: str, provider: str, model: str, mode: str,
                 latency_ms: int = 0) -> AgentResponse:
        return AgentResponse(request.role, request.agent_id, execution_id, request.context_id, mode, provider, model,
                             STATUS_PROVIDER_FAILURE, None, request.prompt_hash, sha256_text(""), "", utc_now(),
                             latency_ms, TokenUsage(), error=error)


def _parse(text: str, schema: dict) -> tuple[dict | None, list[str]]:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, [f"not JSON: {exc}"]
    if not isinstance(obj, dict):
        return None, ["top-level value is not an object"]
    errors = validate(schema, obj)
    return (obj if not errors else None), errors


def _evidence_refs(output: dict) -> list[str]:
    refs: set[str] = set()
    for key in ("evidence_refs", "decisive_evidence"):
        for r in output.get(key, []) or []:
            if isinstance(r, str):
                refs.add(r)
    for item in output.get("observations", []) or []:
        if isinstance(item, dict):
            refs.update(r for r in item.get("evidence_refs", []) if isinstance(r, str))
    return sorted(refs)


def response_digest(resp: AgentResponse) -> str:
    """Stable digest of a response's substantive output (for chain events and duplicate detection)."""
    return sha256_text(canonical_json(resp.output or {}))
