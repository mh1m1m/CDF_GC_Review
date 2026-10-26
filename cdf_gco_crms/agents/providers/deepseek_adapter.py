"""DeepSeek chat completions (LIVE mode). DeepSeek offers JSON mode rather than strict JSON schemas, so the role
schema goes into the instructions and the runner validates the reply against it. Endpoint pinned in the provider
registry; key from the AI settings or ``DEEPSEEK_API_KEY``. Note for the owner: DeepSeek processes requests on
servers in the People's Republic of China."""
from __future__ import annotations

from ..provenance import official_endpoint
from .chat_completions import ChatCompletionsAdapter

DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"


class DeepSeekAdapter(ChatCompletionsAdapter):
    name = "deepseek"
    endpoint = official_endpoint("deepseek")
    default_model = DEFAULT_DEEPSEEK_MODEL
    env_key = "DEEPSEEK_API_KEY"
    schema_mode = "json_object"
