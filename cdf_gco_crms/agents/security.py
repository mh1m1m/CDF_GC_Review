"""Security controls of the agent runtime (Articles 04, 05, 10).

* Data-handling authorisation: a payload that carries institutional content may leave the process for an
  external provider only under an explicit ``INSTITUTIONAL_AUTHORIZED:<reference>`` authorisation. Synthetic
  payloads (labelled) are always allowed. The check is fail-closed: unlabelled content counts as institutional.
* Sealed-label guard: no payload may carry an evaluation answer or another role's private material.
* Trace sanitisation: credentials and bearer tokens are redacted from anything written to disk.
"""
from __future__ import annotations

import re
from typing import Any

from .contracts import canonical_json
from .providers.base import MODE_LIVE, ProviderAdapter, ProviderConfig

SYNTHETIC_LABELS = ("SYNTHETIC", "SYNTHETIC_TEST_CASE", "SYNTHETIC_REFERENCE_FIXTURE", "SYNTHETIC_NOT_APPROVED",
                    "بيانات تجريبية")
FORBIDDEN_PAYLOAD_KEYS = ("expected", "_sealed", "sealed", "answer_key", "preferred_winner", "private_instructions",
                          "other_role_output", "ground_truth")
_SECRET_RE = re.compile(r"(sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,}|"
                        r"x-api-key\s*[:=]\s*\S+)", re.I)


class DataHandlingViolation(PermissionError):
    """Content that is not cleared for an external provider was about to be transmitted."""


class ContextIsolationViolation(ValueError):
    """A payload carries sealed answers or another role's private material."""


def payload_is_synthetic(payload: dict) -> bool:
    label = str(payload.get("label") or payload.get("data_classification") or "")
    return any(label.upper().startswith(x.upper()) for x in SYNTHETIC_LABELS)


def assert_context_isolated(payload: dict) -> None:
    text = canonical_json(payload).lower()
    for key in FORBIDDEN_PAYLOAD_KEYS:
        if f'"{key}"' in text:
            raise ContextIsolationViolation(f"payload carries forbidden key {key!r}")


def assert_transmission_allowed(payload: dict, adapter: ProviderAdapter | None, config: ProviderConfig | None = None) -> None:
    """Refuse to send institutional content to an external LIVE provider without an explicit authorisation."""
    if adapter is None or adapter.mode != MODE_LIVE:
        return                                      # nothing leaves the process
    cfg = config or adapter.config
    if payload_is_synthetic(payload):
        return
    if not cfg.institutional_data_authorized:
        raise DataHandlingViolation("payload is not labelled synthetic and no INSTITUTIONAL_AUTHORIZED:<reference> "
                                    "data-handling authorisation is configured (CDF_AI_DATA_AUTHORIZATION)")


def sanitize(text: Any) -> str:
    return _SECRET_RE.sub("[REDACTED]", str(text))


def sanitize_record(record: dict) -> dict:
    return {k: (sanitize(v) if isinstance(v, str) else v) for k, v in record.items()}
