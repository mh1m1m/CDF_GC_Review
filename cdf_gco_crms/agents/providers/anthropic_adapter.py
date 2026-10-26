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
from ..provenance import official_endpoint
from .base import ProviderAdapter, ProviderConfig, ProviderFailure, ProviderResult

MAX_RATE_LIMIT_WAIT = 30.0
# Structured outputs accept a subset of JSON Schema: no numeric bounds, no string length bounds, no complex array
# constraints, and every object closed with additionalProperties: false. The full role schema stays the contract:
# the runner validates every reply against it client-side (agents/runner.py), so only the copy sent is reduced.
_UNSUPPORTED_KEYWORDS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength",
                         "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "minProperties",
                         "maxProperties", "contains", "minContains", "maxContains"}
_SUPPORTED_FORMATS = {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
# Current models think before answering and thinking counts against max_tokens; a role's small budget would truncate
# the reply. Non-streaming requests stay below the SDK's long-request threshold.
MIN_MAX_TOKENS = 16000
MAX_NONSTREAMING_TOKENS = 20000


def wire_schema(schema):
    """The copy of a role schema sent as the structured-output format (see the note above)."""
    if isinstance(schema, list):
        return [wire_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_KEYWORDS:
            continue
        if key == "format" and value not in _SUPPORTED_FORMATS:
            continue
        if key in ("properties", "$defs", "definitions", "patternProperties"):
            out[key] = {name: wire_schema(sub) for name, sub in value.items()}
        else:
            out[key] = wire_schema(value)
    if out.get("type") == "object" or (isinstance(out.get("type"), list) and "object" in out["type"]) \
            or "properties" in out:
        out["additionalProperties"] = False
    return out


# The API's error text is never stored (it can echo the request); it is reduced to one of these fixed reasons, checked
# in order, so the website can say what to fix. The provider's request id is kept: it carries no content.
_REJECTION_REASONS = (
    ("CREDIT_BALANCE_TOO_LOW", ("credit balance",)),
    ("BILLING", ("billing", "payment", "spend limit", "usage limit")),
    ("PROMPT_TOO_LONG", ("prompt is too long", "too many tokens", "context window")),
    ("OUTPUT_SCHEMA_REJECTED", ("schema", "output_config", "output_format")),
    ("MAX_TOKENS_REJECTED", ("max_tokens",)),
    ("THINKING_REJECTED", ("thinking",)),
    ("EFFORT_REJECTED", ("effort",)),
    ("SAMPLING_PARAMETER_REJECTED", ("temperature", "top_p", "top_k")),
    ("DATA_RETENTION_POLICY", ("retention",)),
    ("MODEL_REJECTED", ("model",)),
)


def rejection_reason(exc) -> str:
    """Fixed reason code and provider request id for an API error, without any of the error text."""
    body = getattr(exc, "body", None)
    message = ""
    if isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        message = str(inner.get("message") or "")
    message = (message or str(exc)).lower()
    code = next((name for name, needles in _REJECTION_REASONS if any(n in message for n in needles)), "UNCLASSIFIED")
    request_id = getattr(exc, "request_id", None)
    if not request_id:
        response = getattr(exc, "response", None)
        request_id = response.headers.get("request-id") if getattr(response, "headers", None) else None
    request_id = str(request_id) if request_id and str(request_id).replace("_", "").isalnum() else None
    return f"[{code}]" + (f" request_id={request_id[:64]}" if request_id else "")


def _budget(requested: int) -> int:
    import os

    floor = int(os.getenv("CDF_AI_MIN_MAX_TOKENS", str(MIN_MAX_TOKENS)) or MIN_MAX_TOKENS)
    return min(max(int(requested or 0), floor), MAX_NONSTREAMING_TOKENS)


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"
    mode = MODE_LIVE
    endpoint = official_endpoint("anthropic")

    def __init__(self, config: ProviderConfig | None = None, client=None, api_key: str | None = None):
        super().__init__(config)
        self._client = client
        self._api_key = api_key or None                # a key saved in the AI settings; else the SDK reads the env
        self.client_injected = client is not None     # provenance: an injected client is never a trusted provider path

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:                  # the SDK is an optional dependency of the live runtime
                raise ProviderFailure("anthropic SDK not installed (pip install anthropic)", kind="SDK_MISSING") from exc
            # base_url pinned: ANTHROPIC_BASE_URL never redirects a trusted adapter
            extra = {"api_key": self._api_key} if self._api_key else {}
            self._client = anthropic.Anthropic(base_url=self.endpoint, timeout=self.config.timeout_seconds,
                                               max_retries=self.config.max_retries, **extra)
        return self._client

    def complete(self, request: AgentRequest) -> ProviderResult:
        import anthropic
        client = self._get_client()
        import os

        model = request.model or self.model
        output_config = {"format": {"type": "json_schema", "schema": wire_schema(request.schema)}}
        effort = os.getenv("CDF_AI_EFFORT", "").strip()
        if effort:
            output_config["effort"] = effort
        attempts = 0
        while True:
            attempts += 1
            try:
                raw = client.messages.with_raw_response.create(
                    model=model,
                    max_tokens=_budget(request.max_tokens),
                    system=request.system,
                    messages=[{"role": "user", "content": request.user_text}],
                    output_config=output_config,
                )
                response = raw.parse()
                request_id = (raw.headers.get("request-id") if getattr(raw, "headers", None) else None) \
                    or getattr(response, "_request_id", None)
                break
            except anthropic.AuthenticationError as exc:
                raise ProviderFailure(f"authentication failed {rejection_reason(exc)}", kind="AUTHENTICATION") from exc
            except anthropic.PermissionDeniedError as exc:
                raise ProviderFailure(f"permission denied {rejection_reason(exc)}", kind="PERMISSION") from exc
            except anthropic.NotFoundError as exc:
                raise ProviderFailure(f"model or endpoint not found {rejection_reason(exc)}", kind="NOT_FOUND") from exc
            except anthropic.BadRequestError as exc:
                raise ProviderFailure(f"bad request {rejection_reason(exc)}", kind="BAD_REQUEST") from exc
            except anthropic.RateLimitError as exc:
                if attempts >= self.config.max_retries + 1:
                    raise ProviderFailure("rate limited after bounded retries", retryable=True, kind="RATE_LIMIT") from exc
                wait = min(MAX_RATE_LIMIT_WAIT, float(exc.response.headers.get("retry-after", "5") or 5))
                time.sleep(wait)
            except anthropic.APIStatusError as exc:
                raise ProviderFailure(f"API error {exc.status_code} {rejection_reason(exc)}",
                                      retryable=exc.status_code >= 500, kind="API_STATUS") from exc
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
