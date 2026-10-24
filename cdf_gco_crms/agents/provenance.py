"""Execution provenance (live-inference provenance assurance directive).

The question is not "what does the record say?" but "where did the response come from?". The runner derives
the **execution source** from the adapter object the runtime constructed, never from a declared ``mode`` or a
self-reported provider name:

  PROVIDER_API          the registered live adapter class, built by the runtime from configuration, returned a
                        provider response that carries provider-originated evidence (request id / message id)
  PROVIDER_API_UNTRUSTED the registered class, but with an injected client (test harness) — not trusted
  SIMULATED_LIVE        any other adapter that declares mode LIVE (test fixtures that imitate a provider)
  MOCK_SCRIPT           the scripted mock adapter
  CACHED_REPLAY         replay of a previously recorded response (never a new inference)
  DETERMINISTIC_RULES   no provider; the rule engine
  FAILED                the call did not produce a usable response (never counts as execution)

Only PROVIDER_API with status OK is a live inference. Everything downstream (trace counts, receipts,
independence, the release gate) keys on this field; a fixture can set ``mode``, it cannot set the source.

The trace is a hash chain (``prev_hash`` / ``line_hash``); its head is stored in the gate record and signed
into the release attestation, so a line edited after the fact breaks verification. Locally generated
telemetry (Execution_ID, Context_ID, hashes) is kept apart from provider-originated evidence
(Provider_Request_ID, Invocation_ID = provider message id, model echoed by the server, usage).
"""
from __future__ import annotations

import hashlib
import json

SOURCE_PROVIDER_API = "PROVIDER_API"
SOURCE_PROVIDER_API_UNTRUSTED = "PROVIDER_API_UNTRUSTED_CLIENT"
SOURCE_SIMULATED_LIVE = "SIMULATED_LIVE"
SOURCE_MOCK = "MOCK_SCRIPT"
SOURCE_CACHED = "CACHED_REPLAY"
SOURCE_DETERMINISTIC = "DETERMINISTIC_RULES"
SOURCE_FAILED = "FAILED"
SOURCES = (SOURCE_PROVIDER_API, SOURCE_PROVIDER_API_UNTRUSTED, SOURCE_SIMULATED_LIVE, SOURCE_MOCK, SOURCE_CACHED,
           SOURCE_DETERMINISTIC, SOURCE_FAILED)
TRUSTED_LIVE_SOURCES = (SOURCE_PROVIDER_API,)


def trusted_live_adapter_types() -> tuple[type, ...]:
    """The adapter classes whose responses are provider-originated. Exact class match only: a subclass that
    overrides ``complete`` is not the registered adapter."""
    from .providers.anthropic_adapter import AnthropicAdapter
    return (AnthropicAdapter,)


def classify_adapter(adapter) -> str:
    """Execution source of an adapter object (see module docstring)."""
    if adapter is None:
        return SOURCE_DETERMINISTIC
    from .providers.cached_adapter import CachedAdapter, RecordingAdapter
    from .providers.mock_adapter import MockAdapter
    if isinstance(adapter, RecordingAdapter):
        inner = classify_adapter(adapter.inner)
        return inner if inner == SOURCE_PROVIDER_API else SOURCE_SIMULATED_LIVE
    if type(adapter) is CachedAdapter:
        return SOURCE_CACHED
    if type(adapter) in trusted_live_adapter_types():
        return SOURCE_PROVIDER_API if not getattr(adapter, "client_injected", False) else SOURCE_PROVIDER_API_UNTRUSTED
    if type(adapter) is MockAdapter:
        return SOURCE_MOCK
    if getattr(adapter, "mode", "") == "LIVE":
        return SOURCE_SIMULATED_LIVE
    return SOURCE_MOCK


def is_trusted_live(source: str, status: str) -> bool:
    return source in TRUSTED_LIVE_SOURCES and status == "OK"


def system_hash(system: str) -> str:
    return hashlib.sha256(system.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ trace chain
GENESIS = "GENESIS"


def line_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "line_hash"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def verify_chain(records: list[dict]) -> tuple[bool, str | None, str]:
    """(intact, head_hash, reason). Every line must name the previous line's hash and hash to its own line_hash."""
    prev = GENESIS
    for i, r in enumerate(records):
        if r.get("prev_hash") != prev:
            return False, None, f"line {i + 1}: prev_hash mismatch"
        if r.get("line_hash") != line_hash(r):
            return False, None, f"line {i + 1}: line_hash mismatch"
        prev = r["line_hash"]
    return True, (prev if records else None), ""
