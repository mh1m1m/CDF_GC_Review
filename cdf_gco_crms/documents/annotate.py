"""Put review comments back onto the original file when it is not a Word document.

* PDF: each comment highlights the lines of the paragraph that holds its quote and adds a sticky note (PDF Text
  annotation) at the top of that paragraph. Page content is never changed; only annotations are added.
* Excel under review: each comment becomes a cell comment on the first cell of the row that holds its quote.

A comment whose quote is found in no block is listed in ``unplaced`` and never pinned to a guessed place.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .ingest import SourceText

AUTHOR = "الحوكمة والامتثال"
_MARKS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_ALEF = str.maketrans("أإآٱ", "اااا")


@dataclass
class Comment:
    ref: str            # observation id shown in the note
    quote: str
    body: str


@dataclass
class PlacementReport:
    placed: list[dict] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"placed": len(self.placed), "unplaced": len(self.unplaced), "unplaced_refs": self.unplaced[:50]}


def key(text: str) -> str:
    """Loose matching key: NFKC, no diacritics or tatweel, one alef form, single spaces, lower case."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _MARKS.sub("", text).translate(_ALEF).replace("ى", "ي").replace("ة", "ه")
    text = re.sub("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def find_block(source: SourceText, quote: str):
    """The first block holding the quote (exact, then loose key, then a long prefix of the loose key)."""
    quote = (quote or "").replace("…", "").strip()
    if not quote:
        return None
    for block in source.blocks:
        if quote in block.text:
            return block
    k = key(quote)
    keys = [(b, key(b.text)) for b in source.blocks]
    for block, text in keys:
        if k and k in text:
            return block
    if len(k) >= 40:
        head = k[:40]
        for block, text in keys:
            if head in text:
                return block
    return None


def annotate_pdf(src_pdf, source: SourceText, comments: list[Comment], dest) -> PlacementReport:
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Highlight, Text
    from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject

    reader = PdfReader(str(src_pdf))
    writer = PdfWriter(clone_from=reader)
    report = PlacementReport()
    stacked: dict[tuple[int, int], int] = {}
    for comment in comments:
        block = find_block(source, comment.quote)
        if block is None or block.page is None or block.box is None:
            report.unplaced.append(comment.ref)
            continue
        page = writer.pages[block.page - 1]
        box = page.mediabox
        left, bottom = float(box.left), float(box.bottom)
        height = float(box.height)

        def pdf_y(top: float) -> float:
            return bottom + height - top

        quads = []
        for x0, top, x1, bot in block.lines or [block.box]:
            quads += [left + x0, pdf_y(top), left + x1, pdf_y(top), left + x0, pdf_y(bot), left + x1, pdf_y(bot)]
        x0, top, x1, bot = block.box
        highlight = Highlight(rect=(left + x0, pdf_y(bot), left + x1, pdf_y(top)),
                              quad_points=ArrayObject(FloatObject(v) for v in quads), highlight_color="fde68a")
        highlight[NameObject("/T")] = TextStringObject(AUTHOR)
        highlight[NameObject("/Contents")] = TextStringObject(f"{comment.ref}\n{comment.body}")
        writer.add_annotation(page_number=block.page - 1, annotation=highlight)
        slot = stacked.get((block.page, block.index), 0)
        stacked[(block.page, block.index)] = slot + 1
        note_x = min(left + x1 + 4 + slot * 14, left + float(box.width) - 20)
        note_y = pdf_y(top)
        note = Text(rect=(note_x, note_y - 18, note_x + 18, note_y), text=f"{comment.ref}\n{comment.body}", open=False)
        note[NameObject("/T")] = TextStringObject(AUTHOR)
        writer.add_annotation(page_number=block.page - 1, annotation=note)
        report.placed.append({"ref": comment.ref, "page": block.page, "location": block.location})
    with open(dest, "wb") as handle:
        writer.write(handle)
    return report


def annotate_xlsx(src_xlsx, source: SourceText, comments: list[Comment], dest) -> PlacementReport:
    from openpyxl import load_workbook
    from openpyxl.comments import Comment as CellComment

    book = load_workbook(str(src_xlsx))
    report = PlacementReport()
    pending: dict[tuple[str, int], list[str]] = {}
    for comment in comments:
        block = find_block(source, comment.quote)
        if block is None or block.sheet is None or block.row is None:
            report.unplaced.append(comment.ref)
            continue
        pending.setdefault((block.sheet, block.row), []).append(f"{comment.ref}\n{comment.body}")
        report.placed.append({"ref": comment.ref, "sheet": block.sheet, "row": block.row, "location": block.location})
    for (sheet_name, row), texts in pending.items():
        sheet = book[sheet_name]
        cell = next((c for c in sheet[row] if c.value not in (None, "")), sheet.cell(row=row, column=1))
        existing = cell.comment.text + "\n\n" if cell.comment else ""
        note = CellComment(existing + "\n\n".join(texts), AUTHOR)
        note.width, note.height = 420, 220
        cell.comment = note
    book.save(str(dest))
    return report
