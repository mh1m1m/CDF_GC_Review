"""Fictional Arabic memo used by the document tests, built at test time.

The public repository refuses PDF files (tools/mat_dna/public_repository_guard.py), so the PDF is produced from the
committed text: python-docx writes a right-to-left Word file and LibreOffice exports it. Tests that need the PDF are
skipped where LibreOffice is not installed.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

TEXT = Path(__file__).parent / "fixtures" / "documents" / "synthetic_arabic_memo.txt"
_CACHE: dict[str, bytes] = {}


def memo_lines() -> list[str]:
    return TEXT.read_text(encoding="utf-8").split("\n")


def memo_docx(path: Path) -> Path:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    word = Document()
    for line in memo_lines():
        paragraph = word.add_paragraph(line)
        bidi = OxmlElement("w:bidi")
        bidi.set(qn("w:val"), "1")
        paragraph._p.get_or_add_pPr().append(bidi)
    word.save(path)
    return path


def memo_pdf() -> bytes:
    if "pdf" not in _CACHE:
        from cdf_gco_crms.qa.lo_engine import available, to_pdf

        import pytest

        if not available():
            pytest.skip("LibreOffice is needed to build the PDF fixture")
        with tempfile.TemporaryDirectory(prefix="cdf-memo-") as tmp:
            pdf = to_pdf(memo_docx(Path(tmp) / "synthetic_arabic_memo.docx"), Path(tmp) / "pdf", timeout=180)
            if pdf is None:
                pytest.skip("LibreOffice could not export the PDF fixture")
            _CACHE["pdf"] = pdf.read_bytes()
    return _CACHE["pdf"]


def memo_pdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic_arabic_memo.pdf"
    path.write_bytes(memo_pdf())
    return path
