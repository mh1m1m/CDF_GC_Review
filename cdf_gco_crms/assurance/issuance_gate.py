"""Fail-closed CLI export policy (PR #2 interface), now backed by the central release gate.

PR #2 (fix/v712-fail-closed-cli) introduced this interface as an interim control that disabled every official
issue. The permanent architecture lives in ``cdf_gco_crms.release.authorization_gate``; this module keeps the
PR #2 names so that its callers and tests remain valid, and routes every decision through that gate:

  * an official issue is permitted only with an :class:`Authorization` whose ``ok`` is True;
  * ``issuance_requested`` (``--issue``) without such an authorisation is refused — a flag is never an approval;
  * an internal draft is permitted only when explicitly requested, and is always classified in its file name.
"""
from __future__ import annotations

from pathlib import Path

from ..release.authorization_gate import (
    DRAFT_CLASSIFICATION, WORKING_COPY_PREFIX, Authorization, is_working_copy_name, working_copy_name,
)

DRAFT_PREFIX = WORKING_COPY_PREFIX

__all__ = ["DRAFT_PREFIX", "DRAFT_CLASSIFICATION", "IssuanceDenied", "draft_path", "authorize_cli_export",
           "is_working_copy_name"]


class IssuanceDenied(PermissionError):
    """An official issue was attempted without a verified release authorisation."""


def draft_path(path: str | Path) -> Path:
    """Label intermediate files and review copies by file name; never imply approval."""
    return working_copy_name(path)


def authorize_cli_export(path: str | Path, *, internal_draft: bool = False, issuance_requested: bool = False,
                         authorization: Authorization | None = None) -> Path:
    """Return the path a CLI export may write to, or raise :class:`IssuanceDenied`.

    ``authorization`` is the result of ``authorization_gate.authorize(state)`` for the exact content being
    written. Without a passing authorisation no official file is written, whatever flags the caller supplies.
    """
    authorized = bool(authorization is not None and authorization.ok)
    if issuance_requested and not authorized:
        raise IssuanceDenied("OFFICIAL_ISSUANCE_NOT_AUTHORIZED: --issue needs a CLEAR, state-bound review record and a "
                             "verified reviewer decision chain; a caller flag is not an authorisation (19A.9)")
    if authorized:
        return Path(path)
    if not internal_draft:
        raise IssuanceDenied("RELEASE_GATE_REQUIRED: no release authorisation for this content; use --internal-draft "
                             f"for a non-issuable {DRAFT_CLASSIFICATION} copy")
    return draft_path(path)
