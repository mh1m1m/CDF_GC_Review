"""Self-test of the chat kit on a fictional memorandum: round 1, two owner returns, rounds 2 and 3.

Run through ``python cdfkit.py selftest``. Everything is synthetic and written under a temporary folder. A pass
proves that this sandbox can build, read back and append the Word and Excel files; it proves nothing about the
quality of a real review.
"""
from __future__ import annotations

import copy
import glob
import json
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECALC = False                      # the self-test skips the LibreOffice recalculation unless asked

PARAS = [
    "مذكرة تفاهم تجريبية بين صندوق التنمية الثقافي وشركة المثال للفعاليات",
    "التمهيد",
    "حيث إن الطرفين يرغبان في التعاون في مجال تطوير الفعاليات الثقافية، فقد اتفقا على ما يلي.",
    "المادة (1): الغرض",
    "1-1 تهدف هذه المذكرة إلى بحث فرص التعاون بين الطرفين في المجالات ذات الاهتمام المشترك.",
    "المادة (2): المدة",
    "2-1 تسري هذه المذكرة من تاريخ توقيعها وتتجدد تلقائياً لمدد مماثلة.",
    "المادة (3): التمويل",
    "3-1 يلتزم الصندوق بدعم وتمويل المبادرات المشتركة التي يقترحها الطرف الثاني.",
    "المادة (4): فريق العمل",
    "4-1 يشكل الطرفان فريق عمل يتولى اعتماد المبادرات والمعايير وآليات التقييم.",
    "المادة (5): البيانات",
    "5-1 يتبادل الطرفان البيانات اللازمة لتنفيذ هذه المذكرة.",
    "المادة (6): الإعلان",
    "6-1 يجوز لأي طرف استخدام اسم الطرف الآخر وشعاره بموافقة فريق العمل.",
    "المادة (7): الإنهاء",
    "7-1 يجوز لأي من الطرفين إنهاء هذه المذكرة بإشعار كتابي مدته ثلاثون يوماً.",
    "المادة (8): التعديل",
    "8-1 يجوز تعديل هذه المذكرة باتفاق الطرفين.",
    "المادة (9): أحكام عامة",
    "9-1 تحررت هذه المذكرة من نسختين أصليتين بيد كل طرف نسخة للعمل بموجبها.",
]
EDITS = {1: [("وتتجدد تلقائياً لمدد مماثلة", "ويجوز تجديدها باتفاق كتابي يوقعه الممثلون المفوضون للطرفين"),
             ("يلتزم الصندوق بدعم وتمويل المبادرات المشتركة", "يبحث الصندوق فرص دعم المبادرات المشتركة")],
         2: [("يتولى اعتماد المبادرات والمعايير وآليات التقييم", "يتولى التنسيق ورفع التوصيات")]}
ANSWERS = {1: {"01": ("تمت إضافة المسارات في الملحق.", "تم التطبيق"),
               "02": ("عُدّل البند (2-1).", "تم التطبيق"),
               "03": ("عُدّل البند (3-1) بصيغة بديلة.", "تم التطبيق بصيغة بديلة"),
               "04": ("نرى أن الصياغة كافية.", "لم يتم التطبيق"),
               "07": ("المدة مناسبة.", "لا ينطبق مع بيان المبرر")},
           2: {"03": ("أُضيف نص التقييم المستقل.", "تم التطبيق"),
               "04": ("عُدّل البند (4-1).", "تم التطبيق")}}
LATE = {
    "GCO-MOU-R1-001": ("لم ترد إفادة في هذه الجولة، وبقي البند (1-1) يحيل إلى المجالات ذات الاهتمام المشترك. والغرض ضبط "
                       "نطاق التعاون بمسارات معتمدة، والخطر: توسع النطاق دون اعتماد صاحب الصلاحية.",
                       "طلبنا في الجولتين الأولى والثانية ربط المجالات بمسارات محددة، ولم يُعدل النص. نوصي بإحلال "
                       "البند (1-1) بالنص المقترح أدناه.",
                       "1-1 تهدف هذه المذكرة إلى بحث فرص التعاون بين الطرفين في المسارات المحددة في الملحق (1)، ولا "
                       "يُضاف أي مسار إلا بملحق مكتوب يعتمده أصحاب الصلاحية لدى الطرفين."),
    "GCO-MOU-R1-003": ("أفادت الإدارة بإضافة نص التقييم المستقل، ولم يُعثر عليه في البند (3-1). والغرض استقلال قرار "
                       "التمويل، والخطر: فهم المذكرة وعداً بالتمويل.",
                       "طلبنا في الجولتين السابقتين خضوع التمويل للتقييم، وعُدّل البند جزئياً. نوصي بإحلال البند (3-1) "
                       "بالنص المقترح.",
                       "3-1 يبحث الصندوق فرص دعم المبادرات المشتركة التي يقترحها الطرف الثاني، وتخضع أي فرص تمويل "
                       "للتقييم وفقاً لمعايير الصندوق وإجراءاته المعتمدة، ولا تُعد المشاركة ضماناً للتمويل."),
}


