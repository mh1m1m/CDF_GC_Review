"""Explicit executor selection; an unavailable live executor never becomes a mock."""

import os
import shutil
from ..agents.providers.base import ProviderConfig, ProviderFailure, DEFAULT_MODEL


def select_executor(executor, *, timeout):
    if executor == "deterministic":
        return None
    if executor == "mock":
        from ..agents.providers.mock_adapter import MockAdapter
        from .synthetic import mock_script

        return MockAdapter(script=mock_script())
    if executor in ("codex-cli", "claude-cli"):
        from ..agents.providers.cli_adapter import SupervisedCLIAdapter

        if os.getenv("CDF_ENABLE_SUPERVISED_CLI") != "1":
            raise ProviderFailure(
                "Supervised CLI disabled", kind="EXECUTION_POLICY_BLOCKED"
            )
        if not shutil.which("codex" if executor == "codex-cli" else "claude"):
            raise ProviderFailure("Requested CLI unavailable", kind="CLI_MISSING")
        return SupervisedCLIAdapter(
            ProviderConfig(
                provider=executor,
                model=os.getenv(
                    "CDF_CLI_MODEL", "CLI_CONFIGURED_MODEL_NOT_INDEPENDENTLY_ATTESTED"
                ),
                timeout_seconds=timeout,
                max_retries=0,
            ),
            executor,
        )
    if os.getenv("CDF_ENABLE_PROVIDER_API") != "1":
        raise ProviderFailure(
            "Provider API policy disabled", kind="EXECUTION_POLICY_BLOCKED"
        )
    if executor == "openai":
        from ..agents.providers.openai_adapter import OpenAIAdapter

        if not os.getenv("OPENAI_API_KEY"):
            raise ProviderFailure(
                "OpenAI API credential unavailable", kind="CREDENTIAL_UNAVAILABLE"
            )
        model = os.getenv("CDF_OPENAI_MODEL") or os.getenv("CDF_AI_MODEL")
        if not model:
            raise ProviderFailure(
                "OpenAI model must be configured", kind="MODEL_REQUIRED"
            )
        return OpenAIAdapter(
            ProviderConfig(
                provider="openai", model=model, timeout_seconds=timeout, max_retries=0
            )
        )
    if executor == "anthropic":
        from ..agents.providers.anthropic_adapter import AnthropicAdapter

        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise ProviderFailure(
                "Anthropic API credential unavailable", kind="CREDENTIAL_UNAVAILABLE"
            )
        return AnthropicAdapter(
            ProviderConfig(
                provider="anthropic",
                model=os.getenv("CDF_AI_MODEL", DEFAULT_MODEL),
                timeout_seconds=timeout,
                max_retries=0,
            )
        )
    raise ProviderFailure("Unsupported executor", kind="UNSUPPORTED_EXECUTOR")


def readiness():
    return {
        "codex-cli": {
            "installed": bool(shutil.which("codex")),
            "policy_enabled": os.getenv("CDF_ENABLE_SUPERVISED_CLI") == "1",
        },
        "claude-cli": {
            "installed": bool(shutil.which("claude")),
            "policy_enabled": os.getenv("CDF_ENABLE_SUPERVISED_CLI") == "1",
        },
        "openai": {
            "credential_configured": bool(os.getenv("OPENAI_API_KEY")),
            "policy_enabled": os.getenv("CDF_ENABLE_PROVIDER_API") == "1",
        },
        "anthropic": {
            "credential_configured": bool(
                os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
            ),
            "policy_enabled": os.getenv("CDF_ENABLE_PROVIDER_API") == "1",
        },
    }
