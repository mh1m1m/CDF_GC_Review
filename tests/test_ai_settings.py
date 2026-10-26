"""AI settings: admins choose the service, model and key; keys are write-only; reviews use the choice."""
import json

import pytest

from cdf_gco_crms.calibration.store import AccessDenied, CalibrationError, CalibrationStore, ReviewerContext
from cdf_gco_crms.interfaces import ai_settings as S

ADMIN = ReviewerContext("SYN-HOSTED-OWNER", frozenset({"CALIBRATION_ADMIN", "CALIBRATION_REVIEWER"}), True)
REVIEWER = ReviewerContext("SYN-HOSTED-OTHER", frozenset({"CALIBRATION_REVIEWER"}), True)
KEY = "Zk3" + "q" * 29


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for name in ("CDF_REVIEW_EXECUTOR", "MISTRAL_API_KEY", "CDF_MISTRAL_KEY_VAR", "DEEPSEEK_API_KEY", "XAI_API_KEY",
                 "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CDF_ANTHROPIC_KEY_VAR"):
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)
    monkeypatch.setenv("CDF_ENABLE_PROVIDER_API", "1")
    S.MemoryKeys._keys.clear()
    return S.AISettings(CalibrationStore(tmp_path / "ai.sqlite"))


def test_only_admins(settings):
    with pytest.raises(AccessDenied):
        settings.status(REVIEWER)
    with pytest.raises(AccessDenied):
        settings.save_key(REVIEWER, "mistral", KEY)


def test_keys_are_write_only_and_logged_without_the_key(settings):
    status = settings.save_key(ADMIN, "mistral", '  "Bearer ' + KEY + '"\n')
    mistral = next(p for p in status["providers"] if p["id"] == "mistral")
    assert mistral["key"]["source"] == "saved" and mistral["key"]["hint"] == "…" + KEY[-4:]
    assert KEY not in json.dumps(status)
    assert settings.key("mistral") == (KEY, "saved")
    log = [dict(r) for r in settings.db.execute("SELECT * FROM ai_settings_log").fetchall()]
    assert log and KEY not in json.dumps(log)
    stored = [dict(r) for r in settings.db.execute("SELECT * FROM ai_settings").fetchall()]
    assert KEY not in json.dumps(stored)
    settings.clear_key(ADMIN, "mistral")
    assert settings.key("mistral") == (None, "none")
    with pytest.raises(CalibrationError):
        settings.save_key(ADMIN, "mistral", "too short")
    with pytest.raises(CalibrationError):
        settings.save_key(ADMIN, "unknown", KEY)


def test_choice_model_and_environment_fallback(settings, monkeypatch):
    assert settings.active() == (None, "none")
    monkeypatch.setenv("CDF_REVIEW_EXECUTOR", "mistral")
    monkeypatch.setenv("MISTRAL_API_KEY", KEY)
    assert settings.active() == ("mistral", "environment")
    assert settings.key("mistral") == (KEY, "environment")
    status = settings.choose(ADMIN, "deepseek", "deepseek-chat")
    assert status["active"] == "deepseek" and status["active_source"] == "settings"
    with pytest.raises(CalibrationError):
        settings.set_model(ADMIN, "xai", "bad model name;")
    settings.set_model(ADMIN, "xai", "grok-4")
    assert settings.model("xai") == "grok-4" and settings.model("mistral") == "mistral-large-latest"


def test_reviews_use_the_chosen_service(settings, monkeypatch):
    from cdf_gco_crms.agents import provenance as PV
    from cdf_gco_crms.agents.providers.base import ProviderFailure

    settings.save_key(ADMIN, "xai", KEY)
    settings.choose(ADMIN, "xai", "grok-4")
    adapter = settings.adapter()
    assert adapter.name == "xai" and adapter.model == "grok-4" and adapter.credential() == KEY
    assert PV.classify_adapter(adapter) == PV.SOURCE_PROVIDER_API
    settings.choose(ADMIN, "deepseek")
    with pytest.raises(ProviderFailure) as error:
        settings.adapter()
    assert error.value.kind == "CREDENTIAL_UNAVAILABLE"
    monkeypatch.setenv("CDF_ENABLE_PROVIDER_API", "0")
    with pytest.raises(ProviderFailure) as error:
        S.build_adapter("xai", "grok-4", KEY)
    assert error.value.kind == "EXECUTION_POLICY_BLOCKED"


def test_connection_test_uses_a_fixed_sample(settings, monkeypatch):
    from cdf_gco_crms.agents.providers import chat_completions as C

    sent = []

    def post(self, body):
        sent.append(body)
        return 200, json.dumps({"id": "abc123", "model": "deepseek-chat",
                                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                                "usage": {}}).encode(), {}

    monkeypatch.setattr(C.ChatCompletionsAdapter, "_post", post)
    settings.save_key(ADMIN, "deepseek", KEY)
    outcome = settings.test(ADMIN, "deepseek")
    assert outcome["ok"] and outcome["model"] == "deepseek-chat"
    assert sent[0]["response_format"] == {"type": "json_object"} and "JSON" in sent[0]["messages"][0]["content"]
    assert '{"ok": true}' in sent[0]["messages"][1]["content"]

    def unauthorised(self, body):
        return 401, b'{"message": "Unauthorized"}', {}

    monkeypatch.setattr(C.ChatCompletionsAdapter, "_post", unauthorised)
    outcome = settings.test(ADMIN, "deepseek")
    assert not outcome["ok"] and outcome["error"].startswith("AUTHENTICATION")