def _make_doc(path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    d = Document()
    for t in PARAS:
        d.add_paragraph(t).alignment = WD_ALIGN_PARAGRAPH.RIGHT
    d.core_properties.author = "Owner Department"
    d.save(path)


def _owner_return(src_dir: Path, dst_dir: Path, r: int) -> dict:
    from docx import Document
    from openpyxl import load_workbook
    from cdf_gco_crms.config.round_schema import ordinal
    dst_dir.mkdir(parents=True, exist_ok=True)
    docx = Path(glob.glob(str(src_dir / "INTERNAL_DRAFT__*.docx"))[0])
    xlsx = Path(glob.glob(str(src_dir / "INTERNAL_DRAFT__*.xlsx"))[0])
    d = Document(docx)
    for p in d.paragraphs:
        for old, new in EDITS[r]:
            for run in p.runs:
                if old in run.text:
                    run.text = run.text.replace(old, new)
    d.core_properties.last_modified_by = "Owner Department"
    d.save(dst_dir / "returned.docx")
    wb = load_workbook(xlsx)
    ws = [w for w in wb.worksheets if w.title.startswith(("ملاحظات", "الملاحظات"))][0]
    hdr = {str(ws.cell(1, c).value or "").split("\n")[0]: c for c in range(1, ws.max_column + 1)}
    ct, cs = hdr[f"الإفادة او التحديث الحاصل – الجولة {ordinal(r)}"], hdr[f"حالة تطبيق الملاحظات – الجولة {ordinal(r)}"]
    for row in range(2, ws.max_row + 1):
        ans = ANSWERS[r].get(str(ws.cell(row, 1).value))
        if ans:
            ws.cell(row, ct).value, ws.cell(row, cs).value = ans
    wb.save(dst_dir / "returned.xlsx")
    shutil.copy(docx, dst_dir / "delivered.docx")
    shutil.copy(xlsx, dst_dir / "delivered.xlsx")
    return {k: str(dst_dir / f"{k.split('_')[0]}.{k.split('_')[1]}") for k in
            ("delivered_docx", "delivered_xlsx", "returned_docx", "returned_xlsx")}


def _two_paragraph_comment_docx(path: Path, ex_pid: str, parent_pid: str) -> None:
    """A minimal owner file: comment 0 has two paragraphs (paraIds 1A000001, 1A000002), comment 1 is a threaded
    reply. Word links w15:commentEx to the LAST paragraph of a comment, so a clean file names 1A000002 (kit 1.1.0
    regression for the G-SYNC structural check)."""
    import zipfile
    W_ = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
    W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
          'wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.'
          'wordprocessingml.comments+xml"/>'
          '<Override PartName="/word/commentsExtended.xml" ContentType="application/vnd.openxmlformats-'
          'officedocument.wordprocessingml.commentsExtended+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/></Relationships>')
    drels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
             'comments" Target="comments.xml"/>'
             '<Relationship Id="rId2" Type="http://schemas.microsoft.com/office/2011/relationships/commentsExtended" '
             'Target="commentsExtended.xml"/></Relationships>')
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W_}"><w:body><w:p>'
           '<w:commentRangeStart w:id="0"/><w:commentRangeStart w:id="1"/><w:r><w:t>نص تجريبي</w:t></w:r>'
           '<w:commentRangeEnd w:id="0"/><w:commentRangeEnd w:id="1"/>'
           '<w:r><w:commentReference w:id="0"/></w:r><w:r><w:commentReference w:id="1"/></w:r>'
           '</w:p></w:body></w:document>')
    com = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:comments xmlns:w="{W_}" xmlns:w14="{W14}">'
           '<w:comment w:id="0" w:author="Owner Department" w:initials="OD">'
           '<w:p w14:paraId="1A000001"><w:r><w:t>الفقرة الأولى من تعليق الإدارة</w:t></w:r></w:p>'
           '<w:p w14:paraId="1A000002"><w:r><w:t>الفقرة الثانية من تعليق الإدارة</w:t></w:r></w:p></w:comment>'
           '<w:comment w:id="1" w:author="Owner Department" w:initials="OD">'
           '<w:p w14:paraId="1A000003"><w:r><w:t>رد في السلسلة</w:t></w:r></w:p></w:comment></w:comments>')
    ex = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w15:commentsEx xmlns:w15="{W15}">'
          f'<w15:commentEx w15:paraId="{ex_pid}" w15:done="0"/>'
          f'<w15:commentEx w15:paraId="1A000003" w15:paraIdParent="{parent_pid}" w15:done="0"/></w15:commentsEx>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("[Content_Types].xml", ct), ("_rels/.rels", rels), ("word/_rels/document.xml.rels", drels),
                           ("word/document.xml", doc), ("word/comments.xml", com),
                           ("word/commentsExtended.xml", ex)):
            z.writestr(name, data)


