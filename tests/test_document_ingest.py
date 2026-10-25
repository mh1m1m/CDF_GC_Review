"""Reading uploaded documents under review (Word, PDF, Excel) and pinning comments back onto PDF/Excel originals.

The PDF is a fictional Arabic memo exported from Word by LibreOffice at test time (document_fixtures.py).
"""
import io
from pathlib import Path

import pytest

from cdf_gco_crms.documents.annotate import Comment, annotate_pdf, annotate_xlsx, find_block, key
from cdf_gco_crms.documents.ingest import extract, to_docx, visual_to_logical
from document_fixtures import memo_lines, memo_pdf_path

pytest.importorskip("pdfplumber")


def test_pdf_arabic_text_in_logical_order(tmp_path):
    source = extract(memo_pdf_path(tmp_path), "pdf")
    expected = memo_lines()
    assert source.pages == 1 and len(source.blocks) == len(expected)
    for block, line in zip(source.blocks, expected):
        # the fixture's font maps the tanween glyph to a zero-width "6"; it is dropped, never kept as a digit
        assert block.text in (line, line.replace("ً", "")), block.text
        assert block.page == 1 and block.box and block.lines
    assert source.blocks[1].location == "صفحة 1، فقرة 2"


def test_visual_order_repair_keeps_numbers_and_ligatures():
    assert visual_to_logical(list(":)3(")) == "(3):"
    assert visual_to_logical(list(".2024")) == "2024."
    assert visual_to_logical(["ل", "لا", "خ"]) == "خلال"          # a ligature glyph stays one unit
    assert visual_to_logical(list("000021")) == "000021"


def test_docx_blocks_and_word_rendition(tmp_path):
    from docx import Document

    word = Document()
    for text in ("الفقرة الأولى من المستند.", "", "يجوز للطرف الثاني رفض طلبات التدقيق."):
        word.add_paragraph(text)
    word.add_table(rows=1, cols=1).cell(0, 0).text = "خلية جدول"
    path = tmp_path / "doc.docx"
    word.save(path)
    source = extract(path, "docx")
    assert [b.text for b in source.blocks] == ["الفقرة الأولى من المستند.", "يجوز للطرف الثاني رفض طلبات التدقيق.",
                                                 "خلية جدول"]
    assert source.blocks[2].location.startswith("جدول")
    pdf_source = extract(memo_pdf_path(tmp_path), "pdf")
    out = to_docx(pdf_source, "مذكرة", tmp_path / "rendition.docx")
    paragraphs = [p.text for p in Document(out).paragraphs]
    assert all(b.text in paragraphs for b in pdf_source.blocks)


def test_pdf_annotation_places_and_refuses_to_guess(tmp_path):
    from pypdf import PdfReader

    pdf = memo_pdf_path(tmp_path)
    source = extract(pdf, "pdf")
    comments = [Comment("GCO-1", "تلتزم الجهة بدفع 120000 ريال", "الملاحظة: التزام مالي. التوصية: توثيق الحد."),
                Comment("GCO-2", "رفض طلبات التدقيق", "حفظ حق المراجعة."),
                Comment("GCO-3", "عبارة لا ترد في المستند", "x")]
    out = tmp_path / "annotated.pdf"
    report = annotate_pdf(pdf, source, comments, out)
    assert [p["ref"] for p in report.placed] == ["GCO-1", "GCO-2"] and report.unplaced == ["GCO-3"]
    annots = [a.get_object() for a in PdfReader(out).pages[0]["/Annots"]]
    assert sorted(a["/Subtype"] for a in annots) == ["/Highlight", "/Highlight", "/Text", "/Text"]
    assert any("GCO-1" in a["/Contents"] for a in annots)
    # page text is untouched
    assert extract(out, "pdf").text == source.text


def test_spreadsheet_under_review(tmp_path):
    from openpyxl import Workbook, load_workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "الميزانية"
    sheet.append(["البند", "المبلغ", "الجهة المعتمدة"])
    sheet.append(["عقد استشارات", 450000, "غير محدد"])
    path = tmp_path / "budget.xlsx"
    book.save(path)
    source = extract(path, "xlsx")
    assert source.blocks[1].text == "عقد استشارات | 450000 | غير محدد"
    assert source.blocks[1].location == "ورقة الميزانية، صف 2"
    out = tmp_path / "commented.xlsx"
    report = annotate_xlsx(path, source, [Comment("GCO-9", "عقد استشارات | 450000", "جهة الاعتماد غير محددة.")], out)
    assert report.summary()["placed"] == 1
    assert "GCO-9" in load_workbook(out)["الميزانية"]["A2"].comment.text


def test_loose_matching_key(tmp_path):
    assert key("إعداد  الطلبِ") == key("اعداد الطلب")
    source = extract(memo_pdf_path(tmp_path), "pdf")
    assert find_block(source, "يوماً من توقيع الاتفاق").index == 2      # tanween in the quote, absent in the PDF text
    assert find_block(source, "") is None
