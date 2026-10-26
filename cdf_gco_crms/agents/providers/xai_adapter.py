"""xAI Grok chat completions (LIVE mode), with the role schema as a strict JSON response format. Endpoint pinned
in the provider registry; key from the AI settings or ``XAI_API_KEY``."""
from __future__ import annotations

from ..provenance import official_endpoint
from .chat_completions import ChatCompletionsAdapter

DEFAULT_XAI_MODEL = "grok-4"


class XAIAdapter(ChatCompletionsAdapter):
    name = "xai"
    endpoint = official_endpoint("xai")
    default_model = DEFAULT_XAI_MODEL
    env_key = "XAI_API_KEY"
