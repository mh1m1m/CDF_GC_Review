"""Provider abstraction (Article 05): one interface, several adapters, modes never conflated.

A provider turns an :class:`AgentRequest` into raw text plus provenance. It knows nothing about roles,
evidence or dispositions; the runner validates the text against the role schema. Credentials are never
read here: the Anthropic adapter lets the SDK resolve them from the environment, the mock adapter needs none.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..contracts import MODE_LIVE, MODE_MOCK, MODES, AgentRequest, TokenUsage

DEFAULT_MODEL = "claude-opus-5-5"
ENV_PROVIDER = "CDF_AI_PROVIDER"            # "anthropic" | "mock" | "" (unset: no live provider)
ENV_MODEL = "CDF_AI_MODEL"
ENV_TIMEOUT = "CDF_AI_TIMEOUT_SECONDS"
ENV_RETRIES = "CDF_AI_MAX_RETRIES"
ENV_DATA_AUTH = "CDF_AI_DATA_AUTHORIZATION"  # "SYNTHETIC_ONLY" (default) | "INSTITUTIONAL_AUTHORIZED:<reference>"
DATA_SYNTHETIC_ONLY = "SYNTHETIC_ONLY"
DATA_INSTITUTIONAL_PREFIX = "INSTITUTIONAL_AUTHORIZED:"


class ProviderFailure(RuntimeError):
    """The provider did not return a usable completion. ``retryable`` says whether a bounded retry is sensible.

    A failure is a failure: the runner records it and no role result exists. Nothing downstream may treat it
    as an approval, a no-objection or a cleared gate.
    """

    def __init__(self, message: str, *, retryable: bool = False, kind: str = "PROVIDER_ERROR"):
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind


@dataclass
class ProviderResult:
    text: str
    invocation_id: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    stop_reason: str | None = None
    refused: bool = False
    refusal_category: str | None = None


@dataclass(frozen=True)
class ProviderConfig:
    provider: str = ""
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 120.0
    max_retries: int = 2
    data_authorization: str = DATA_SYNTHETIC_ONLY

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ProviderConfig":
        e = os.environ if env is None else env
        return cls(provider=(e.get(ENV_PROVIDER) or "").strip().lower(), model=e.get(ENV_MODEL) or DEFAULT_MODEL,
                   timeout_seconds=float(e.get(ENV_TIMEOUT) or 120.0), max_retries=int(e.get(ENV_RETRIES) or 2),
                   data_authorization=e.get(ENV_DATA_AUTH) or DATA_SYNTHETIC_ONLY)

    @property
    def institutional_data_authorized(self) -> bool:
        return self.data_authorization.startswith(DATA_INSTITUTIONAL_PREFIX) and \
            len(self.data_authorization) > len(DATA_INSTITUTIONAL_PREFIX)


class ProviderAdapter:
    """Base class. ``mode`` is fixed per adapter class and reported on every response."""
    name: str = "base"
    mode: str = MODE_MOCK

    def __init__(self, config: ProviderConfig | None = None):
        self.config = config or ProviderConfig()
        if self.mode not in MODES:
            raise ValueError(self.mode)

    @property
    def model(self) -> str:
        return self.config.model

    def complete(self, request: AgentRequest) -> ProviderResult:   # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> dict:
        return {"provider": self.name, "mode": self.mode, "model": self.model,
                "data_authorization": self.config.data_authorization}


def provider_from_env(env: dict | None = None) -> ProviderAdapter | None:
    """The configured provider, or None when no live provider is configured (never a silent mock)."""
    cfg = ProviderConfig.from_env(env)
    if cfg.provider == "anthropic":
        from .anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter(cfg)
    if cfg.provider == "mock":
        from .mock_adapter import MockAdapter
        return MockAdapter(cfg)
    return None


def is_live(adapter: ProviderAdapter | None) -> bool:
    return adapter is not None and adapter.mode == MODE_LIVE