def paraid_regression(root: Path) -> dict:
    """G-SYNC structural check on a two-paragraph owner comment with a threaded reply (kit 1.1.0)."""
    from cdf_gco_crms.word.document_comments import package_structure_problems
    root.mkdir(parents=True, exist_ok=True)
    good, bad = root / "two-paragraph-comment.docx", root / "dangling-commentEx.docx"
    _two_paragraph_comment_docx(good, "1A000002", "1A000002")       # as Word writes it: the last paragraph
    _two_paragraph_comment_docx(bad, "1A0000FF", "1A0000FE")         # a real defect must still be reported
    p_good = [p for p in package_structure_problems(good) if "commentsExtended" in p]
    p_bad = [p for p in package_structure_problems(bad) if "commentsExtended" in p]
    return {"ok": not p_good and len(p_bad) == 2, "clean_file_problems": p_good, "defect_file_problems": p_bad}


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
_W15 = "http://schemas.microsoft.com/office/word/2012/wordml"


def last_paragraph_problems(docx: str) -> dict:
    """Kit 1.1.0 writer rule ([MS-DOCX]): every GCO comment carries its w14:paraId and w14:textId on its LAST
    paragraph, its w15:commentEx names that id, and a reply's paraIdParent names its root's last-paragraph id."""
    import zipfile
    from lxml import etree
    from cdf_gco_crms.word.word_sync import GCO_AUTHOR, REF_RE
    with zipfile.ZipFile(docx) as z:
        com = etree.fromstring(z.read("word/comments.xml"))
        ex = etree.fromstring(z.read("word/commentsExtended.xml"))
    entries = {e.get(f"{{{_W15}}}paraId"): e for e in ex.findall(f"{{{_W15}}}commentEx")}
    problems, gco, replies = [], 0, 0
    last_pid_of_root = {}
    rows = []
    for c in com.findall(f"{{{_W}}}comment"):
        if c.get(f"{{{_W}}}author") != GCO_AUTHOR:
            continue
        paras = c.findall(f"{{{_W}}}p")
        text = "\n".join("".join(t.text or "" for t in p.iter(f"{{{_W}}}t")) for p in paras)
        m = REF_RE.search(text)
        pid = paras[-1].get(f"{{{_W14}}}paraId")
        rows.append((c.get(f"{{{_W}}}id"), m.group("id") if m else None, bool(m and m.group("fu")), pid))
        if m and not m.group("fu"):
            last_pid_of_root[m.group("id")] = pid
    for cid, iid, is_reply, pid in rows:
        gco += 1
        if not pid:
            problems.append(f"comment {cid}: no w14:paraId on its last paragraph")
            continue
        e = entries.get(pid)
        if e is None:
            problems.append(f"comment {cid}: no commentEx names its last paragraph {pid}")
        elif is_reply and iid in last_pid_of_root:
            replies += 1
            if e.get(f"{{{_W15}}}paraIdParent") != last_pid_of_root[iid]:
                problems.append(f"reply {cid}: paraIdParent {e.get(f'{{{_W15}}}paraIdParent')} != root "
                                f"last-paragraph id {last_pid_of_root[iid]}")
    return {"ok": not problems and gco > 0, "gco_comments": gco, "replies_checked": replies, "problems": problems[:5]}


