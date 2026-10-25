"""What the Anthropic adapter sends: a structured-output schema the API accepts, and room for thinking.

No network: a fake client records the request. The full role schema stays the contract the runner enforces.
"""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

from cdf_gco_crms.agents.contracts import ROLE_DRAFTING, AgentRequest, SCHEMAS  # noqa: E402
from cdf_gco_crms.agents.providers.anthropic_adapter import (  # noqa: E402
    MAX_NONSTREAMING_TOKENS, MIN_MAX_TOKENS, AnthropicAdapter, wire_schema,
)
from cdf_gco_crms.agents.providers.base import ProviderConfig  # noqa: E402

UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength",
               "pattern", "minItems", "maxItems", "uniqueItems"}


class _Raw:
    def __init__(self, text):
        self.headers = {"request-id": "req_test"}
        self._text = text

    def parse(self):
        return SimpleNamespace(id="msg_test", model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=self._text)])


class _Client:
    def __init__(self, text="{}"):
        self.calls = []
        self.text = text
        self.messages = SimpleNamespace(with_raw_response=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _Raw(self.text)


def _walk(node, found, path="$"):
    if isinstance(node, dict):
        if (node.get("type") == "object" or "properties" in node) and node.get("additionalProperties") is not False:
            found.append(path + " open object")
        for key, value in node.items():
            if key in UNSUPPORTED:
                found.append(f"{path}.{key}")
            _walk(value, found, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _walk(value, found, f"{path}[{i}]")


@pytest.mark.parametrize("role", sorted(SCHEMAS))
def test_every_role_schema_is_sent_in_the_supported_subset(role):
    original = json.dumps(SCHEMAS[role], sort_keys=True)
    found = []
    _walk(wire_schema(SCHEMAS[role]), found)
    assert found == []
    assert json.dumps(SCHEMAS[role], sort_keys=True) == original          # the contract itself is untouched


def test_request_shape_and_budget(monkeypatch):
    monkeypatch.delenv("CDF_AI_EFFORT", raising=False)
    monkeypatch.delenv("CDF_AI_MIN_MAX_TOKENS", raising=False)
    client = _Client('{"ok": true}')
    adapter = AnthropicAdapter(ProviderConfig(provider="anthropic"), client=client)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"},
                                               "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
              "required": ["ok"]}
    request = AgentRequest(role=ROLE_DRAFTING, system="s", payload={"a": 1}, schema=schema, agent_id="A", max_tokens=2048)
    adapter.complete(request)
    sent = client.calls[0]
    assert sent["max_tokens"] == MIN_MAX_TOKENS                            # thinking counts against max_tokens
    fmt = sent["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert "minimum" not in fmt["schema"]["properties"]["confidence"]
    assert "effort" not in sent["output_config"]
    monkeypatch.setenv("CDF_AI_EFFORT", "high")
    adapter.complete(AgentRequest(role=ROLE_DRAFTING, system="s", payload={}, schema=schema, agent_id="A", max_tokens=90000))
    assert client.calls[1]["output_config"]["effort"] == "high"
    assert client.calls[1]["max_tokens"] == MAX_NONSTREAMING_TOKENS        # stays a non-streaming request


def test_runner_still_enforces_the_full_schema():
    from cdf_gco_crms.agents import AgentRunner, TraceWriter

    schema = {"type": "object", "properties": {"confidence": {"type": "number", "minimum": 0, "maximum": 1}},
              "required": ["confidence"], "additionalProperties": False}
    adapter = AnthropicAdapter(ProviderConfig(provider="anthropic"), client=_Client('{"confidence": 1.7}'))
    response = AgentRunner(adapter, TraceWriter(), max_attempts=1).run(ROLE_DRAFTING, "s", {"label": "SYNTHETIC_TEST_CASE"},
                                                                       schema=schema)
    assert not response.ok and response.schema_errors


def test_key_under_an_owner_chosen_name(monkeypatch):
    """CDF_ANTHROPIC_KEY_VAR names the variable holding the key; only an Anthropic-shaped value is used."""
    from cdf_gco_crms.execution.providers import anthropic_credential_configured, select_executor

    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CDF_ANTHROPIC_KEY_VAR", "Owner_Key", "OTHER_SECRET"):
        monkeypatch.setenv(name, "x")      # recorded, so teardown removes whatever the code sets
        monkeypatch.delenv(name)
    assert not anthropic_credential_configured()
    # a name pointing at another secret is never forwarded
    monkeypatch.setenv("OTHER_SECRET", "postgresql://user:pw@host/db")
    monkeypatch.setenv("CDF_ANTHROPIC_KEY_VAR", "OTHER_SECRET")
    assert not anthropic_credential_configured() and "ANTHROPIC_API_KEY" not in __import__("os").environ
    monkeypatch.setenv("CDF_ANTHROPIC_KEY_VAR", "bad name; rm")
    assert not anthropic_credential_configured()
    # the owner's own name works
    monkeypatch.setenv("Owner_Key", "sk-ant-api03-test-not-a-real-key")
    monkeypatch.setenv("CDF_ANTHROPIC_KEY_VAR", "Owner_Key")
    monkeypatch.setenv("CDF_ENABLE_PROVIDER_API", "1")
    assert anthropic_credential_configured()
    assert __import__("os").environ["ANTHROPIC_API_KEY"] == "sk-ant-api03-test-not-a-real-key"
    assert select_executor("anthropic", timeout=5).config.provider == "anthropic"
