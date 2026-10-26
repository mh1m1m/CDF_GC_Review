"""OpenAI-style chat completions over HTTPS, shared by Mistral, DeepSeek and xAI (Grok).

Each subclass pins its endpoint in the provider registry (``provenance.LIVE_PROVIDERS``); no base-URL override
from the environment reaches it. The key is passed in by the caller (a key saved in the AI settings) or read from
the subclass's environment variable; it is never logged or stored by this module.

Each ``complete`` is one fresh request: the role's system text, the payload as the single user turn, and the role
schema as the response format (a strict JSON schema where the service supports it, otherwise JSON mode with the
schema in the instructions). The runner validates every reply against the full schema either way.

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
from .anthropic_adapter import wire_schema
from .base import ProviderAdapter, ProviderConfig, ProviderFailure, ProviderResult

MAX_RATE_LIMIT_WAITS = 4
MAX_RATE_LIMIT_WAIT = 20.0
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
# A key is one token of printable ASCII. Pasting often adds quotes, spaces or a "Bearer " prefix: those are removed.
KEY_SHAPE = re.compile(r"^[!-~]{16,512}$")
# Under an owner-chosen variable name, values that are plainly another kind of secret are never sent.
_OTHER_SECRET_MARKS = ("://", "@", "sb_", "eyJ")
_REQUEST_ID_HEADERS = ("x-request-id", "request-id", "mistral-correlation-id", "x-kong-request-id", "x-ds-trace-id")
_REASONS = (
    ("CREDIT_BALANCE_TOO_LOW", ("credit", "insufficient", "balance")),
    ("BILLING", ("billing", "payment", "subscription", "plan", "quota")),
    ("PROMPT_TOO_LONG", ("too long", "too many tokens", "context length", "maximum context")),
    ("OUTPUT_SCHEMA_REJECTED", ("schema", "response_format", "json")),
    ("MAX_TOKENS_REJECTED", ("max_tokens",)),
    ("MODEL_REJECTED", ("model",)),
)


def clean_key(value: str | None) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def key_from_env(variable: str, alias_variable: str | None = None, *, foreign_marks: tuple = ()) -> str | None:
    """A provider key from its own variable, or from the variable named in ``alias_variable``."""
    value = clean_key(os.getenv(variable))
    if not value and alias_variable:
        name = (os.getenv(alias_variable) or "").strip()
        if not name or not _ENV_NAME.match(name):
            return None
        value = clean_key(os.getenv(name))
        if any(mark in value for mark in _OTHER_SECRET_MARKS + tuple(foreign_marks)):
            return None
    return value if KEY_SHAPE.match(value) else None


def reason(status: int, raw: bytes, headers) -> str:
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
    request_id = request_id_of(headers)
    return f"HTTP {status} [{code}]" + (f" request_id={request_id}" if request_id else "")


def request_id_of(headers) -> str | None:
    for name in _REQUEST_ID_HEADERS:
        value = headers.get(name) if headers is not None else None
        if value and re.fullmatch(r"[A-Za-z0-9_.:-]{6,128}", str(value)):
            return str(value)
    return None


class ChatCompletionsAdapter(ProviderAdapter):
    """Base class; a subclass sets ``name``, ``endpoint``, ``default_model`` and ``env_key``."""
    name = "chat-completions"
    mode = MODE_LIVE
    endpoint = ""
    default_model = ""
    env_key = ""
    env_key_alias: str | None = None
    foreign_key_marks: tuple = ("sk-ant-",)
    schema_mode = "json_schema"          # or "json_object": JSON mode, with the schema written into the instructions

    def __init__(self, config: ProviderConfig | None = None, transport=None, api_key: str | None = None):
        super().__init__(config or ProviderConfig(provider=self.name, model=self.default_model))
        self._transport = transport
        self._api_key = clean_key(api_key) or None
        self.client_injected = transport is not None   # an injected transport is never a trusted provider path

    def credential(self) -> str | None:
        if self._api_key:
            return self._api_key if KEY_SHAPE.match(self._api_key) else None
        return key_from_env(self.env_key, self.env_key_alias, foreign_marks=self.foreign_key_marks)

    def _post(self, body: dict) -> tuple[int, bytes, dict]:
        if self._transport is not None:
            return self._transport(body)
        key = self.credential()
        if not key:
            raise ProviderFailure(f"no {self.name} credential", kind="AUTHENTICATION")
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

    def _body(self, request: AgentRequest) -> dict:
        system = request.system
        if self.schema_mode == "json_schema":
            fmt = {"type": "json_schema", "json_schema": {
                "name": "cdf_" + str(getattr(request, "role", "role") or "role").lower(),
                "schema": wire_schema(request.schema), "strict": True}}
        else:
            fmt = {"type": "json_object"}
            system = (system + "\n\nReply with one JSON object only, matching this JSON Schema:\n"
                      + json.dumps(wire_schema(request.schema), ensure_ascii=False))
        return {"model": request.model or self.model, "max_tokens": int(request.max_tokens or 4096),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": request.user_text}],
                "response_format": fmt}

    def complete(self, request: AgentRequest) -> ProviderResult:
        body = self._body(request)
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
            raise ProviderFailure(f"authentication failed {reason(status, raw, headers)}",
                                  kind="AUTHENTICATION" if status == 401 else "PERMISSION")
        if status == 402:
            raise ProviderFailure(f"payment required {reason(status, raw, headers)}", kind="BILLING")
        if status == 404:
            raise ProviderFailure(f"model or endpoint not found {reason(status, raw, headers)}", kind="NOT_FOUND")
        if status == 429:
            raise ProviderFailure(f"rate limited after bounded waits {reason(status, raw, headers)}",
                                  retryable=True, kind="RATE_LIMIT")
        if status in (400, 422):
            raise ProviderFailure(f"bad request {reason(status, raw, headers)}", kind="BAD_REQUEST")
        if status != 200:
            raise ProviderFailure(f"API error {reason(status, raw, headers)}", retryable=status >= 500,
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
        if finish == "model_length":                   # Mistral: the model's context window ran out
            raise ProviderFailure("reply cut off: context window full [PROMPT_TOO_LONG]", kind="INCOMPLETE")
        if finish == "error":                          # Mistral: generation stopped on a server-side error
            raise ProviderFailure("generation stopped with an error", retryable=True, kind="API_STATUS")
        usage = data.get("usage") or {}
        return ProviderResult(str(content or ""), str(data["id"]), str(data.get("model") or body["model"]),
                              TokenUsage(int(usage.get("prompt_tokens") or 0),
                                         int(usage.get("completion_tokens") or 0)),
                              stop_reason=finish, provider_request_id=request_id_of(headers))
