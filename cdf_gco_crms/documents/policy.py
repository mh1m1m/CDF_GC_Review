"""Deployment policy for uploaded documents under review.

Uploads exist only when the deployment owner sets ``CDF_DOCUMENT_UPLOADS=PUBLIC``. A review of an uploaded document
lives in a case whose id starts with ``UPL-``; the fictional demo cases keep ``SYN-``. Each check that used to accept
only ``SYN-`` accepts ``UPL-`` through :func:`is_uploaded_case`, and only while uploads are on, so turning the switch
off makes every uploaded case inaccessible again rather than silently treating it as synthetic.

Sending an uploaded document to a model provider additionally needs ``CDF_AI_DATA_AUTHORIZATION`` set to
``INSTITUTIONAL_AUTHORIZED:<reference>`` (the engine's existing data-handling guard, ``agents/security.py``). The
content keeps its true label (``INSTITUTIONAL_CONTENT``); it is never relabelled synthetic.
"""
from __future__ import annotations

import os

UPLOAD_CASE_PREFIX = "UPL-"


def uploads_public() -> bool:
    return os.getenv("CDF_DOCUMENT_UPLOADS", "") == "PUBLIC"


def is_uploaded_case(case_id) -> bool:
    return uploads_public() and str(case_id or "").startswith(UPLOAD_CASE_PREFIX)


def allowed_case_prefixes() -> tuple[str, ...]:
    return ("SYN-", UPLOAD_CASE_PREFIX) if uploads_public() else ("SYN-",)


def site_identity() -> str:
    """``CDF`` when the owner has branded this deployment (exports then carry the institution's wordmark)."""
    return os.getenv("CDF_SITE_IDENTITY", "") or os.getenv("VITE_SITE_IDENTITY", "")
