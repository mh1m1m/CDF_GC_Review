"""Mistral as a live provider: request shape, strict JSON schema, rate-limit waits, rejection reasons without the
API's text, the owner-named key, and provenance (an injected transport is never trusted)."""
import json
from types import SimpleNamespace

import pytest

from cdf_gco_crms.agents import provenance as PV
from cdf_gco_crms.agents.contracts import SCHEMAS, ROLE_DRAFTING
from cdf_gco_crms.agents.providers import mistral_adapter as M
from cdf_gco_crms.agents.providers.base import ProviderConfig, ProviderFailure

REPLY = {"observations": [], "gaps_not_drafted": [], "reasoning_summary": "x"}


def _request():
    return SimpleNamespace(role=ROLE_DRAFTING, model=None, max_tokens=8192, system="SYS", user_text="USER",
                           schema=SCHEMAS[ROLE_DRAFTING])


def _ok(body):
    data = {"id": "0123456789abcdef", "model": "mistral-large-2411",
            "choices": [{"message": {"content": json.dumps(REPLY)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7}}
    return 200, json.dumps(data).encode(), {"x-request-id": "req-abc123"}


def test_request_shape_and_result():
    sent = []

    def transport(body):
        sent.append(body)
        return _ok(body)

    result = M.MistralAdapter(ProviderConfig(provider="mistral", model="mistral-large-latest"),
                              transport=transport).complete(_request())
    body = sent[0]
    assert body["model"] == "mistral-large-latest" and body["max_tokens"] == 8192
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["additionalProperties"] is False
    assert json.loads(result.text) == REPLY
    assert result.invocation_id == "0123456789abcdef" and result.provider_request_id == "req-abc123"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 7)


def test_rate_limit_waits_then_succeeds(monkeypatch):
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    replies = [(429, b'{"message":"rate limit"}', {"retry-after": "1"}), None]

    def transport(body):
        reply = replies.pop(0)
        return reply or _ok(body)

    assert json.loads(M.MistralAdapter(transport=transport).complete(_request()).text) == REPLY


def test_rejection_keeps_reason_not_text():
    secret = "Invalid schema SYNTHETIC_TEXT_MUST_NOT_ESCAPE"

    def transport(body):
        return 400, json.dumps({"object": "error", "message": secret}).encode(), {"x-request-id": "req-xyz789"}

    with pytest.raises(ProviderFailure) as error:
        M.MistralAdapter(transport=transport).complete(_request())
    assert error.value.kind == "BAD_REQUEST"
    assert "[OUTPUT_SCHEMA_REJECTED]" in str(error.value) and "req-xyz789" in str(error.value)
    assert "SYNTHETIC_TEXT_MUST_NOT_ESCAPE" not in str(error.value)

    def unauthorised(body):
        return 401, b'{"message":"Unauthorized"}', {}

    with pytest.raises(ProviderFailure) as error:
        M.MistralAdapter(transport=unauthorised).complete(_request())
    assert error.value.kind == "AUTHENTICATION"


@pytest.mark.parametrize("finish,kind", [("length", "INCOMPLETE"), ("model_length", "INCOMPLETE"),
                                         ("error", "API_STATUS")])
def test_cut_off_or_failed_reply_is_a_failure(finish, kind):
    """Mistral's finish reasons (API reference): stop, length, model_length, error, tool_calls."""
    def transport(body):
        status, raw, headers = _ok(body)
        data = json.loads(raw)
        data["choices"][0]["finish_reason"] = finish
        return status, json.dumps(data).encode(), headers

    with pytest.raises(ProviderFailure) as error:
        M.MistralAdapter(transport=transport).complete(_request())
    assert error.value.kind == kind


def test_wire_format_matches_the_api_reference():
    """POST {endpoint}/chat/completions, Bearer auth; response_format.json_schema carries name, schema, strict
    (the SDK's ``schema_definition`` is sent as ``schema``); content may arrive as text chunks or null."""
    assert M.MistralAdapter.endpoint == "https://api.mistral.ai/v1"
    body = M.MistralAdapter(transport=lambda b: _ok(b))._body(_request())
    assert set(body["response_format"]["json_schema"]) == {"name", "schema", "strict"}

    def chunks(b):
        status, raw, headers = _ok(b)
        data = json.loads(raw)
        data["choices"][0]["message"]["content"] = [{"type": "text", "text": json.dumps(REPLY)}]
        return status, json.dumps(data).encode(), headers

    assert json.loads(M.MistralAdapter(transport=chunks).complete(_request()).text) == REPLY


def test_key_under_an_owner_chosen_name(monkeypatch):
    for name in ("MISTRAL_API_KEY", "CDF_MISTRAL_KEY_VAR", "Owner_Mistral", "OTHER_SECRET"):
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)
    assert M.mistral_credential() is None
    monkeypatch.setenv("OTHER_SECRET", "postgresql://user:pw@host/db")
    monkeypatch.setenv("CDF_MISTRAL_KEY_VAR", "OTHER_SECRET")
    assert M.mistral_credential() is None                     # not the shape of a Mistral key: never sent
    monkeypatch.setenv("OTHER_SECRET", "sk-ant-" + "x" * 30)
    assert M.mistral_credential() is None                     # another provider's key is never sent to Mistral
    monkeypatch.setenv("Owner_Mistral", "A" * 32)
    monkeypatch.setenv("CDF_MISTRAL_KEY_VAR", "Owner_Mistral")
    assert M.mistral_credential() == "A" * 32
    # as pasted into a settings form: surrounding spaces, quotes, a "Bearer " prefix, a trailing newline
    for pasted in ("  " + "B" * 32 + "\n", '"' + "B" * 32 + '"', "Bearer " + "B" * 32, "'" + "B" * 32 + "'"):
        monkeypatch.setenv("MISTRAL_API_KEY", pasted)
        assert M.mistral_credential() == "B" * 32
    monkeypatch.setenv("MISTRAL_API_KEY", "Ab1-_.xyz" * 4)       # newer key formats with punctuation
    assert M.mistral_credential() == "Ab1-_.xyz" * 4
    monkeypatch.setenv("MISTRAL_API_KEY", "two words " * 4)
    assert M.mistral_credential() is None


