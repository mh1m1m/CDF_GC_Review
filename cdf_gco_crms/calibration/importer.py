"""Offline OOXML-to-calibration importer; never exposes document contents via public CI.

The importer is a Python library, not an authenticated upload endpoint.
Call only from a private, authorized execution environment. Institutional
deployment requires separately provisioned identity and source authorization.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys

from .store import CalibrationError, CalibrationStore, ReviewerContext
from .input_safety import check_ooxml_zip

MAX_DOCX_BYTES = 25 * 1024 * 1024


def _valid_docx_path(value: str | Path) -> Path:
    p = Path(value).expanduser()
    if p.is_symlink() or not p.is_file() or p.suffix.lower() != ".docx":
        raise CalibrationError("INVALID_DOCX_INPUT")
    size = p.stat().st_size
    if not (0 < size <= MAX_DOCX_BYTES):
        raise CalibrationError("DOCX_SIZE_OUT_OF_RANGE")
    with p.open("rb") as fp:
        if fp.read(4) != b"PK\x03\x04":
            raise CalibrationError("INVALID_DOCX_PACKAGE_SIGNATURE")
    check_ooxml_zip(p, max_compressed=MAX_DOCX_BYTES)
    return p.resolve(strict=True)


def build_case_from_docx(original_path: str | Path, reviewed_path: str | Path) -> dict:
    """Return an in-memory private comparison; do not log its content."""
    original = _valid_docx_path(original_path)
    reviewed = _valid_docx_path(reviewed_path)
    if original == reviewed:
        raise CalibrationError("SOURCE_VERSIONS_MUST_DIFFER")
    # Existing extractor is the canonical forensic parser. It preserves
    # unmatched observations and never equates an absent comment to withdrawal.
    import tools.mat_dna.ooxml_forensics as forensic
    orig = forensic.extract(original)
    final = forensic.extract(reviewed)
    report = forensic.compare(orig, final)
    original_sha = forensic.sha256_file(original)
    reviewed_sha = forensic.sha256_file(reviewed)
    pair_sha = sha256(bytes.fromhex(original_sha) + bytes.fromhex(reviewed_sha)).hexdigest()
    observations = []
    for m in report["matches"]:
        types = m["change_types"]
        observed = ("REMOVED_FROM_VERSION" if "REMOVED_FROM_VERSION" in types
                    else "ADDED_IN_REVIEW" if "ADDED_IN_REVIEW" in types
                    else "EMPTIED_IN_PLACE" if "EMPTIED_IN_PLACE" in types
                    else "KEEP_UNCHANGED" if "KEEP_UNCHANGED" in types
                    else "REVISED")
        observations.append({
            "observation_id": m["observation_id"],
            "original_text": m["original_text"],
            "reviewed_text": m["reviewed_text"],
            "observed_change": observed,
            "change_types": types,
            "document_article": m["document_article"],
            "document_anchor": m["document_anchor"],
            "matching_method": m["matching_method"],
            "matching_confidence": m["matching_confidence"],
            "manual_review": m["manual_review"],
            "provenance": m["provenance"],
            "attribution_status": m["attribution_status"],
            "primary_type_original": m["original_class"] or None,
            "primary_type_reviewed": m["reviewed_class"] or None,
            "material_categories": [],
            "documented_withdrawal": False,
        })
    return {
        "source_pair_sha256": pair_sha,
        "original_sha256": original_sha,
        "reviewed_sha256": reviewed_sha,
        "original_comment_objects": len(orig.comments),
        "reviewed_comment_objects": len(final.comments),
        "reviewed_nonempty_comments": sum(bool((c.text or "").strip()) for c in final.comments),
        "observations": observations,
        "match_statistics": report["statistics"],
        "manual_review_queue": [m["observation_id"] for m in observations if m["manual_review"]],
        "authorship_verification": "NOT_ESTABLISHED_FROM_SHARED_AUTHOR",
    }


def import_private_pair(
    store: CalibrationStore, case_id: str, original_path: str | Path,
    reviewed_path: str | Path, reviewer: ReviewerContext,
) -> dict:
    reviewer.require("CALIBRATION_ADMIN")
    result = build_case_from_docx(original_path, reviewed_path)
    receipt = store.import_case(case_id, result["source_pair_sha256"], result["observations"], reviewer)
    # Caller must protect in-memory output, input documents and database.
    return {
        "case_id": case_id,
        "evidence_hash": receipt,
        "source_pair_sha256": result["source_pair_sha256"],
        "observations": len(result["observations"]),
        "manual_review": len(result["manual_review_queue"]),
        "institutional_authorization": "NOT_ESTABLISHED_BY_IMPORT",
    }
