"""Document-backed reference verification: a quoted passage must occur in its source file.

Ported from the earlier v7.12 batch (reference_verify.py) without its
container paths and PyMuPDF dependency. PDF text comes from ``pdftotext``
(poppler) when it is on PATH, otherwise from ``pypdf``; DOCX text from
python-docx. Verification is page-level when a page is given.

What a positive result means, and only that: the normalised excerpt occurs in
the extracted text of the source (verdict TEXT_VERIFIED_ONLY). It is never an
approval claim: ``approval_supported`` stays False unless the citation carries
an explicit approving body and decision reference *and* the source register
already records APPROVED_CURRENT; ``applicability_verified`` is never derived
from the text. No authority is inferred from a file name. Image-only sources
return IMAGE_ONLY_SOURCE_REQUIRES_VISUAL_VERIFICATION.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from ..references.textnorm import lam_alef_insensitive, repair_ligatures

APPROVALS = frozenset({
    "APPROVED_CURRENT", "APPROVED_SUPERSEDED", "PROPOSED_NOT_APPROVED", "DRAFT_UNDETERMINED",
    "NOT_SUPPLIED", "EXTERNAL_BINDING", "EXTERNAL_NON_BINDING", "UNVERIFIED",
})
VERDICT_TEXT_ONLY = "TEXT_VERIFIED_ONLY"
VERDICT_NOT_VERIFIED = "NOT_VERIFIED"
MIN_EXCERPT_CHARS = 8

_MARKS = re.compile("[​-‏‪-‮⁦-⁩﻿ؐ-ًؚ-ٰٟـ]")


def norm(s: str) -> str:
    """Matching key: NFKC, ligatures repaired, marks and diacritics removed, hamza forms folded, casefolded."""
    s = unicodedata.normalize("NFKC", s)
    s = repair_ligatures(s)
    s = _MARKS.sub("", s)
    s = s.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"}))
    return re.sub(r"\s+", " ", s).strip().casefold()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ extraction
def pdf_page_count(path: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(path)).pages)


def _pdftotext(path: Path, page: int | None) -> str | None:
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    cmd = [exe, "-layout"]
    if page:
        cmd += ["-f", str(page), "-l", str(page)]
    cmd += [str(path), "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return out.stdout.decode("utf-8", errors="replace")


def _pypdf_text(path: Path, page: int | None) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = [reader.pages[page - 1]] if page else list(reader.pages)
    return "\n".join((p.extract_text() or "") for p in pages)


def load_source_text(source_path: Path, page: int | None = None) -> str:
    """Text of a PDF (one page when ``page`` is given, 1-based) or of a DOCX (whole document).

    The text proves occurrence only; it carries no approval or applicability meaning.
    """
    p = Path(source_path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        text = _pdftotext(p, page)
        if text is None:
            text = _pypdf_text(p, page)
        return text
    if suffix == ".docx":
        # the accepted view of the body (tracked insertions count, deletions do not; tables included), the same
        # text the Word lifecycle anchors to (document_comments.DocText), so evidence and anchors never disagree
        import zipfile
        from lxml import etree
        from ..word.document_comments import DOC_PART, DocText
        with zipfile.ZipFile(p) as z:
            root = etree.fromstring(z.read(DOC_PART))
        return "\n".join(para.text for para in DocText(root).paras if para.text.strip())
    raise ValueError("PDF or DOCX expected")


# ------------------------------------------------------------------ citation
@dataclass(frozen=True)
class VerifiedCitation:
    """A quoted passage attributed to a source file, verified by occurrence only."""
    source_path: str
    source_name: str
    provision: str
    excerpt: str
    approval_status: str = "UNVERIFIED"
    declared_sha256: str | None = None
    page: int | None = None
    applicability_basis: str | None = None
    issuing_authority: str | None = None
    approved_by: str | None = None
    decision_ref: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def verify(self) -> dict:
        """Occurrence check. A TEXT_VERIFIED_ONLY verdict is not an approval and not an applicability finding."""
        if self.approval_status not in APPROVALS:
            raise ValueError("Unknown source approval class")
        p = Path(self.source_path)
        result = {
            "source": self.source_name, "source_path": str(p), "page": self.page,
            "approval_status": self.approval_status, "approval_supported": False,
            "hash_valid": False, "excerpt_exact_or_normalized": False, "match_mode": None,
            "applicability_verified": False, "verdict": VERDICT_NOT_VERIFIED, "reason": [],
        }
        if not p.is_file():
            result["reason"].append("SOURCE_NOT_AVAILABLE")
            return result
        actual = sha_file(p)
        result["source_sha256"] = actual
        result["hash_valid"] = not self.declared_sha256 or actual == self.declared_sha256
        if not result["hash_valid"]:
            result["reason"].append("HASH_MISMATCH")
            return result
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            if self.page is not None and not 1 <= self.page <= pdf_page_count(p):
                result["reason"].append("INVALID_PAGE")
                return result
            text = load_source_text(p, self.page)
        elif suffix == ".docx":
            text = load_source_text(p)
        else:
            result["reason"].append("UNSUPPORTED_SOURCE")
            return result
        if len(text.strip()) < 10:
            result["reason"].append("IMAGE_ONLY_SOURCE_REQUIRES_VISUAL_VERIFICATION")
            return result
        needle = norm(self.excerpt)
        if len(needle) < MIN_EXCERPT_CHARS:
            result["reason"].append("EXCERPT_TOO_SHORT_TO_VERIFY")
            return result
        hay = norm(text)
        if needle in hay:
            result["match_mode"] = "NORMALIZED"
        elif len(needle) >= 3 * MIN_EXCERPT_CHARS and lam_alef_insensitive(self.excerpt) in lam_alef_insensitive(text):
            result["match_mode"] = "LAM_ALEF_INSENSITIVE"  # ligature breaks the repair did not cover
        result["excerpt_exact_or_normalized"] = result["match_mode"] is not None
        if not result["excerpt_exact_or_normalized"]:
            result["reason"].append("EXCERPT_NOT_FOUND_IN_SOURCE")
            return result
        # Occurrence of the excerpt is deliberately not enough to support approval of the source.
        result["approval_supported"] = (self.approval_status == "APPROVED_CURRENT"
                                        and bool(self.approved_by and self.decision_ref))
        result["applicability_verified"] = bool(self.applicability_basis
                                                and len(self.applicability_basis.strip()) >= 18)
        if not result["approval_supported"]:
            result["reason"].append("APPROVAL_NOT_INDEPENDENTLY_PROVEN")
        if not result["applicability_verified"]:
            result["reason"].append("APPLICABILITY_REQUIRES_REVIEW")
        result["verdict"] = VERDICT_TEXT_ONLY
        return result


def build_reference_status(paths: list[Path], output: Path, statuses: dict[str, str] | None = None) -> dict:
    """Write a source register (name, sha256, pages, approval_status) for the given files.

    ``statuses`` maps a file name to its approval class; every file without an
    entry is UNVERIFIED. Nothing is inferred from the file name. Approval
    evidence is NOT_SUPPLIED and applicability NOT_ESTABLISHED for every entry.
    """
    statuses = statuses or {}
    summary = []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            summary.append({"name": path.name, "available": False, "status": "NOT_SUPPLIED"})
            continue
        status = statuses.get(path.name, "UNVERIFIED")
        if status not in APPROVALS:
            raise ValueError(f"Unknown source approval class for {path.name}: {status}")
        pages = pdf_page_count(path) if path.suffix.lower() == ".pdf" else None
        summary.append({"name": path.name, "available": True, "sha256": sha_file(path), "pages": pages,
                        "approval_status": status, "approval_evidence": "NOT_SUPPLIED",
                        "applicability": "NOT_ESTABLISHED"})
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"sources": len(summary), "available": sum(1 for x in summary if x["available"])}
