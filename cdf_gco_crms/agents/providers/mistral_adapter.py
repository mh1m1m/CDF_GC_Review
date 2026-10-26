"""Mistral chat completions (LIVE mode) over HTTPS, with a JSON-schema response format.

The endpoint is pinned (no base-URL override from the environment). The key is read from ``MISTRAL_API_KEY``, or
from the variable named in ``CDF_MISTRAL_KEY_VAR`` when the owner stored it under another name; it is used only if
it has the shape of a Mistral key, so a mistyped name never sends another secret. Each ``complete`` is one fresh
request: the role's system text, the payload as the single user turn, and the role schema as a strict response
format; the runner still validates every reply against the full schema.

The API's error text is never stored: a rejection becomes a fixed reason code plus the provider's request id.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from ..contracts import MODE_LIVE, AgentRequest, TokenUsage
from ..provenance import official_endpoint
from .anthropic_adapter import wire_schema
from .base import ProviderAdapter, ProviderConfig, ProviderFailure, ProviderResult

DEFAULT_MISTRAL_MODEL = "mistral-large-latest"
MAX_RATE_LIMIT_WAITS = 4
MAX_RATE_LIMIT_WAIT = 20.0
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
# A key is one token of printable ASCII. Pasting often adds quotes, spaces or a "Bearer " prefix: those are removed.
_KEY_SHAPE = re.compile(r"^[!-~]{16,256}$")
# Under an owner-chosen variable name, values that are plainly another kind of secret are never sent.
_OTHER_SECRET_MARKS = ("://", "@", "sk-ant-", "sb_", "eyJ")
_REQUEST_ID_HEADERS = ("x-request-id", "mistral-correlation-id", "x-kong-request-id")
_REASONS = (
    ("CREDIT_BALANCE_TOO_LOW", ("credit", "insufficient")),
    ("BILLING", ("billing", "payment", "subscription", "plan")),
    ("PROMPT_TOO_LONG", ("too long", "too many tokens", "context length", "maximum context")),
    ("OUTPUT_SCHEMA_REJECTED", ("schema", "response_format", "json")),
    ("MAX_TOKENS_REJECTED", ("max_tokens",)),
    ("MODEL_REJECTED", ("model",)),
)


def _clean(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def mistral_credential() -> str | None:
    """The Mistral API key from the environment, or None. Never logged or returned anywhere else."""
    value = _clean(os.getenv("MISTRAL_API_KEY") or "")
    if not value:
        name = (os.getenv("CDF_MISTRAL_KEY_VAR") or "").strip()
        if not name or not _ENV_NAME.match(name):
            return None
        value = _clean(os.getenv(name) or "")
        if any(mark in value for mark in _OTHER_SECRET_MARKS):
            return None
    return value if _KEY_SHAPE.match(value) else None


def _reason(status: int, raw: bytes, headers) -> str:
    try:
        body = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        body = {}
    message = ""
    if isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        message = str(inner.get("message") or inner.get("detail") or inner.get("type") or "")
    message = message.lower()
    code = next((name for name, needles in _REASONS if any(n in message for n in needles)), "UNCLASSIFIED")
    request_id = _request_id(headers)
    return f"HTTP {status} [{code}]" + (f" request_id={request_id}" if request_id else "")


def _request_id(headers) -> str | None:
    for name in _REQUEST_ID_HEADERS:
        value = headers.get(name) if headers is not None else None
        if value and re.fullmatch(r"[A-Za-z0-9_.:-]{6,128}", str(value)):
            return str(value)
    return None


class MistralAdapter(ProviderAdapter):
    name = "mistral"
    mode = MODE_LIVE
    endpoint = official_endpoint("mistral")

    def __init__(self, config: ProviderConfig | None = None, transport=None):
        super().__init__(config or ProviderConfig(provider="mistral", model=DEFAULT_MISTRAL_MODEL))
        self._transport = transport
        self.client_injected = transport is not None   # an injected transport is never a trusted provider path

    def _post(self, body: dict) -> tuple[int, bytes, dict]:
        if self._transport is not None:
            return self._transport(body)
        key = mistral_credential()
        if not key:
            raise ProviderFailure("no Mistral credential (MISTRAL_API_KEY or CDF_MISTRAL_KEY_VAR)",
                                  kind="AUTHENTICATION")
        # The URL is the fixed https endpoint from the provider registry.
        request = urllib.request.Request(  # nosec B310
            self.endpoint + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:  # nosec B310
                return response.status, response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read() or b"", dict(exc.headers.items()) if exc.headers else {}
        except TimeoutError as exc:
            raise ProviderFailure("request timed out", retryable=True, kind="TIMEOUT") from exc
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise ProviderFailure("request timed out", retryable=True, kind="TIMEOUT") from exc
            raise ProviderFailure("connection error", retryable=True, kind="CONNECTION") from exc

    def complete(self, request: AgentRequest) -> ProviderResult:
        body = {
            "model": request.model or self.model,
            "max_tokens": int(request.max_tokens or 4096),
            "messages": [{"role": "system", "content": request.system},
                         {"role": "user", "content": request.user_text}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "cdf_" + str(getattr(request, "role", "role") or "role").lower(),
                "schema": wire_schema(request.schema), "strict": True}},
        }
        waits = 0
        while True:
            status, raw, headers = self._post(body)
            headers = {str(k).lower(): v for k, v in (headers or {}).items()}
            if status == 429 and waits < MAX_RATE_LIMIT_WAITS:
                waits += 1
                try:
                    wait = float(headers.get("retry-after") or 2 * waits)
                except ValueError:
                    wait = 2.0 * waits
                time.sleep(min(MAX_RATE_LIMIT_WAIT, max(1.0, wait)))
                continue
            break
        if status in (401, 403):
            raise ProviderFailure(f"authentication failed {_reason(status, raw, headers)}",
                                  kind="AUTHENTICATION" if status == 401 else "PERMISSION")
        if status == 404:
            raise ProviderFailure(f"model or endpoint not found {_reason(status, raw, headers)}", kind="NOT_FOUND")
        if status == 429:
            raise ProviderFailure(f"rate limited after bounded waits {_reason(status, raw, headers)}",
                                  retryable=True, kind="RATE_LIMIT")
        if status in (400, 422):
            raise ProviderFailure(f"bad request {_reason(status, raw, headers)}", kind="BAD_REQUEST")
        if status != 200:
            raise ProviderFailure(f"API error {_reason(status, raw, headers)}", retryable=status >= 500,
                                  kind="API_STATUS")
        try:
            data = json.loads(raw.decode("utf-8"))
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderFailure("unreadable provider response", kind="INCOMPLETE") from exc
        if isinstance(content, list):                  # content chunks: keep the text parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not data.get("id"):
            raise ProviderFailure("Provider receipt missing", kind="PROVIDER_RECEIPT_MISSING")
        finish = choice.get("finish_reason")
        if finish == "length":
            raise ProviderFailure("reply cut off at max_tokens", kind="INCOMPLETE")
        usage = data.get("usage") or {}
        return ProviderResult(str(content or ""), str(data["id"]), str(data.get("model") or body["model"]),
                              TokenUsage(int(usage.get("prompt_tokens") or 0),
                                         int(usage.get("completion_tokens") or 0)),
                              stop_reason=finish, provider_request_id=_request_id(headers))
