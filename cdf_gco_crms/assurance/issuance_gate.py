"""Fail-closed CLI export policy for v7.12.

This guard deliberately does NOT certify review completion or institutional approval.
Until a cryptographically verified, state-bound challenge/authorization service exists,
production CLI commands may render only explicitly requested INTERNAL DRAFT artefacts.

Calling the lower-level workbook/Word writers directly is outside this CLI boundary;
the future centrally enforced issuance service must protect every official exporter.
"""
from __future__ import annotations

from pathlib import Path

DRAFT_PREFIX = "INTERNAL_DRAFT__"
DRAFT_CLASSIFICATION = "INTERNAL_DRAFT_NOT_APPROVED"


class IssuanceDenied(PermissionError):
    """An official issue was attempted without a verified institutional release gate."""


def draft_path(path: str | Path) -> Path:
    """Label intermediate files and review copies by filename; never imply approval."""
    p = Path(path)
    if p.name.startswith(DRAFT_PREFIX):
        return p
    return p.with_name(DRAFT_PREFIX + p.name)


def authorize_cli_export(path: str | Path, *, internal_draft: bool = False,
                         issuance_requested: bool = False) -> Path:
    """Permit explicitly identified internal drafts, never a production issue.

    No caller-supplied bool, JSON challenge record, or synthetic signing key can
    authorize issue. Approval will require a future, audited centralized service
    that recomputes challenge evidence and validates institution-managed signatures.
    """
    if issuance_requested:
        raise IssuanceDenied(
            "OFFICIAL_ISSUANCE_DISABLED: independent AI review, state-bound challenge "
            "and institutional release authorization are not implemented."
        )
    if not internal_draft:
        raise IssuanceDenied(
            "RELEASE_GATE_REQUIRED: use --internal-draft for a non-issuable working copy; "
            "official issuance is not available in this build."
        )
    return draft_path(path)
