"""Live multi-agent runtime (v7.12): provider adapters, isolated role execution, orchestration.

Deterministic institutional safeguards (authorisation, state transitions, evidence integrity, signatures,
history, serialisation) stay in ``assurance`` and ``release``; this package adds AI agents for the analytical
and interpretive roles and binds their results to those safeguards. A provider failure never approves anything.
"""
from .contracts import (  # noqa: F401
    MODE_CACHED, MODE_DETERMINISTIC, MODE_LIVE, MODE_MOCK, ROLES, SCHEMAS, AgentRequest, AgentResponse,
)
from .providers import MockAdapter, ProviderAdapter, ProviderConfig, ProviderFailure, provider_from_env  # noqa: F401
from .runner import AgentRunner  # noqa: F401
from .tracing import TraceWriter  # noqa: F401
