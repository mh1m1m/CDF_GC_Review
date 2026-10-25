"""Explicit executor selection; an unavailable live executor never becomes a mock."""

import os
import re
import shutil
from ..agents.providers.base import DATA_SYNTHETIC_ONLY, DEFAULT_MODEL, ProviderConfig, ProviderFailure

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def anthropic_credential_configured():
    """True when the Anthropic SDK will find a credential.

    A host may store the key under a name of the owner's choosing; ``CDF_ANTHROPIC_KEY_VAR`` names that variable.
    Its value is copied to ``ANTHROPIC_API_KEY`` for this process only if it has the shape of an Anthropic API key,
    so a mistyped name can never send another secret (a database URL, say) to the provider.
    """
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return True
    name = (os.getenv("CDF_ANTHROPIC_KEY_VAR") or "").strip()
    if not name or not _ENV_NAME.match(name):
        return False
    value = (os.getenv(name) or "").strip()
    if not value.startswith("sk-ant-"):
        return False
    os.environ["ANTHROPIC_API_KEY"] = value
    return True


def select_executor(executor, *, timeout):
    if executor == "deterministic":
        return None
    if executor == "mock":
        from ..agents.providers.mock_adapter import MockAdapter
        from .synthetic import mock_script

        # Explicit server-only synthetic fault injection; never a live executor substitute.
        fail_role=os.getenv('CDF_SYNTHETIC_FAIL_ROLE') if os.getenv('CDF_ENABLE_SYNTHETIC_FAULTS')=='1' else None
        return MockAdapter(script=mock_script(),fail_roles={fail_role} if fail_role else None)
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

        if not anthropic_credential_configured():
            raise ProviderFailure(
                "Anthropic API credential unavailable", kind="CREDENTIAL_UNAVAILABLE"
            )
        return AnthropicAdapter(
            ProviderConfig(
                provider="anthropic",
                model=os.getenv("CDF_AI_MODEL", DEFAULT_MODEL),
                timeout_seconds=timeout,
                max_retries=int(os.getenv("CDF_AI_MAX_RETRIES", "0") or 0),
                # The data-handling guard (agents/security.py) admits non-synthetic content only under an explicit
                # INSTITUTIONAL_AUTHORIZED:<reference> set by the deployment owner; unset stays SYNTHETIC_ONLY.
                data_authorization=os.getenv("CDF_AI_DATA_AUTHORIZATION") or DATA_SYNTHETIC_ONLY,
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
            "credential_configured": anthropic_credential_configured(),
            "policy_enabled": os.getenv("CDF_ENABLE_PROVIDER_API") == "1",
        },
    }
