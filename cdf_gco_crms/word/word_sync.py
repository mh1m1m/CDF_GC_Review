"""Word–Excel synchronisation (protocol Art. 13, 08.2, 08.3; gate G-DASH-12; TEST 12).

* ``extract_comments`` reads the comments of any .docx (comments.xml) and finds,
  by pattern (13.2), the reader label, the "REF: " line and, for follow-ups,
  the status word of line 3.
* ``reconcile`` checks a Word file against a requester workbook: one REF per
  workbook row (round 1) or per row not مغلقة at the start of the round and
  per row reopened in the round (round n, 10.2 and 16.1), labels equal column A, status words equal the round-n closure
  column, and the dashboard's current counts equal the counts in Word.
* ``build_review_docx`` writes a synthetic reviewed document for tests: the
  quoted passages as paragraphs and GCO comments in the 08.2/08.3 format
  (label, white 2-pt REF line, body), Calibri on every run. The round-n file
  carries the birth comment of every observation and its follow-ups as native
  reply threads (G-SYNC-9, v7.12): python-docx has no reply API, so after the
  save the package is post-processed with lxml: every comment's first paragraph
  receives a w14:paraId, word/commentsExtended.xml (w15) links each follow-up to
  its birth comment through w15:paraIdParent and marks مغلقة threads resolved
  (w15:done="1"), word/commentsIds.xml (w16cid) carries the durable ids, and the
  two parts are registered in [Content_Types].xml and document.xml.rels.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from ..config import round_schema as S
from ..config import workbook_settings as W
from ..model.entities import ReviewState, plain_text

WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14NS = "http://schemas.microsoft.com/office/word/2010/wordml"
W15NS = "http://schemas.microsoft.com/office/word/2012/wordml"
W16CIDNS = "http://schemas.microsoft.com/office/word/2016/wordml/cid"
MCNS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
COMMENTS_EX_PART = "word/commentsExtended.xml"
COMMENTS_IDS_PART = "word/commentsIds.xml"
COMMENTS_EX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
COMMENTS_IDS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsIds+xml"
COMMENTS_EX_REL = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
COMMENTS_IDS_REL = "http://schemas.microsoft.com/office/2016/09/relationships/commentsIds"
GCO_AUTHOR = "إدارة الحوكمة والامتثال المؤسسي"
REF_RE = re.compile(r"REF:\s*(?P<id>GCO-[A-Z]{2,4}-R\d+-\d{3})(?:\s*/\s*R(?P<fu>\d+)-FU)?")
LABEL_RE = re.compile(r"^(?:متابعة )?الملاحظة #(?P<no>\d{2,3})(?:\s*–\s*الجولة\s+(?P<ord>\S+))?\s*$")


@dataclass
class WordComment:
    cid: str
    author: str
    lines: list[str]
    internal_id: str | None = None
    follow_up_round: int | None = None
    reader_no: str | None = None
    status: str | None = None
    ref_line_index: int | None = None
    ref_run_ok: bool = False
    para_id: str | None = None          # w14:paraId of the first paragraph (thread key)
    parent_cid: str | None = None       # id of the comment this one replies to (w15:paraIdParent), else None
    done: bool | None = None            # w15:done of the thread, None when commentsExtended.xml is absent


@dataclass
class SyncReport:
    docx: str
    xlsx: str
    round: int
    comments: int = 0
    gco_comments: int = 0
    expected: int = 0
    problems: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems and all(self.checks.values())


def extract_comments(docx) -> list[WordComment]:
    out = []
    with zipfile.ZipFile(docx) as z:
        if "word/comments.xml" not in z.namelist():
            return out
        root = etree.fromstring(z.read("word/comments.xml"))
        ext = etree.fromstring(z.read(COMMENTS_EX_PART)) if COMMENTS_EX_PART in z.namelist() else None
    for c in root.findall(f"{{{WNS}}}comment"):
        lines = []
        first_p = c.find(f"{{{WNS}}}p")
        para_id = first_p.get(f"{{{W14NS}}}paraId") if first_p is not None else None
        ref_ok = False
        ref_idx = None
        for i, p in enumerate(c.findall(f"{{{WNS}}}p")):
            text = "".join(t.text or "" for t in p.iter(f"{{{WNS}}}t"))
            lines.append(text)
            if REF_RE.search(text):
                ref_idx = i
                for r in p.findall(f"{{{WNS}}}r"):
                    rpr = r.find(f"{{{WNS}}}rPr")
                    if rpr is None:
                        continue
                    color = rpr.find(f"{{{WNS}}}color")
                    sz = rpr.find(f"{{{WNS}}}sz")
                    if color is not None and color.get(f"{{{WNS}}}val", "").upper() == "FFFFFF" and \
                            sz is not None and sz.get(f"{{{WNS}}}val") == "4":
                        ref_ok = True
        wc = WordComment(c.get(f"{{{WNS}}}id"), c.get(f"{{{WNS}}}author", ""), lines, ref_line_index=ref_idx,
                         ref_run_ok=ref_ok, para_id=(para_id or "").upper() or None)
        for ln in lines:
            m = REF_RE.search(ln)
            if m:
                wc.internal_id = m.group("id")
                wc.follow_up_round = int(m.group("fu")) if m.group("fu") else None
                break
        if lines:
            m = LABEL_RE.match(lines[0].strip())
            if m:
                wc.reader_no = m.group("no")
        if wc.follow_up_round and len(lines) >= 3:
            head = lines[2].split(":", 1)[0].strip()
            wc.status = head if head in S.CLOSURE_VALUES else None
        out.append(wc)
    if ext is not None:                                   # reply threads (w15 commentsExtended)
        by_para = {wc.para_id: wc for wc in out if wc.para_id}
        for ex in ext.findall(f"{{{W15NS}}}commentEx"):
            wc = by_para.get((ex.get(f"{{{W15NS}}}paraId") or "").upper())
            if wc is None:
                continue
            parent = ex.get(f"{{{W15NS}}}paraIdParent")
            wc.parent_cid = by_para[parent.upper()].cid if parent and parent.upper() in by_para else None
            wc.done = ex.get(f"{{{W15NS}}}done", "0") in ("1", "true")
    return out


def reconcile(docx, xlsx, *, round_no: int | None = None) -> SyncReport:
    from ..ingestion.workbook_reader import parse_workbook
    from openpyxl import load_workbook
    pw = parse_workbook(xlsx)
    st = pw.state
    R = round_no or st.current_round
    rep = SyncReport(str(docx), str(xlsx), R)
    comments = extract_comments(docx)
    rep.comments = len(comments)
    gco = [c for c in comments if c.author == GCO_AUTHOR and c.internal_id]
    rep.gco_comments = len(gco)
    by_id = st.by_id()
    if R == 1:
        expected = {o.internal_id for o in st.observations}
        got = {c.internal_id for c in gco if c.follow_up_round is None}
    else:
        expected = {o.internal_id for o in st.observations if o.birth_round < R
                    and (o.value(R - 1) != S.CLOSED or o.value(R) != S.CLOSED)}   # open at start, or reopened (16.1)
        expected |= {o.internal_id for o in st.observations if o.birth_round == R}
        got = {c.internal_id for c in gco if c.follow_up_round == R}
        got |= {c.internal_id for c in gco if c.follow_up_round is None and by_id.get(c.internal_id)
                and by_id[c.internal_id].birth_round == R}
    rep.expected = len(expected)
    rep.checks["G-SYNC-1 count"] = got == expected
    if got != expected:
        rep.problems.append(f"missing in Word: {sorted(expected - got)}; not expected: {sorted(got - expected)}")
    ids = [c.internal_id for c in gco if (c.follow_up_round == R or (R == 1 and c.follow_up_round is None))]
    rep.checks["G-SYNC-2 one REF per row"] = len(ids) == len(set(ids))
    lab_ok, st_ok, ref_ok = True, True, True
    for c in gco:
        o = by_id.get(c.internal_id)
        if o is None:
            rep.problems.append(f"comment {c.cid}: REF {c.internal_id} has no workbook row")
            lab_ok = False
            continue
        if c.reader_no != o.reader_no:
            rep.problems.append(f"{c.internal_id}: label #{c.reader_no} != column A {o.reader_no}")
            lab_ok = False
        if c.ref_line_index != 1 or not c.ref_run_ok:
            ref_ok = False
            rep.problems.append(f"{c.internal_id}: REF line not on line 2 in white 2 pt")
        if c.follow_up_round == R and R > 1:
            if c.status != o.value(R):
                st_ok = False
                rep.problems.append(f"{c.internal_id}: Word status {c.status!r} != workbook {o.value(R)!r}")
    rep.checks["G-SYNC-2 labels = column A"] = lab_ok
    rep.checks["G-ID-1 REF line format"] = ref_ok
    rep.checks["G-SYNC-3 status words = block R"] = st_ok
    # G-SYNC-9: every round-R follow-up is a native reply to the birth comment of the same observation
    th_ok = True
    if R > 1:
        by_cid = {c.cid: c for c in comments}
        for c in gco:
            if c.follow_up_round != R:
                continue
            parent = by_cid.get(c.parent_cid) if c.parent_cid else None
            if parent is None:
                th_ok = False
                rep.problems.append(f"{c.internal_id}: round-{R} follow-up is a top-level comment, not a reply")
            elif parent.internal_id != c.internal_id or parent.follow_up_round is not None:
                th_ok = False
                rep.problems.append(f"{c.internal_id}: round-{R} follow-up replies to comment {parent.cid} "
                                    f"({parent.internal_id}{' follow-up' if parent.follow_up_round else ''}), "
                                    "not to its birth comment")
    rep.checks["G-SYNC-9 follow-ups threaded"] = th_ok
    # dashboard counts (cached values) against Word status counts and the data sheet
    wb = load_workbook(xlsx, data_only=True)
    if W.DASHBOARD_SHEET in wb.sheetnames and W.HELPER_SHEET in wb.sheetnames:
        hs = wb[W.HELPER_SHEET]
        hdr = {hs.cell(row=1, column=c).value: c for c in range(1, hs.max_column + 1)}
        rowR = 1 + R
        counts = {v: hs.cell(row=rowR, column=hdr[f"trend.{k}"]).value
                  for v, k in ((S.CLOSED, "closed"), (S.CLOSED_COND, "cond"), (S.REQUIRES_EDIT, "req"), (S.OPEN, "open"))}
        sheet_counts = {v: sum(1 for o in st.observations if o.value(R) == v) for v in S.CLOSURE_VALUES}
        rep.checks["G-DASH-12 dashboard counts = data sheet"] = counts == sheet_counts
        if counts != sheet_counts:
            rep.problems.append(f"dashboard {counts} != sheet {sheet_counts}")
        if R > 1:
            word_counts = {v: sum(1 for c in gco if c.follow_up_round == R and c.status == v) for v in S.CLOSURE_VALUES}
            expect_word = {v: sum(1 for o in st.observations if o.internal_id in expected and o.birth_round < R
                                  and o.value(R) == v) for v in S.CLOSURE_VALUES}
            rep.checks["G-DASH-12 Word follow-up statuses = assessed rows"] = word_counts == expect_word
    return rep


# ---------------------------------------------------------------------- synthetic documents
def build_review_docx(state: ReviewState, path, *, round_no: int | None = None, break_ids: set | None = None):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    R = round_no or state.current_round
    doc = Document()
    sect = doc.sections[0]
    sect._sectPr.set(qn("w:rtlGutter"), "0")
    title = doc.add_paragraph()
    run = title.add_run(f"{state.document.name} (وثيقة تجريبية لاختبار التزامن)")
    _calibri(run, 12, bold=True)
    anchors = {}
    for o in state.ordered():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run(plain_text(o.quote))
        _calibri(r, 11)
        anchors[o.internal_id] = r
    break_ids = break_ids or set()

    def add(run, lines) -> str:
        c = doc.add_comment([run], text="", author=GCO_AUTHOR, initials="حوكمة")
        first = c.paragraphs[0]
        for i, (text, kind) in enumerate(lines):
            para = first if i == 0 else c.add_paragraph()
            rr = para.add_run(text)
            if kind == "ref":
                _calibri(rr, 2)
                rr.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            else:
                _calibri(rr, 10, bold=(kind == "bold"))
        return str(c.comment_id)
    # one thread per observation: the birth comment (top level) and, for every round j ≤ R in which the row
    # was not مغلقة at the start of the round, the round-j follow-up as a reply anchored on the same run
    parents: dict[str, str] = {}        # reply cid -> birth cid
    resolved: dict[str, bool] = {}      # thread root cid -> w15:done
    for o in state.ordered():
        iid = o.internal_id
        if o.birth_round > R:
            continue
        lines = [(f"الملاحظة #{o.reader_no}", "bold"), (f"REF: {iid}", "ref")]
        lines += [(ln, "body") for ln in plain_text(o.comment).split("\n")]
        root = add(anchors[iid], lines)
        last_status = S.OPEN
        for j in range(o.birth_round + 1, R + 1):
            # a row closed at the start of round j gets no follow-up unless round j reopens it (16.1, v7.12)
            if o.value(j - 1) == S.CLOSED and o.value(j) == S.CLOSED:
                continue
            status = o.value(j)
            if j == R and iid in break_ids:
                status = S.OPEN if o.value(R) != S.OPEN else S.CLOSED
            fb = plain_text(o.cells[j].feedback).split("\n")
            lines = [(f"متابعة الملاحظة #{o.reader_no} {S.EN_DASH} الجولة {S.ordinal(j)}", "bold"),
                     (f"REF: {iid} / R{j}-FU", "ref"), (f"{status}: {fb[0]}", "body")]
            lines += [(ln, "body") for ln in fb[1:]]
            parents[add(anchors[iid], lines)] = root
            last_status = status
        resolved[root] = last_status == S.CLOSED
    cp = doc.core_properties
    cp.author = W.AUTHOR
    cp.last_modified_by = W.AUTHOR
    cp.comments = ""
    import datetime as _dt
    cp.created = cp.modified = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0, tzinfo=None)
    from ..config.workbook_settings import file_stem
    cp.title = file_stem(state.document.name, R)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    _thread_comments(path, parents, resolved)
    from ..protocol.render import _set_company
    _set_company(path)
    return path


def _thread_comments(path, parents: dict[str, str], resolved: dict[str, bool] | None = None):
    """Post-process a saved .docx into Word reply threads (w15 commentsExtended; G-SYNC-9).

    ``parents`` maps the w:id of a reply comment to the w:id of its thread root; ``resolved`` maps a root
    w:id to the thread's w15:done. Every comment's first paragraph gets a unique w14:paraId (Word's thread
    key, 8 hex digits below 0x80000000); the w15 and w16cid parts are written and registered.
    """
    import os
    resolved = resolved or {}
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        parts = {i.filename: z.read(i.filename) for i in z.infolist()}
        infos = z.infolist()
    if "word/comments.xml" not in parts:
        return
    # 1. comments.xml: w14:paraId on the first paragraph of every comment; w15 declared; mc:Ignorable
    old = etree.fromstring(parts["word/comments.xml"])
    nsmap = dict(old.nsmap)
    nsmap.setdefault("mc", MCNS)
    nsmap.setdefault("w14", W14NS)
    nsmap.setdefault("w15", W15NS)
    root = etree.Element(old.tag, nsmap=nsmap)
    for k, v in old.attrib.items():
        root.set(k, v)
    for child in list(old):
        root.append(child)
    ignorable = (root.get(f"{{{MCNS}}}Ignorable") or "").split()
    root.set(f"{{{MCNS}}}Ignorable", " ".join(ignorable + [t for t in ("w14", "w15") if t not in ignorable]))
    used = set()
    for el in root.iter(f"{{{WNS}}}p"):
        pid = el.get(f"{{{W14NS}}}paraId")
        if pid:
            used.add(pid.upper())
    para_of: dict[str, str] = {}
    order: list[str] = []
    n = 0
    for c in root.findall(f"{{{WNS}}}comment"):
        cid = c.get(f"{{{WNS}}}id")
        p = c.find(f"{{{WNS}}}p")
        if p is None:
            p = etree.SubElement(c, f"{{{WNS}}}p")
        pid = p.get(f"{{{W14NS}}}paraId")
        if not pid:
            while True:
                n += 1
                pid = f"{0x1F000000 + n * 0x0101:08X}"
                if pid not in used:
                    break
            used.add(pid)
            p.set(f"{{{W14NS}}}paraId", pid)
            p.set(f"{{{W14NS}}}textId", pid)
        para_of[cid] = pid.upper()
        order.append(cid)
    parts["word/comments.xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    # 2. commentsExtended.xml (w15): paraId, paraIdParent for replies, done per thread
    ex = etree.Element(f"{{{W15NS}}}commentsEx", nsmap={"mc": MCNS, "w15": W15NS})
    ex.set(f"{{{MCNS}}}Ignorable", "w15")
    for cid in order:
        e = etree.SubElement(ex, f"{{{W15NS}}}commentEx")
        e.set(f"{{{W15NS}}}paraId", para_of[cid])
        root_cid = parents.get(cid)
        if root_cid is not None and root_cid in para_of:
            e.set(f"{{{W15NS}}}paraIdParent", para_of[root_cid])
        e.set(f"{{{W15NS}}}done", "1" if resolved.get(root_cid if root_cid is not None else cid) else "0")
    parts[COMMENTS_EX_PART] = etree.tostring(ex, xml_declaration=True, encoding="UTF-8", standalone=True)
    # 3. commentsIds.xml (w16cid): a durable id per comment
    ids = etree.Element(f"{{{W16CIDNS}}}commentsIds", nsmap={"mc": MCNS, "w16cid": W16CIDNS})
    ids.set(f"{{{MCNS}}}Ignorable", "w16cid")
    for k, cid in enumerate(order, 1):
        e = etree.SubElement(ids, f"{{{W16CIDNS}}}commentId")
        e.set(f"{{{W16CIDNS}}}paraId", para_of[cid])
        e.set(f"{{{W16CIDNS}}}durableId", f"{0x2E000000 + k * 0x0101:08X}")
    parts[COMMENTS_IDS_PART] = etree.tostring(ids, xml_declaration=True, encoding="UTF-8", standalone=True)
    # 4. content types and the document relationships
    ct = etree.fromstring(parts["[Content_Types].xml"])
    have = {o.get("PartName") for o in ct.findall(f"{{{CT_NS}}}Override")}
    for part, ctype in ((COMMENTS_EX_PART, COMMENTS_EX_CT), (COMMENTS_IDS_PART, COMMENTS_IDS_CT)):
        if f"/{part}" not in have:
            etree.SubElement(ct, f"{{{CT_NS}}}Override", PartName=f"/{part}", ContentType=ctype)
    parts["[Content_Types].xml"] = etree.tostring(ct, xml_declaration=True, encoding="UTF-8", standalone=True)
    rels = etree.fromstring(parts["word/_rels/document.xml.rels"])
    have_types = {r.get("Type") for r in rels.findall(f"{{{REL_NS}}}Relationship")}
    rid_nums = [int(r.get("Id")[3:]) for r in rels.findall(f"{{{REL_NS}}}Relationship")
                if re.fullmatch(r"rId\d+", r.get("Id") or "")]
    nxt = max(rid_nums, default=0) + 1
    for rtype, target in ((COMMENTS_EX_REL, "commentsExtended.xml"), (COMMENTS_IDS_REL, "commentsIds.xml")):
        if rtype not in have_types:
            etree.SubElement(rels, f"{{{REL_NS}}}Relationship", Id=f"rId{nxt}", Type=rtype, Target=target)
            nxt += 1
    parts["word/_rels/document.xml.rels"] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8",
                                                           standalone=True)
    tmp = str(path) + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        written = set()
        for item in infos:
            zout.writestr(item, parts[item.filename])
            written.add(item.filename)
        for name in (COMMENTS_EX_PART, COMMENTS_IDS_PART):
            if name not in written:
                zout.writestr(name, parts[name])
    os.replace(tmp, path)


def _calibri(run, size, bold=False):
    from docx.oxml.ns import qn
    from docx.shared import Pt
    run.font.name = "Calibri"
    run.font.size = Pt(size)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, fonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs"):
        fonts.set(qn(a), "Calibri")
    szcs = rpr.makeelement(qn("w:szCs"), {qn("w:val"): str(int(size * 2))})
    rpr.append(szcs)
