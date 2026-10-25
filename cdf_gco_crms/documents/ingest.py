"""Read an uploaded document under review into numbered text blocks the review engine can quote.

Every block carries the exact text a reviewer (or the drafting agent) quotes, a reader-facing location, and, for a
PDF, the page and box where it sits so a comment can be pinned back onto the original page.

* Word (.docx): the accepted view of every body paragraph, tables included (``word.document_comments.DocText``).
* PDF: words from ``pdfplumber``. pdfplumber orders the glyphs of a line by x, so an Arabic word comes out in
  visual order; it is reversed back to logical order and a right-to-left line is read right to left (the same
  repair the DoA-matrix parser uses). Lines are grouped into paragraphs by vertical gap. A scanned page with no
  text layer yields no block and is reported in ``warnings`` (no OCR here).
* Excel (.xlsx) under review: one block per non-empty row, ``sheet!row``, cells joined with `` | ``.

The text is never paraphrased. ``to_docx`` writes the blocks as a right-to-left Word document whose paragraphs
are exactly the block texts, so comments can be anchored on a PDF or spreadsheet the same way as on a Word file.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

_ARABIC = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
MAX_BLOCKS = 4000


@dataclass
class Block:
    index: int
    text: str
    location: str
    page: int | None = None                       # 1-based (PDF)
    box: tuple[float, float, float, float] | None = None   # x0, top, x1, bottom in pdfplumber page space
    lines: list[tuple[float, float, float, float]] = field(default_factory=list)
    sheet: str | None = None                      # spreadsheet under review
    row: int | None = None


@dataclass
class SourceText:
    kind: str                                     # docx | pdf | xlsx
    blocks: list[Block]
    pages: int = 0
    page_sizes: dict[int, tuple[float, float]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)

    def summary(self) -> dict:
        return {"kind": self.kind, "blocks": len(self.blocks), "pages": self.pages,
                "characters": sum(len(b.text) for b in self.blocks), "warnings": self.warnings[:20]}

    def to_json(self) -> dict:
        return {"kind": self.kind, "pages": self.pages, "warnings": self.warnings,
                "page_sizes": {str(k): v for k, v in self.page_sizes.items()},
                "blocks": [asdict(b) for b in self.blocks]}


def extract(path, kind: str) -> SourceText:
    path = Path(path)
    if kind == "docx":
        return _docx(path)
    if kind == "pdf":
        return _pdf(path)
    if kind == "xlsx":
        return _xlsx(path)
    raise ValueError("UNSUPPORTED_DOCUMENT_KIND")


# -- Word ----------------------------------------------------------------------------------------------------------

def _docx(path: Path) -> SourceText:
    from ..word.document_comments import _load_doc

    doc, _parts = _load_doc(path)
    blocks = []
    for para in doc.paras:
        text = para.text.strip()
        if text:
            n = len(blocks) + 1
            where = "جدول، " if para.in_table else ""
            blocks.append(Block(n, text, f"{where}الفقرة {para.index + 1}"))
    return SourceText("docx", blocks[:MAX_BLOCKS])


# -- PDF -----------------------------------------------------------------------------------------------------------

_LTR = re.compile(r"[A-Za-z0-9\u0660-\u0669\u06f0-\u06f9]")
_JOINERS = set(".,:/%-")


def _units(word: dict) -> list[str]:
    """The glyph texts of a word in x order. A ligature glyph stays one unit (``لا``); a zero-width non-Arabic
    glyph inside an Arabic word (a broken font mapping of a diacritic) is dropped."""
    arabic_word = bool(_ARABIC.search(word["text"]))
    units = []
    for char in word.get("chars") or [{"text": c, "x0": 0, "x1": 9} for c in word["text"]]:
        text = char["text"]
        if arabic_word and not _ARABIC.search(text) and (char["x1"] - char["x0"]) < 1.6:
            continue
        units.append(text)
    return units


def visual_to_logical(units: list[str]) -> str:
    """Reverse glyph units of a right-to-left run, keeping digit/Latin runs (with inner . , : / % -) in order."""
    rev = units[::-1]
    out: list[str] = []
    i = 0
    while i < len(rev):
        if _LTR.match(rev[i]):
            j = i
            while j + 1 < len(rev) and (_LTR.match(rev[j + 1]) or (
                    rev[j + 1] in _JOINERS and j + 2 < len(rev) and _LTR.match(rev[j + 2]))):
                j += 1
            out.extend(reversed(rev[i:j + 1]))
            i = j + 1
        else:
            out.append(rev[i])
            i += 1
    return "".join(out)


def logical_order(word: str) -> str:
    return visual_to_logical(list(word))


def _rtl(words: list[dict]) -> bool:
    arabic = sum(1 for w in words if _ARABIC.search(w["text"]))
    return arabic * 2 >= len(words)


def _line_text(words: list[dict], rtl: bool | None = None) -> str:
    if _rtl(words) if rtl is None else rtl:
        ordered = sorted(words, key=lambda w: -w["x1"])
        text = " ".join(visual_to_logical(_units(w)) for w in ordered)
    else:
        ordered = sorted(words, key=lambda w: w["x0"])
        text = " ".join(visual_to_logical(_units(w)) if _ARABIC.search(w["text"]) else w["text"] for w in ordered)
    return _clean(text)


_INVISIBLE = re.compile("[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)     # presentation forms → letters; ligature glyphs → their letters
    return re.sub(r"\s+", " ", _INVISIBLE.sub("", text)).strip()


def _pdf(path: Path) -> SourceText:
    import pdfplumber

    out = SourceText("pdf", [])
    with pdfplumber.open(str(path)) as pdf:
        out.pages = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, 1):
            out.page_sizes[pno] = (float(page.width), float(page.height))
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5, y_tolerance=3,
                                       return_chars=True)
            if not words:
                out.warnings.append(f"PAGE_{pno}_HAS_NO_TEXT_LAYER")
                continue
            lines: list[list[dict]] = []
            for word in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
                if lines and abs(word["top"] - lines[-1][0]["top"]) <= 3:
                    lines[-1].append(word)
                else:
                    lines.append([word])
            heights = sorted(l[0]["bottom"] - l[0]["top"] for l in lines)
            typical = heights[len(heights) // 2] if heights else 10.0
            paragraph: list[list[dict]] = []
            para_no = 0

            def close():
                nonlocal paragraph, para_no
                if not paragraph:
                    return
                rtl = _rtl([w for l in paragraph for w in l])        # a paragraph has one base direction
                text = " ".join(_line_text(l, rtl) for l in paragraph).strip()
                if text:
                    para_no += 1
                    boxes = [(min(w["x0"] for w in l), min(w["top"] for w in l), max(w["x1"] for w in l),
                              max(w["bottom"] for w in l)) for l in paragraph]
                    box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                           max(b[3] for b in boxes))
                    out.blocks.append(Block(len(out.blocks) + 1, text, f"صفحة {pno}، فقرة {para_no}", page=pno,
                                            box=box, lines=boxes))
                paragraph = []

            previous_bottom = None
            for line in lines:
                top = min(w["top"] for w in line)
                if previous_bottom is not None and top - previous_bottom > typical * 0.9:
                    close()
                paragraph.append(line)
                previous_bottom = max(w["bottom"] for w in line)
            close()
            if len(out.blocks) >= MAX_BLOCKS:
                out.warnings.append("TOO_MANY_BLOCKS_TRUNCATED")
                break
    out.blocks = out.blocks[:MAX_BLOCKS]
    if not out.blocks:
        out.warnings.append("NO_TEXT_FOUND_SCANNED_PDF_NEEDS_OCR")
    return out


# -- Excel under review --------------------------------------------------------------------------------------------

def _xlsx(path: Path) -> SourceText:
    from openpyxl import load_workbook

    out = SourceText("xlsx", [])
    book = load_workbook(str(path), read_only=True, data_only=True)
    try:
        for sheet in book.worksheets:
            for r, row in enumerate(sheet.iter_rows(values_only=True), 1):
                cells = [_clean(str(v)) for v in row if v is not None and str(v).strip()]
                if cells:
                    out.blocks.append(Block(len(out.blocks) + 1, " | ".join(cells), f"ورقة {sheet.title}، صف {r}",
                                            sheet=sheet.title, row=r))
                if len(out.blocks) >= MAX_BLOCKS:
                    out.warnings.append("TOO_MANY_ROWS_TRUNCATED")
                    return out
    finally:
        book.close()
    out.pages = len(book.worksheets)
    return out


# -- Word rendition of a PDF or spreadsheet ------------------------------------------------------------------------

def to_docx(source: SourceText, title: str, dest) -> Path:
    """Write the blocks as an RTL Word document (one paragraph per block) for anchoring review comments."""
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    def rtl(paragraph):
        props = paragraph._p.get_or_add_pPr()
        bidi = OxmlElement("w:bidi")
        bidi.set(qn("w:val"), "1")
        props.append(bidi)       # a right-to-left paragraph starts at the right; an explicit "right" would flip it

    doc = Document()
    heading = doc.add_paragraph()
    run = heading.add_run(title)
    run.bold = True
    run.font.size = Pt(14)
    rtl(heading)
    note = doc.add_paragraph()
    label = {"pdf": "نص مستخرج من ملف PDF", "xlsx": "نص مستخرج من جدول Excel"}.get(source.kind, "نص المستند")
    small = note.add_run(label + " — يُحفظ النص كما ورد دون تعديل.")
    small.font.size = Pt(8)
    small.font.color.rgb = RGBColor(0x66, 0x74, 0x82)
    rtl(note)
    current = None
    for block in source.blocks:
        marker = block.page if source.kind == "pdf" else block.sheet
        if marker is not None and marker != current:
            current = marker
            sep = doc.add_paragraph()
            sep_run = sep.add_run(f"— صفحة {marker} —" if source.kind == "pdf" else f"— ورقة {marker} —")
            sep_run.font.size = Pt(8)
            sep_run.font.color.rgb = RGBColor(0x66, 0x74, 0x82)
            rtl(sep)
        para = doc.add_paragraph(block.text)
        rtl(para)
    dest = Path(dest)
    doc.save(str(dest))
    return dest
