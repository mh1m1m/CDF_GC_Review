"""Cached provider (CACHED mode): replays recorded LIVE responses by prompt hash. Never reported as live.

The cache is a JSON file ``{prompt_hash: {"text": ..., "model": ..., "invocation_id": ..., "recorded_mode": "LIVE"}}``
written by :class:`RecordingAdapter`. A miss is a :class:`ProviderFailure`, not a fabricated answer.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..contracts import MODE_CACHED, MODE_LIVE, AgentRequest, TokenUsage
from .base import ProviderAdapter, ProviderConfig, ProviderFailure, ProviderResult


class CachedAdapter(ProviderAdapter):
    name = "cached"
    mode = MODE_CACHED

    def __init__(self, cache_path, config: ProviderConfig | None = None):
        super().__init__(config or ProviderConfig(provider="cached", model="cached"))
        self.cache_path = Path(cache_path)
        self.cache: dict = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.is_file() else {}

    def complete(self, request: AgentRequest) -> ProviderResult:
        entry = self.cache.get(request.prompt_hash)
        if entry is None:
            raise ProviderFailure(f"no cached response for prompt {request.prompt_hash[:12]}", kind="CACHE_MISS")
        if entry.get("recorded_mode") != MODE_LIVE:
            raise ProviderFailure("cache entry was not recorded from a live inference", kind="CACHE_ORIGIN")
        return ProviderResult(entry["text"], f"cached:{entry.get('invocation_id', '')}", entry.get("model", "cached"),
                              TokenUsage(), entry.get("stop_reason"))


class RecordingAdapter(ProviderAdapter):
    """Wraps a LIVE adapter and records every successful completion for later CACHED replay."""

    def __init__(self, inner: ProviderAdapter, cache_path):
        super().__init__(inner.config)
        if inner.mode != MODE_LIVE:
            raise ValueError("only a LIVE adapter can be recorded")
        self.inner = inner
        self.name = inner.name
        self.mode = inner.mode
        self.cache_path = Path(cache_path)
        self.cache: dict = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.is_file() else {}

    def complete(self, request: AgentRequest) -> ProviderResult:
        res = self.inner.complete(request)
        if not res.refused:
            self.cache[request.prompt_hash] = {"text": res.text, "model": res.model, "invocation_id": res.invocation_id,
                                               "stop_reason": res.stop_reason, "recorded_mode": MODE_LIVE}
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return res
