"""Mock provider (MOCK mode): scripted responses for tests. Never reported as live inference.

A script maps a role (or a role and a predicate on the payload) to the JSON object the "model" returns.
Unscripted roles raise :class:`ProviderFailure` so that a test cannot pass on an accidental default.
Also usable as a fault injector: ``fail_roles`` makes the named roles fail like a provider outage.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from ..contracts import MODE_MOCK, AgentRequest, TokenUsage
from .base import ProviderAdapter, ProviderConfig, ProviderFailure, ProviderResult

Script = dict[str, dict | Callable[[dict], dict] | list]


class MockAdapter(ProviderAdapter):
    name = "mock"
    mode = MODE_MOCK

    def __init__(self, config: ProviderConfig | None = None, script: Script | None = None,
                 fail_roles: set[str] | None = None, refuse_roles: set[str] | None = None, raw_text: dict | None = None):
        super().__init__(config or ProviderConfig(provider="mock", model="mock-model"))
        self.script: Script = dict(script or {})
        self.fail_roles = set(fail_roles or ())
        self.refuse_roles = set(refuse_roles or ())
        self.raw_text = dict(raw_text or {})          # role -> raw (possibly invalid) text, for schema-failure tests
        self.calls: list[AgentRequest] = []
        self._n = 0

    def complete(self, request: AgentRequest) -> ProviderResult:
        self.calls.append(request)
        self._n += 1
        inv = f"mock-{self._n:04d}"
        if request.role in self.fail_roles:
            raise ProviderFailure(f"injected provider failure for {request.role}", retryable=False, kind="INJECTED")
        if request.role in self.refuse_roles:
            return ProviderResult("", inv, self.model, TokenUsage(), "refusal", refused=True, refusal_category="injected")
        if request.role in self.raw_text:
            return ProviderResult(self.raw_text[request.role], inv, self.model, TokenUsage(), "end_turn")
        entry = self.script.get(request.role)
        if entry is None:
            raise ProviderFailure(f"no scripted response for role {request.role}", kind="UNSCRIPTED")
        if isinstance(entry, list):                    # a queue of responses consumed in order
            if not entry:
                raise ProviderFailure(f"script exhausted for role {request.role}", kind="UNSCRIPTED")
            out = entry.pop(0)
        elif callable(entry):
            out = entry(request.payload)
        else:
            out = entry
        text = json.dumps(out, ensure_ascii=False)
        return ProviderResult(text, inv, self.model, TokenUsage(len(request.user_text) // 4, len(text) // 4), "end_turn")