def test_api_round_trip_never_returns_the_key(tmp_path, monkeypatch):
    import importlib
    import sys

    from fastapi.testclient import TestClient

    token = "t" * 40
    monkeypatch.setenv("CDF_CALIBRATION_MODE", "SYNTHETIC_LOCAL_DEV")
    monkeypatch.setenv("CDF_CALIBRATION_DEV_TOKEN", token)
    monkeypatch.setenv("CDF_CALIBRATION_DB", str(tmp_path / "public-demo" / "ai.sqlite"))
    monkeypatch.setenv("CDF_ENABLE_PROVIDER_API", "1")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    S.MemoryKeys._keys.clear()
    sys.modules.pop("apps.api.main", None)
    module = importlib.import_module("apps.api.main")
    auth = {"Authorization": "Bearer " + token}
    try:
        with TestClient(module.app) as client:
            assert client.get("/api/ai/settings").status_code == 401
            state = client.get("/api/ai/settings", headers=auth).json()
            assert {p["id"] for p in state["providers"]} == {"anthropic", "openai", "mistral", "deepseek", "xai"}
            saved = client.put("/api/ai/providers/mistral/key", headers=auth, json={"key": KEY})
            assert saved.status_code == 200 and KEY not in saved.text
            bad = client.put("/api/ai/providers/mistral/key", headers=auth, json={"key": KEY, "extra": KEY})
            assert bad.status_code == 422 and KEY not in bad.text          # validation errors never echo the key
            chosen = client.put("/api/ai/active", headers=auth, json={"provider": "mistral",
                                                                      "model": "mistral-large-latest"}).json()
            assert chosen["active"] == "mistral" and KEY not in json.dumps(chosen)
            assert client.put("/api/ai/providers/nope/key", headers=auth, json={"key": KEY}).status_code == 422
            assert client.delete("/api/ai/providers/mistral/key", headers=auth).json()["providers"][2]["key"][
                "source"] == "none"
    finally:
        module.store.close()
        sys.modules.pop("apps.api.main", None)


def test_find_models_lists_chat_models_and_tries_each(settings, monkeypatch):
    """A Mistral key on a plan without Large: the list comes from GET /models, non-chat models (OCR,
    embeddings) and dated duplicates are skipped, and each remaining model is tried with the fixed sample."""
    from cdf_gco_crms.agents.providers import chat_completions as C
    import cdf_gco_crms.interfaces.ai_settings as module

    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    listing = {"data": [
        {"id": "mistral-large-latest", "capabilities": {"completion_chat": True}},
        {"id": "mistral-large-2411", "capabilities": {"completion_chat": True}},
        {"id": "mistral-small-latest", "capabilities": {"completion_chat": True}},
        {"id": "mistral-ocr-latest", "capabilities": {"completion_chat": False, "ocr": True}},
        {"id": "mistral-embed", "capabilities": {"completion_chat": False}},
        {"id": "open-mistral-7b", "capabilities": {"completion_chat": True}, "deprecation": "2025-03-30"},
    ]}

    def models(self):
        return [
            {"id": m["id"], "chat": m["capabilities"].get("completion_chat"), "deprecated": bool(m.get("deprecation"))}
            for m in listing["data"]]

    def post(self, body):
        if body["model"] == "mistral-large-latest":
            return 403, b'{"message": "upgrade your plan"}', {}
        return 200, json.dumps({"id": "c1", "model": body["model"], "usage": {},
                                "choices": [{"message": {"content": '{"ok": true}'},
                                             "finish_reason": "stop"}]}).encode(), {}

    monkeypatch.setattr(C.ChatCompletionsAdapter, "list_models", models)
    monkeypatch.setattr(C.ChatCompletionsAdapter, "_post", post)
    settings.save_key(ADMIN, "mistral", KEY)
    found = settings.find_models(ADMIN, "mistral")
    tried = {r["model"]: r for r in found["results"]}
    assert set(tried) == {"mistral-large-latest", "mistral-small-latest"} and found["listed"] == 6
    assert not tried["mistral-large-latest"]["ok"] and "[BILLING]" in tried["mistral-large-latest"]["error"]
    assert tried["mistral-small-latest"]["ok"]
    with pytest.raises(AccessDenied):
        settings.find_models(REVIEWER, "mistral")


def test_list_models_reads_the_api_format():
    from cdf_gco_crms.agents.providers.mistral_adapter import MistralAdapter

    def transport(body):
        assert body == {"__list_models__": True}
        return 200, json.dumps({"object": "list", "data": [
            {"id": "mistral-small-latest", "capabilities": {"completion_chat": True}},
            {"id": "mistral-ocr-latest", "capabilities": {"completion_chat": False}}]}).encode(), {}

    assert MistralAdapter(transport=transport).list_models() == [
        {"id": "mistral-small-latest", "chat": True, "deprecated": False},
        {"id": "mistral-ocr-latest", "chat": False, "deprecated": False}]
