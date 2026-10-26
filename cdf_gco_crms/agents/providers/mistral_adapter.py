"""Mistral chat completions (LIVE mode), with the role schema as a strict JSON response format.

The endpoint is pinned in the provider registry. The key is the one saved in the AI settings, or
``MISTRAL_API_KEY``, or the variable named in ``CDF_MISTRAL_KEY_VAR`` (refused when it plainly holds another kind
of secret). Shared request, rate-limit and error handling: :mod:`.chat_completions`.
"""
from __future__ import annotations

import time  # noqa: F401  (tests patch time.sleep through this module)

from ..provenance import official_endpoint
from .chat_completions import ChatCompletionsAdapter, key_from_env

DEFAULT_MISTRAL_MODEL = "mistral-large-latest"


def mistral_credential() -> str | None:
    """The Mistral API key from the environment, or None. Never logged or returned anywhere else."""
    return key_from_env("MISTRAL_API_KEY", "CDF_MISTRAL_KEY_VAR", foreign_marks=("sk-ant-",))


class MistralAdapter(ChatCompletionsAdapter):
    name = "mistral"
    endpoint = official_endpoint("mistral")
    default_model = DEFAULT_MISTRAL_MODEL
    env_key = "MISTRAL_API_KEY"
    env_key_alias = "CDF_MISTRAL_KEY_VAR"