def make_v100_style(src: str, dst: str) -> int:
    """Copy of a returned file whose GCO comments carry their thread key on the FIRST paragraph, as kit 1.0.0 wrote
    them (same values, so commentsExtended still names them). Returns the number of comments rewritten."""
    import zipfile
    from lxml import etree
    from cdf_gco_crms.word.word_sync import GCO_AUTHOR
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    com = etree.fromstring(parts["word/comments.xml"])
    n = 0
    for c in com.findall(f"{{{_W}}}comment"):
        paras = c.findall(f"{{{_W}}}p")
        if c.get(f"{{{_W}}}author") != GCO_AUTHOR or len(paras) < 2 or not paras[-1].get(f"{{{_W14}}}paraId"):
            continue
        for a in ("paraId", "textId"):
            v = paras[-1].attrib.pop(f"{{{_W14}}}{a}", None)
            if v:
                paras[0].set(f"{{{_W14}}}{a}", v)
        n += 1
    parts["word/comments.xml"] = etree.tostring(com, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for i in infos:
            z.writestr(i, parts[i.filename])
    return n


def dashboard_checks(xlsx: str) -> dict:
    """Kit 1.1.0 one-sheet dashboard, read back from the file: exactly two sheets (no helper sheet), gridlines hidden
    on both, the calculation block hidden from column R, every chart with plotVisOnly 0, alt text on every drawing,
    one card per observation, metadata of 09.4."""
    import re
    import zipfile
    from openpyxl import load_workbook
    from cdf_gco_crms.config import workbook_settings as W
    from cdf_gco_crms.ingestion.workbook_reader import calc_block, parse_workbook
    wb = load_workbook(xlsx)
    dash = wb[W.DASHBOARD_SHEET]
    hs, hdr = calc_block(wb)
    n = len(parse_workbook(xlsx).state.observations)
    with zipfile.ZipFile(xlsx) as z:
        charts = [z.read(p).decode() for p in z.namelist() if p.startswith("xl/charts/chart")]
        drawings = "".join(z.read(p).decode() for p in z.namelist() if re.fullmatch(r"xl/drawings/drawing\d+\.xml", p))
        core = z.read("docProps/core.xml").decode()
        app = z.read("docProps/app.xml").decode()
    cnv = re.findall(r"<(?:xdr:)?cNvPr [^>]*>", drawings)
    cards = sum(1 for c in dash["B"] if isinstance(c.value, str) and c.value.startswith("#") and c.font.sz == 16)
    checks = {
        "two sheets": len(wb.sheetnames) == 2 and W.HELPER_SHEET not in wb.sheetnames,
        "gridlines hidden": all(ws.sheet_view.showGridLines is False for ws in wb.worksheets),
        "block from R, hidden": hs is dash and min(hdr.values()) >= W.CALC_FIRST_COL and all(
            dash.column_dimensions[dash.cell(row=1, column=c).column_letter].hidden for c in hdr.values()),
        "plotVisOnly 0": bool(charts) and all(re.search(r'plotVisOnly val="0"', c) for c in charts),
        "alt text": bool(cnv) and all(re.search(r'descr="[^"]{6,}"', t) and 'descr="Picture"' not in t for t in cnv),
        "cards": cards == n,
        "metadata": bool(re.search(r"<dc:creator[^>]*>Mohammed Alsaleh</dc:creator>", core)) and
                    bool(re.search(r"<cp:lastModifiedBy[^>]*>Mohammed Alsaleh</cp:lastModifiedBy>", core)) and
                    "<Company>صندوق التنمية الثقافي</Company>" in app and "openpyxl" not in (core + app).lower(),
    }
    return {"ok": all(checks.values()), "checks": checks, "charts": len(charts), "drawings": len(cnv), "cards": cards}


def _round_args(files: dict, reg: Path) -> list[str]:
    return ["--register", str(reg), "--delivered-xlsx", files["delivered_xlsx"], "--returned-xlsx",
            files["returned_xlsx"], "--delivered-docx", files["delivered_docx"], "--returned-docx",
            files["returned_docx"]]


def run(keep: str | None = None) -> dict:
    import contextlib
    import io
    import cdfkit as K
    root = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="cdfkit-selftest-"))
    root.mkdir(parents=True, exist_ok=True)
    steps = []

    def call(name, argv, want=(0, 4)):
        buf = io.StringIO()
        if not RECALC and argv[0] in ("build", "next"):
            argv = argv + ["--no-recalc"]
        with contextlib.redirect_stdout(buf):
            try:
                rc = K.main(argv)
            except SystemExit as exc:                          # commands stop with SystemExit(code) on input errors
                rc = exc.code if isinstance(exc.code, int) else 2
        try:
            out = json.loads(buf.getvalue())
        except ValueError:
            out = {"raw": buf.getvalue()[-2000:]}
        ok = rc in want
        detail = out.get("detail") or out.get("problems")
        if not ok and not detail:                              # say which gates stopped it
            detail = [g for g in (out.get("gates_not_passed") or []) if "FAIL" in json.dumps(g)] or \
                out.get("gates_not_passed") or out.get("raw")
        steps.append({"step": name, "rc": rc, "ok": ok, "gate_counts": out.get("gate_counts"), "detail": detail})
        return rc, out

    pr = paraid_regression(root / "paraid")
    steps.append({"step": "G-SYNC: commentsExtended resolves to the last paragraph of a two-paragraph owner comment "
                          "with a threaded reply", "ok": pr["ok"], "rc": None,
                  "detail": None if pr["ok"] else pr})

    doc = root / "mou.docx"
    _make_doc(doc)
    call("read", ["read", str(doc), "--out", str(root / "w")], (0,))
    call("check", ["check", str(HERE / "examples/draft-round1.example.json"), "--doc", str(doc), "--out",
                   str(root / "w")], (0,))
    bad = json.loads((HERE / "examples/draft-round1.example.json").read_text(encoding="utf-8"))
    bad["observations"][0]["recommendation"] = "أرى أن البند → باطل"
    bad["observations"][0]["lens_category"] = ""
    (root / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    call("check catches defects", ["check", str(root / "bad.json"), "--doc", str(doc)], (1,))
    q = json.loads((HERE / "examples/draft-round1.example.json").read_text(encoding="utf-8"))
    q["observations"][5].update(form="F6", recommendation="هل مدة الإشعار مناسبة للإدارة صاحبة الطلب؟")
    (root / "question.json").write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
    call("v7.15: check refuses a new comment that asks a question (07.4A(d))",
         ["check", str(root / "question.json"), "--doc", str(doc)], (1,))
    call("build round 1", ["build", str(HERE / "examples/draft-round1.example.json"), "--doc", str(doc), "--out",
                           str(root / "r1")])
    r1_x = glob.glob(str(root / "r1" / "INTERNAL_DRAFT__*.xlsx"))
    dc = dashboard_checks(r1_x[0]) if r1_x else {"ok": False, "checks": "no workbook"}
    steps.append({"step": "one-sheet dashboard read back (two sheets, hidden block, plotVisOnly 0, alt text, cards, "
                          "metadata)", "ok": dc["ok"], "rc": None, "detail": None if dc["ok"] else dc})
    # the states of spec 9 build into the two-sheet workbook and read back clean
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    from cdf_gco_crms.regression.synthetic import dashboard_states
    bad9 = {}
    for name, st9 in dashboard_states().items():
        p9 = root / "spec9" / f"{name}.xlsx"
        try:
            build_workbook(st9, p9, working_copy=True)
            if st9.observations:
                d9 = dashboard_checks(str(p9))
                if not d9["ok"]:
                    bad9[name] = d9["checks"]
        except Exception as exc:                               # noqa: BLE001
            bad9[name] = f"{type(exc).__name__}: {exc}"
    steps.append({"step": "spec 9 states build (all open, all conditional, five rounds, all closed, no observation)",
                  "ok": not bad9, "rc": None, "detail": bad9 or None})
    f1 = _owner_return(root / "r1", root / "ret1", 1)
    rc, intake = call("intake round 2", ["intake", *_round_args(f1, root / "r1/register.json"), "--out",
                                         str(root / "i2")], (0,))
    flags = {r["reader_no"]: r["flags"] for r in intake.get("rows", [])}
    steps.append({"step": "I-01 claim without change detected", "ok": bool(flags.get("01")), "rc": None})
    r2 = json.loads((HERE / "examples/round-n.example.json").read_text(encoding="utf-8"))
    (root / "round2.json").write_text(json.dumps(r2, ensure_ascii=False), encoding="utf-8")
    rc, out2 = call("next round 2", ["next", str(root / "round2.json"), *_round_args(f1, root / "r1/register.json"),
                                     "--out", str(root / "r2")])
    r2_docx = glob.glob(str(root / "r2" / "INTERNAL_DRAFT__*.docx"))
    lp = last_paragraph_problems(r2_docx[0]) if r2_docx else {"ok": False, "problems": ["no round-2 Word file"]}
    steps.append({"step": "Word writer: thread key on the last paragraph of every GCO comment and reply ([MS-DOCX])",
                  "ok": lp["ok"] and lp.get("replies_checked", 0) > 0, "rc": None, "detail": None if lp["ok"] else lp})
    # a round-2 build on a returned file written by kit 1.0.0 (thread keys on the first paragraph) finds its roots
    legacy = dict(f1)
    legacy["returned_docx"] = str(root / "ret1" / "returned-v100.docx")
    n_legacy = make_v100_style(f1["returned_docx"], legacy["returned_docx"])
    rc, outL = call("next round 2 on a kit 1.0.0 returned file", ["next", str(root / "round2.json"),
                                                                  *_round_args(legacy, root / "r1/register.json"),
                                                                  "--out", str(root / "r2-v100")])
    def _word(o):
        w_ = o.get("word") or {}
        return json.loads(w_) if isinstance(w_, str) else w_
    wL, w2 = _word(outL), _word(out2)
    rL = glob.glob(str(root / "r2-v100" / "INTERNAL_DRAFT__*.docx"))
    lpL = last_paragraph_problems(rL[0]) if rL else {"ok": False, "problems": ["no Word file"]}
    okL = (n_legacy > 0 and wL.get("roots_missing") == 0 and wL.get("roots_found") == w2.get("roots_found")
           and (w2.get("roots_found") or 0) > 0 and lpL["ok"])
    steps.append({"step": "round-2 roots found in a kit 1.0.0 file and its keys moved to the last paragraph", "ok": okL,
                  "rc": None, "detail": None if okL else {"legacy_comments": n_legacy, "word": wL, "check": lpL}})
    f2 = _owner_return(root / "r2", root / "ret2", 2)
    rc, intake3 = call("intake round 3", ["intake", *_round_args(f2, root / "r2/register.json"), "--out",
                                          str(root / "i3")], (0,))
    c16 = {c["reader_no"]: c["status"] for c in intake3.get("closed_text_16_1", [])}
    steps.append({"step": "16.1 closed text intact (#02 on its closure text)", "ok": c16.get("02") == "INTACT",
                  "rc": None, "detail": c16})
    r3 = {"round": 3, "date": "2026-10-28", "document_version": "الإصدار 0.3", "assessments": [], "new_observations": []}
    wrong = copy.deepcopy(r3)
    wrong["assessments"] = [{"internal_id": "GCO-MOU-R1-003", "status": "مغلقة", "closure_path": "VERIFIED_TEXT",
                             "closure_text": "تخضع أي فرص تمويل للتقييم", "feedback": "أُضيف نص التقييم."}]
    (root / "round3-wrong.json").write_text(json.dumps(wrong, ensure_ascii=False), encoding="utf-8")
    call("next refuses a closure on text that is not there", ["next", str(root / "round3-wrong.json"),
                                                              *_round_args(f2, root / "r2/register.json"),
                                                              "--out", str(root / "r3-wrong")], (1,))
    for iid in ("GCO-MOU-R1-001", "GCO-MOU-R1-003"):
        c, rec, txt = LATE[iid]
        r3["assessments"].append({"internal_id": iid, "status": "يتطلب تعديل" if iid.endswith("3") else "مفتوحة",
                                  "comment": c, "recommendation": rec, "proposed_text": txt})
    r3["assessments"].append({"internal_id": "GCO-MOU-R1-004", "status": "مغلقة", "closure_path": "VERIFIED_TEXT",
                              "closure_text": "يتولى التنسيق ورفع التوصيات",
                              "feedback": "عُدّل البند (4-1) وأصبح دور فريق العمل التنسيق ورفع التوصيات."})
    for iid in ("GCO-MOU-R1-005", "GCO-MOU-R1-006", "GCO-MOU-R1-008"):
        r3["assessments"].append({"internal_id": iid, "status": "مفتوحة",
                                  "comment": "لم ترد إفادة ولم يُعدل النص في الجولتين السابقتين. والخطر: بقاء الفجوة.",
                                  "recommendation": "نوصي بتطبيق التوصية الواردة في الجولة الأولى.",
                                  "proposed_text": "يُدرج النص وفق التوصية."})
    r3["new_observations"] = [{
        "quote": "يتولى التنسيق ورفع التوصيات", "location": "المادة (4) – البند (4-1)",
        "title": "توثيق توصيات فريق العمل", "form": "F1", "observation_type": "IMPROVEMENT",
        "analysis": "لا يبين البند المعدل كيف توثق توصيات الفريق.",
        "recommendation": "نقترح النص على توثيق توصيات الفريق في محاضر معتمدة.",
        "proposed_wording": "وتوثق توصيات الفريق في محاضر يعتمدها ممثلا الطرفين.",
        "closure_action": "إضافة حكم التوثيق إلى البند (4-1) أو بيان المبرر.",
        "reason": "أُثيرت بعد تعديل البند (4-1) في الجولة الثانية.", "lens_category": "c", "severity": "LOW",
        "severity_basis": "غياب توثيق التوصيات (4-1).",
        "materiality_test": {"q1_lens": True, "q2_worse_off": True, "q3_handled_elsewhere": False,
                             "q4_duplicate": False},
        "searched_clauses": ["(4-1)", "(9-1)"], "target_clauses": ["(4-1)"], "edit_type": "insert after (4-1)",
        "conflicts_checked": "لا تعارض"}]
    (root / "round3.json").write_text(json.dumps(r3, ensure_ascii=False), encoding="utf-8")
    rc, out3 = call("next round 3", ["next", str(root / "round3.json"), *_round_args(f2, root / "r2/register.json"),
                                     "--out", str(root / "r3")])
    steps.append({"step": "round 3 closure counts", "ok": out3.get("closure_counts") is not None, "rc": None,
                  "detail": out3.get("closure_counts")})
    # scanned source (02.6A): an image-only PDF, the assistant's transcription, the guards
    from PIL import Image
    scan = root / "scan"
    scan.mkdir(exist_ok=True)
    Image.new("RGB", (1240, 1754), "white").save(scan / "scanned.pdf")
    call("read stops on a scanned PDF", ["read", str(scan / "scanned.pdf"), "--out", str(scan)], (2,))
    call("pages renders (or says no renderer)", ["pages", str(scan / "scanned.pdf"), "--out", str(scan / "pages")],
         (0, 2))
    (scan / "transcript.txt").write_text("=== صفحة 1 ===\n" + "\n".join(PARAS[:-1]) +
                                         "\n9-1 تحررت هذه المذكرة من نسختين أصليتين بيد كل طرف نسخة للعمل [؟].",
                                         encoding="utf-8")
    rc, tr = call("transcript", ["transcript", str(scan / "transcript.txt"), "--source", str(scan / "scanned.pdf"),
                                 "--out", str(scan / "t"), "--platform", "selftest"], (0,))
    tdoc = tr.get("review_docx", "")
    call("check on the transcription", ["check", str(HERE / "examples/draft-round1.example.json"), "--doc", tdoc],
         (0,))
    bad2 = json.loads((HERE / "examples/draft-round1.example.json").read_text(encoding="utf-8"))
    bad2["observations"][7]["quote"] = "نسخة للعمل [؟]"
    (scan / "bad.json").write_text(json.dumps(bad2, ensure_ascii=False), encoding="utf-8")
    call("check refuses a quote with [؟]", ["check", str(scan / "bad.json"), "--doc", tdoc], (1,))
    call("build on the transcription", ["build", str(HERE / "examples/draft-round1.example.json"), "--doc", tdoc,
                                        "--out", str(scan / "r1")])
    call("issue refused without --quotes-confirmed", ["build", str(HERE / "examples/draft-round1.example.json"),
                                                      "--doc", tdoc, "--out", str(scan / "iss"), "--issue",
                                                      "--decision", "test"], (3,))
    # review stages (19A, 19B, 20): issue refused without them, allowed with them, refused again when stale
    proto = root / "mini-protocol.txt"
    proto.write_text("VERSION: 7.14 | ISSUED: test\n"
                     "ARTICLE 03A — LENS\n03A.1 test\nARTICLE 04 — MATERIALITY\n04.4 test\nARTICLE 05 — LAW\n05.1 test\n"
                     "ARTICLE 07 — STANDARD\n07.4 test\nARTICLE 19A — CHALLENGE\n19A.6 test\n"
                     "ARTICLE 19B — MAT\n19B.4 test\nARTICLE 20 — READ\n20.4 test\n"
                     "ANNEX F — EXEMPLARS\nF.1 test\nANNEX G — MAT PROFILE\nG.0 test\nEND OF ANNEX G\n"
                     "END OF PROTOCOL — test\n", encoding="utf-8")
    sd = root / "stages"
    sd.mkdir(exist_ok=True)
    draft = sd / "draft.json"
    draft.write_text((HERE / "examples/draft-round1.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    call("issue refused without stages", ["build", str(draft), "--doc", str(doc), "--out", str(sd / "x"), "--issue",
                                          "--decision", "test"], (3,))
    for st in ("MAT-01", "CHALLENGE"):
        call(f"packet {st}", ["stage-packet", st, "--draft", str(draft), "--protocol", str(proto), "--doc", str(doc),
                              "--out", str(sd / "pk")], (0,))
    d = json.loads(draft.read_text(encoding="utf-8"))
    ids = [o["id"] for o in d["observations"]]
    prof = d["stage_packets"]["MAT-01"]["profile"]["line"]

    def answer(name, obj):
        f = sd / f"{name}.json"
        f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return str(f)
    call("record MAT-01", ["stage-record", "MAT-01", answer("m1", {"stage": "MAT-01", "profile": prof, "positions": [
        {"id": i, "position": "KEEP", "advice": "-", "suggested_text": None} for i in ids]}), "--draft", str(draft)], (0,))
    recs = [{"id": i, "objection": None, "ground": None, "evidence": None, "response": None, "revision": None,
             "cycles": 0} for i in ids]
    recs[1].update({"objection": "x", "ground": "19A.4", "evidence": "¶7", "response": "y", "cycles": 1})
    call("record CHALLENGE", ["stage-record", "CHALLENGE", answer("ch", {"stage": "CHALLENGE", "records": recs}),
                              "--draft", str(draft)], (0,))
    for st in ("MAT-02", "MAT-03"):
        call(f"packet {st}", ["stage-packet", st, "--draft", str(draft), "--protocol", str(proto), "--out",
                              str(sd / "pk")], (0,))
        call(f"record {st}", ["stage-record", st, answer(st, {"stage": st, "profile": prof, "positions": [
            {"id": ids[1], "position": "KEEP", "advice": "-", "suggested_text": None}]}), "--draft", str(draft)], (0,))
    call("packet ADJUDICATE", ["stage-packet", "ADJUDICATE", "--draft", str(draft), "--protocol", str(proto), "--out",
                               str(sd / "pk")], (0,))
    call("record ADJUDICATE", ["stage-record", "ADJUDICATE", answer("adj", {"stage": "ADJUDICATE", "dispositions": [
        {"id": i, "disposition": "UPHELD_UNCHANGED", "rationale": "-"} for i in ids]}), "--draft", str(draft)], (0,))
    call("build working copy", ["build", str(draft), "--doc", str(doc), "--out", str(sd / "wc")])
    wb = glob.glob(str(sd / "wc" / "INTERNAL_DRAFT__*.xlsx"))[0]
    call("packet READ", ["stage-packet", "READ", "--draft", str(draft), "--protocol", str(proto), "--workbook", wb,
                         "--out", str(sd / "pk")], (0,))
    nos = json.loads(draft.read_text(encoding="utf-8"))["stage_packets"]["READ"]["comments"]
    good = {n: {"R1": 1, "R2": 0, "R3": 1, "R4": 1, "R5": 1, "R6": 0, "R7": 1} for n in nos}
    call("record READ", ["stage-record", "READ", answer("rd", {"stage": "READ", "seed": 7, "sample": nos,
                                                               "scores": good, "scan_findings": []}),
                         "--draft", str(draft)], (0,))
    call("issue with every stage", ["build", str(draft), "--doc", str(doc), "--out", str(sd / "issued"), "--issue",
                                    "--decision", "test"])
    d = json.loads(draft.read_text(encoding="utf-8"))
    d["observations"][0]["recommendation"] += " مثلاً"
    draft.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    call("issue refused after an edit (stale read)", ["build", str(draft), "--doc", str(doc), "--out",
                                                      str(sd / "stale"), "--issue", "--decision", "test"], (3,))
    ok = all(s["ok"] for s in steps)
    return {"status": "PASS" if ok else "FAIL", "folder": str(root), "steps": steps,
            "note": "synthetic data only; a pass proves the sandbox can run the engine, not the quality of a review"}
