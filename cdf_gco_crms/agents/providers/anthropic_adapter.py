"""Anthropic Claude provider adapter (LIVE mode): real model inference through the official SDK.

Credentials are never hard-coded or read by this module: ``anthropic.Anthropic()`` resolves them from the
environment (``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN`` or a CLI profile). Without a credential the
first call fails with ``ProviderFailure(kind="AUTHENTICATION")`` — never with a fabricated response.

Each ``complete`` is one fresh ``messages.create`` call: a new conversation, the role's system text, the
payload as the single user turn, and a JSON-schema output format so the reply validates before use.
"""
from __future__ import annotations

import time

from ..contracts import MODE_LIVE, AgentRequest, TokenUsage
from .base import ProviderAdapter, ProviderConfig, ProviderFailure, ProviderResult

MAX_RATE_LIMIT_WAIT = 30.0


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"
    mode = MODE_LIVE

    def __init__(self, config: ProviderConfig | None = None, client=None):
        super().__init__(config)
        self._client = client
        self.client_injected = client is not None     # provenance: an injected client is never a trusted provider path

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:                  # the SDK is an optional dependency of the live runtime
                raise ProviderFailure("anthropic SDK not installed (pip install anthropic)", kind="SDK_MISSING") from exc
            self._client = anthropic.Anthropic(timeout=self.config.timeout_seconds, max_retries=self.config.max_retries)
        return self._client

    def complete(self, request: AgentRequest) -> ProviderResult:
        import anthropic
        client = self._get_client()
        model = request.model or self.model
        attempts = 0
        while True:
            attempts += 1
            try:
                raw = client.messages.with_raw_response.create(
                    model=model,
                    max_tokens=request.max_tokens,
                    system=request.system,
                    messages=[{"role": "user", "content": request.user_text}],
                    output_config={"format": {"type": "json_schema", "schema": request.schema}},
                )
                response = raw.parse()
                request_id = (raw.headers.get("request-id") if getattr(raw, "headers", None) else None) \
                    or getattr(response, "_request_id", None)
                break
            except anthropic.AuthenticationError as exc:
                raise ProviderFailure("authentication failed", kind="AUTHENTICATION") from exc
            except anthropic.PermissionDeniedError as exc:
                raise ProviderFailure("permission denied", kind="PERMISSION") from exc
            except anthropic.NotFoundError as exc:
                raise ProviderFailure("model or endpoint not found", kind="NOT_FOUND") from exc
            except anthropic.BadRequestError as exc:
                raise ProviderFailure("bad request", kind="BAD_REQUEST") from exc
            except anthropic.RateLimitError as exc:
                if attempts >= self.config.max_retries + 1:
                    raise ProviderFailure("rate limited after bounded retries", retryable=True, kind="RATE_LIMIT") from exc
                wait = min(MAX_RATE_LIMIT_WAIT, float(exc.response.headers.get("retry-after", "5") or 5))
                time.sleep(wait)
            except anthropic.APIStatusError as exc:
                raise ProviderFailure(f"API error {exc.status_code}", retryable=exc.status_code >= 500,
                                      kind="API_STATUS") from exc
            except anthropic.APITimeoutError as exc:
                raise ProviderFailure("request timed out", retryable=True, kind="TIMEOUT") from exc
            except anthropic.APIConnectionError as exc:
                raise ProviderFailure("connection error", retryable=True, kind="CONNECTION") from exc
            except TypeError as exc:                   # the SDK raises TypeError when no credential resolves
                if "authentication" in str(exc).lower():
                    raise ProviderFailure("no credential resolved (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / CLI profile)",
                                          kind="AUTHENTICATION") from exc
                raise ProviderFailure("request construction failed", kind="BAD_REQUEST") from exc
            except Exception as exc:                   # never let an unexpected error look like a result
                raise ProviderFailure(f"unexpected provider error: {type(exc).__name__}", kind="UNEXPECTED") from exc
        usage = TokenUsage(int(getattr(response.usage, "input_tokens", 0) or 0),
                           int(getattr(response.usage, "output_tokens", 0) or 0),
                           int(getattr(response.usage, "cache_read_input_tokens", 0) or 0))
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details is not None else None
            return ProviderResult("", response.id, response.model, usage, response.stop_reason, refused=True,
                                  refusal_category=category, provider_request_id=request_id)
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        if response.stop_reason == "max_tokens":
            raise ProviderFailure("response truncated at max_tokens", retryable=False, kind="TRUNCATED")
        return ProviderResult(text, response.id, response.model, usage, response.stop_reason, provider_request_id=request_id)
