"""AI settings for the hosted site: which AI service reviews documents, with which model, and the services' keys.

Five services: Claude (Anthropic), ChatGPT (OpenAI), Mistral, DeepSeek and Grok (xAI). Only a reviewer with
``CALIBRATION_ADMIN`` can read or change the settings.

Keys are write-only. Once saved, a key is never returned by the API; the page shows only where it came from and
its last four characters. In the hosted deployment the key is kept in Supabase Vault (encrypted at rest, outside
the application's tables), reached only through four ``SECURITY DEFINER`` functions in schema ``cdf``
(``supabase/migrations/…_cdf_ai_keys_vault.sql``). Without them (local development on SQLite) a saved key is held
in memory for the life of the process only. A key in the host's environment (``MISTRAL_API_KEY`` and the like)
still works; a saved key takes precedence.

Every change is written to ``ai_settings_log`` (who, when, which service, what kind of change), never the key.

Sending documents to any of these services still needs the owner's data authorisation
(``CDF_AI_DATA_AUTHORIZATION``) and ``CDF_ENABLE_PROVIDER_API=1``; the settings do not bypass either.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from ..agents.providers.base import DATA_SYNTHETIC_ONLY, ProviderConfig, ProviderFailure
from ..agents.providers.chat_completions import KEY_SHAPE, clean_key
from ..calibration.store import AccessDenied, CalibrationError

PROVIDERS: dict[str, dict] = {
    "anthropic": {"label": "Claude (Anthropic)", "default_model": "claude-opus-5-5", "env": "ANTHROPIC_API_KEY",
                  "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
                  "console": "https://console.anthropic.com"},
    "openai": {"label": "ChatGPT (OpenAI)", "default_model": "gpt-5", "env": "OPENAI_API_KEY",
               "models": ["gpt-5", "gpt-5-mini"], "console": "https://platform.openai.com"},
    "mistral": {"label": "Mistral", "default_model": "mistral-large-latest", "env": "MISTRAL_API_KEY",
                "models": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
                "console": "https://console.mistral.ai"},
    "deepseek": {"label": "DeepSeek", "default_model": "deepseek-chat", "env": "DEEPSEEK_API_KEY",
                 "models": ["deepseek-chat", "deepseek-reasoner"], "console": "https://platform.deepseek.com",
                 "note": "PROCESSED_IN_CHINA"},
    "xai": {"label": "Grok (xAI)", "default_model": "grok-4", "env": "XAI_API_KEY",
            "models": ["grok-4"], "console": "https://console.x.ai"},
}
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
ADMIN = "CALIBRATION_ADMIN"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_settings (
  name TEXT PRIMARY KEY, value TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_settings_log (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  provider TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS ai_settings_log_no_update BEFORE UPDATE ON ai_settings_log
  BEGIN SELECT RAISE(ABORT, 'AUDIT_LOG_APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS ai_settings_log_no_delete BEFORE DELETE ON ai_settings_log
  BEGIN SELECT RAISE(ABORT, 'AUDIT_LOG_APPEND_ONLY'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- key storage ------------------------------------------------------------------------------------------------

class VaultKeys:
    """Supabase Vault through the ``ai_key_*`` functions (hosted deployment)."""
    storage = "vault"

    def __init__(self, db):
        self.db = db

    @staticmethod
    def available(db) -> bool:
        try:
            row = db.execute("SELECT to_regprocedure('ai_key_get(text)') IS NOT NULL AS ok").fetchone()
            return bool(row and row["ok"])
        except Exception:                         # noqa: BLE001 - absent functions simply mean "not available"
            return False

    def put(self, provider: str, key: str) -> None:
        self.db.execute("SELECT ai_key_set(?, ?)", (provider, key))

    def get(self, provider: str) -> str | None:
        row = self.db.execute("SELECT ai_key_get(?) AS k", (provider,)).fetchone()
        return row["k"] if row and row["k"] else None

    def clear(self, provider: str) -> None:
        self.db.execute("SELECT ai_key_clear(?)", (provider,))


class MemoryKeys:
    """Local development: keys live in this process only and are gone after a restart."""
    storage = "memory"
    _keys: dict[str, dict[str, str]] = {}
    _lock = threading.Lock()

    def __init__(self, scope: str):
        self.scope = scope

    def put(self, provider, key):
        with self._lock:
            self._keys.setdefault(self.scope, {})[provider] = key

    def get(self, provider):
        with self._lock:
            return self._keys.get(self.scope, {}).get(provider)

    def clear(self, provider):
        with self._lock:
            self._keys.get(self.scope, {}).pop(provider, None)


def _env_key(provider: str) -> str | None:
    if provider == "anthropic":
        from ..execution.providers import anthropic_credential_configured

        if anthropic_credential_configured():
            return clean_key(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")) or None
        return None
    if provider == "mistral":
        from ..agents.providers.mistral_adapter import mistral_credential

        return mistral_credential()
    value = clean_key(os.getenv(PROVIDERS[provider]["env"]))
    return value if KEY_SHAPE.match(value) else None


# -- the settings ---------------------------------------------------------------------------------------------

class AISettings:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.db.executescript(SCHEMA)
        hosted = bool(getattr(store, "hosted", False))
        self.keys = VaultKeys(self.db) if hosted and VaultKeys.available(self.db) else \
            MemoryKeys(str(getattr(store, "path", "")))

    # reads
    def _value(self, name: str) -> str | None:
        row = self.db.execute("SELECT value FROM ai_settings WHERE name=?", (name,)).fetchone()
        return row["value"] if row else None

    def active(self) -> tuple[str | None, str]:
        """(provider, source): the saved choice, else ``CDF_REVIEW_EXECUTOR``, else none."""
        saved = self._value("active_provider")
        if saved in PROVIDERS:
            return saved, "settings"
        env = (os.getenv("CDF_REVIEW_EXECUTOR") or "").strip().lower()
        if env in PROVIDERS:
            return env, "environment"
        return None, "none"

    def model(self, provider: str) -> str:
        if provider == "anthropic":
            env = os.getenv("CDF_AI_MODEL")
        elif provider == "mistral":
            env = os.getenv("CDF_MISTRAL_MODEL")
        elif provider == "openai":
            env = os.getenv("CDF_OPENAI_MODEL")
        else:
            env = None
        return self._value(f"model:{provider}") or env or PROVIDERS[provider]["default_model"]

    def key(self, provider: str) -> tuple[str | None, str]:
        """(key, source) for the runtime; never sent to a browser."""
        saved = self.keys.get(provider)
        if saved:
            return saved, "saved"
        env = _env_key(provider)
        return (env, "environment") if env else (None, "none")

    def status(self, reviewer) -> dict:
        reviewer.require(ADMIN)
        active, source = self.active()
        providers = []
        for pid, spec in PROVIDERS.items():
            key, key_source = self.key(pid)
            providers.append({
                "id": pid, "label": spec["label"], "model": self.model(pid), "default_model": spec["default_model"],
                "models": spec["models"], "console": spec["console"], "note": spec.get("note"),
                "key": {"source": key_source,
                        "hint": ("…" + key[-4:]) if key and key_source == "saved" else None,
                        "saved_at": self._value(f"key_saved_at:{pid}") if key_source == "saved" else None},
                "active": pid == active})
        return {"active": active, "active_source": source, "key_storage": self.keys.storage,
                "provider_api_enabled": os.getenv("CDF_ENABLE_PROVIDER_API") == "1",
                "data_authorized": (os.getenv("CDF_AI_DATA_AUTHORIZATION") or "").startswith(
                    "INSTITUTIONAL_AUTHORIZED:"),
                "providers": providers}

    # writes
    def _put(self, name: str, value: str, actor: str) -> None:
        self.db.execute("INSERT INTO ai_settings (name, value, updated_by, updated_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, "
                        "updated_at=excluded.updated_at", (name, value, actor, _now()))

    def _log(self, actor: str, action: str, provider: str, detail: dict) -> None:
        self.db.execute("INSERT INTO ai_settings_log (at, actor, action, provider, detail) VALUES (?,?,?,?,?)",
                        (_now(), actor, action, provider, json.dumps(detail, ensure_ascii=False)))

    @staticmethod
    def _provider(provider: str) -> str:
        if provider not in PROVIDERS:
            raise CalibrationError("UNKNOWN_AI_PROVIDER")
        return provider

    def choose(self, reviewer, provider: str, model: str | None = None) -> dict:
        """Make ``provider`` the service that reviews documents, optionally with ``model``."""
        reviewer.require(ADMIN)
        provider = self._provider(provider)
        with self.store.transaction():
            if model is not None:
                self._set_model(reviewer, provider, model)
            self._put("active_provider", provider, reviewer.reviewer_id)
            self._log(reviewer.reviewer_id, "CHOOSE_PROVIDER", provider, {"model": self.model(provider)})
        return self.status(reviewer)

    def _set_model(self, reviewer, provider, model):
        model = (model or "").strip()
        if not _MODEL.match(model):
            raise CalibrationError("INVALID_MODEL_NAME")
        self._put(f"model:{provider}", model, reviewer.reviewer_id)
        self._log(reviewer.reviewer_id, "SET_MODEL", provider, {"model": model})

    def set_model(self, reviewer, provider: str, model: str) -> dict:
        reviewer.require(ADMIN)
        provider = self._provider(provider)
        with self.store.transaction():
            self._set_model(reviewer, provider, model)
        return self.status(reviewer)

    def save_key(self, reviewer, provider: str, key: str) -> dict:
        reviewer.require(ADMIN)
        provider = self._provider(provider)
        key = clean_key(key)
        if not KEY_SHAPE.match(key):
            raise CalibrationError("INVALID_API_KEY_FORMAT")
        with self.store.transaction():
            self.keys.put(provider, key)
            self._put(f"key_saved_at:{provider}", _now(), reviewer.reviewer_id)
            self._log(reviewer.reviewer_id, "SAVE_KEY", provider, {"storage": self.keys.storage})
        return self.status(reviewer)

    def clear_key(self, reviewer, provider: str) -> dict:
        reviewer.require(ADMIN)
        provider = self._provider(provider)
        with self.store.transaction():
            self.keys.clear(provider)
            self._log(reviewer.reviewer_id, "CLEAR_KEY", provider, {"storage": self.keys.storage})
        return self.status(reviewer)

    # runtime
    def adapter(self, provider: str | None = None, *, timeout: float | None = None):
        """The adapter the review uses: the chosen service, its model and its key. Raises ProviderFailure."""
        if provider is None:
            provider, _ = self.active()
        if provider is None:
            raise ProviderFailure("no AI service chosen", kind="NO_AI_PROVIDER")
        key, _ = self.key(provider)
        return build_adapter(provider, self.model(provider), key, timeout=timeout)

    def test(self, reviewer, provider: str) -> dict:
        """One tiny request to ``provider`` with a fixed sample text (no documents): does the key work?"""
        reviewer.require(ADMIN)
        provider = self._provider(provider)
        started = time.monotonic()
        try:
            adapter = self.adapter(provider, timeout=60)
            result = adapter.complete(SimpleNamespace(
                role="CONNECTION_TEST", model=None, max_tokens=256,
                system="You check that an API connection works. Reply with JSON only.",
                user_text='Reply with {"ok": true}.',
                schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}))
            ok = json.loads(result.text or "{}").get("ok") is True
            outcome = {"ok": ok, "model": result.model, "error": None if ok else "UNEXPECTED_REPLY"}
        except ProviderFailure as exc:
            outcome = {"ok": False, "model": None, "error": f"{exc.kind}: {exc}"}
        except ValueError:
            outcome = {"ok": False, "model": None, "error": "UNEXPECTED_REPLY"}
        outcome.update(provider=provider, latency_ms=int((time.monotonic() - started) * 1000))
        with self.store.transaction():
            self._log(reviewer.reviewer_id, "TEST_CONNECTION", provider,
                      {"ok": outcome["ok"], "error": outcome["error"]})
        return outcome


def build_adapter(provider: str, model: str, key: str | None, *, timeout: float | None = None):
    """A live adapter for ``provider``. Refused unless the owner enabled provider calls."""
    if os.getenv("CDF_ENABLE_PROVIDER_API") != "1":
        raise ProviderFailure("Provider API policy disabled", kind="EXECUTION_POLICY_BLOCKED")
    if not key:
        raise ProviderFailure(f"no key for {provider}", kind="CREDENTIAL_UNAVAILABLE")
    timeout = float(timeout or os.getenv("CDF_AI_TIMEOUT_SECONDS", "180") or 180)
    config = ProviderConfig(provider=provider, model=model, timeout_seconds=timeout,
                            max_retries=int(os.getenv("CDF_AI_MAX_RETRIES", "0") or 0),
                            data_authorization=os.getenv("CDF_AI_DATA_AUTHORIZATION") or DATA_SYNTHETIC_ONLY)
    if provider == "anthropic":
        from ..agents.providers.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(config, api_key=key)
    if provider == "openai":
        from ..agents.providers.openai_adapter import OpenAIAdapter

        return OpenAIAdapter(config, api_key=key)
    if provider == "mistral":
        from ..agents.providers.mistral_adapter import MistralAdapter

        return MistralAdapter(config, api_key=key)
    if provider == "deepseek":
        from ..agents.providers.deepseek_adapter import DeepSeekAdapter

        return DeepSeekAdapter(config, api_key=key)
    if provider == "xai":
        from ..agents.providers.xai_adapter import XAIAdapter

        return XAIAdapter(config, api_key=key)
    raise ProviderFailure("Unsupported AI service", kind="UNSUPPORTED_EXECUTOR")


__all__ = ["AISettings", "PROVIDERS", "build_adapter", "AccessDenied"]