def test_provenance_and_executor_selection(monkeypatch):
    from cdf_gco_crms.execution.providers import select_executor

    assert PV.classify_adapter(M.MistralAdapter(transport=lambda body: _ok(body))) == \
        PV.SOURCE_PROVIDER_API_UNTRUSTED
    monkeypatch.setenv("CDF_ENABLE_PROVIDER_API", "1")
    monkeypatch.setenv("MISTRAL_API_KEY", "B" * 32)
    monkeypatch.setenv("CDF_AI_DATA_AUTHORIZATION", "INSTITUTIONAL_AUTHORIZED:test")
    adapter = select_executor("mistral", timeout=5)
    assert adapter.config.provider == "mistral" and adapter.endpoint == "https://api.mistral.ai/v1"
    assert adapter.config.institutional_data_authorized
    assert PV.classify_adapter(adapter) == PV.SOURCE_PROVIDER_API
    monkeypatch.delenv("MISTRAL_API_KEY")
    with pytest.raises(ProviderFailure) as error:
        select_executor("mistral", timeout=5)
    assert error.value.kind == "CREDENTIAL_UNAVAILABLE"


def test_quickstart_errors_401_402_429(monkeypatch):
    """Mistral's quickstart lists 401 (key wrong or missing), 402 (no payment method) and 429 (rate limit)."""
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    for status, kind in ((401, "AUTHENTICATION"), (402, "BILLING"), (429, "RATE_LIMIT")):
        def transport(body, status=status):
            return status, b'{"message": "x"}', {}
        with pytest.raises(ProviderFailure) as error:
            M.MistralAdapter(transport=transport).complete(_request())
        assert error.value.kind == kind
