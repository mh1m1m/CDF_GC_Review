"""Renders the consolidated protocol text as Markdown and as an editable Word document.

The text itself is never changed: Markdown adds heading marks and paragraph
breaks only; Word adds styles, right-to-left paragraphs for Arabic lines and
document properties (09.4). Separator rules become heading spacing.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import workbook_settings as W

ARABIC = re.compile(r"[؀-ۿ]")
HEAD1 = re.compile(r"^(PART [0IVX]+ — |PREAMBLE — |ANNEX [A-F] — )")
HEAD2 = re.compile(r"^ARTICLE \d{2}A? — ")
SUBCLAUSE = re.compile(r"^(\d{2}A?\.\d+[A-Z]?(?:\.\d+)?|D\.\d+|E\.\d+(?:\.\d+)?|C\.\d+|F\.\d+(?:\.\d+)?)\s")


def is_arabic(line: str) -> bool:
    letters = [ch for ch in line if ch.isalpha()]
    if not letters:
        return False
    return sum(1 for ch in letters if ARABIC.match(ch)) / len(letters) > 0.5


def to_markdown(text: str, version: str, issued: str) -> str:
    out = [f"<!-- Author: {W.AUTHOR} | Last modified by: {W.AUTHOR} | Company: {W.COMPANY} | "
           f"Title: CDF–GCO–CRMS v{version} | Issued: {issued} -->", ""]
    lines = text.split("\n")
    first = True
    for ln in lines:
        if ln.startswith("═"):
            continue
        if not ln.strip():
            continue
        if first:
            out += [f"# {ln}", ""]
            first = False
            continue
        if HEAD1.match(ln):
            out += [f"# {ln}", ""]
        elif HEAD2.match(ln):
            out += [f"## {ln}", ""]
        elif ln.startswith("  ") or ln.startswith(" G-") or ln.startswith(" ("):
            out += ["    " + ln.rstrip(), ""] if ln.startswith("  ") else [ln.strip(), ""]
        else:
            m = SUBCLAUSE.match(ln)
            if m and len(ln) < 4000:
                out += [f"**{m.group(1)}**{ln[len(m.group(1)):]}", ""]
            else:
                out += [ln, ""]
    return "\n".join(out).rstrip() + "\n"


def to_docx(text: str, path, version: str, issued: str):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Cm

    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    styles = doc.styles
    for name in ("Normal", "Heading 1", "Heading 2", "Title"):
        st = styles[name]
        st.font.name = "Calibri"
        rpr = st.element.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(a), "Calibri")
        for t in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            if rf.get(qn(t)) is not None:
                del rf.attrib[qn(t)]
    styles["Normal"].font.size = Pt(10)
    styles["Heading 1"].font.size = Pt(14)
    styles["Heading 1"].font.color.rgb = RGBColor(0x10, 0x18, 0x20)
    styles["Heading 2"].font.size = Pt(12)
    styles["Heading 2"].font.color.rgb = RGBColor(0x10, 0x18, 0x20)
    styles["Normal"].paragraph_format.space_after = Pt(4)

    # footer with page number
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fp.add_run(f"CDF–GCO–CRMS v{version} — ")
    run.font.size = Pt(8)
    for kind, txt in (("begin", None), (None, "PAGE"), ("end", None)):
        r = fp.add_run()
        r.font.size = Pt(8)
        if kind:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            r._r.append(fc)
        else:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = txt
            r._r.append(it)

    def para(line: str, style: str | None = None, bold_prefix: str | None = None, indent: bool = False):
        p = doc.add_paragraph(style=style)
        rtl = is_arabic(line)
        if rtl:
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            ppr = p._p.get_or_add_pPr()
            bidi = OxmlElement("w:bidi")
            ppr.insert(0, bidi)
        if indent:
            p.paragraph_format.left_indent = Cm(0.6) if not rtl else None
            if rtl:
                p.paragraph_format.right_indent = Cm(0.6)
        body = line
        if bold_prefix:
            r = p.add_run(bold_prefix)
            r.bold = True
            _rtl(r, rtl)
            body = line[len(bold_prefix):]
        r = p.add_run(body)
        _rtl(r, rtl)
        return p

    def _rtl(run, rtl):
        rpr = run._r.get_or_add_rPr()
        rf = OxmlElement("w:rFonts")
        for a in ("w:ascii", "w:hAnsi", "w:cs"):
            rf.set(qn(a), "Calibri")
        rpr.insert(0, rf)
        if rtl:
            rpr.append(OxmlElement("w:rtl"))

    lines = text.split("\n")
    title_done = False
    for ln in lines:
        if ln.startswith("═") or not ln.strip():
            continue
        if not title_done:
            p = para(ln, "Title")
            title_done = True
            continue
        if HEAD1.match(ln):
            para(ln, "Heading 1")
        elif HEAD2.match(ln):
            para(ln, "Heading 2")
        else:
            m = SUBCLAUSE.match(ln)
            para(ln.strip() if ln.startswith(" ") else ln, None,
                 bold_prefix=m.group(1) if m else None, indent=ln.startswith(" "))
    cp = doc.core_properties
    cp.author = W.AUTHOR
    cp.last_modified_by = W.AUTHOR
    cp.title = f"CDF–GCO–CRMS v{version}"
    cp.subject = "Unified Master Agent Operating Protocol — consolidated edition"
    cp.keywords = ""
    cp.comments = ""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0, tzinfo=None)
    cp.created = now
    cp.modified = now
    cp.revision = 1
    path = Path(path)
    doc.save(path)
    _set_company(path)
    return path


def _set_company(path):
    """python-docx does not write app.xml Company; set it and drop the generator name (09.4)."""
    import zipfile
    import os
    tmp = str(path) + ".tmp"
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
           'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
           f'<Company>{W.COMPANY}</Company></Properties>')
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        names = zin.namelist()
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/app.xml":
                data = app.encode("utf-8")
            zout.writestr(item, data)
        if "docProps/app.xml" not in names:
            zout.writestr("docProps/app.xml", app)
    os.replace(tmp, path)
