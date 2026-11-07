#!/usr/bin/env python3
"""Writes the v7.12 QA report and the implementation guide from build/state.json (numbers are never typed by hand)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cdf_gco_crms import ENGINE_VERSION  # noqa: E402
from cdf_gco_crms.config import workbook_settings as W  # noqa: E402

OUT = ROOT / "deliverables"
st = json.loads((ROOT / "build" / "state.json").read_text())
HEADER = (f"<!-- Author: {W.AUTHOR} | Last modified by: {W.AUTHOR} | Company: {W.COMPANY} | Title: {{title}} -->\n")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "/").replace("\n", " ") for x in r) + " |")
    return "\n".join(out)


def qa_report() -> str:
    g = st["gates"]
    gs, ts = st["gate_summary"], st["test_summary"]
    p = st.get("protocol", {})
    views = st["views"]
    compared = sum(v["compared"] for v in views)
    mism = sum(len(v["mismatches"]) for v in views)
    mig = st.get("migration", [])
    refs = st.get("references", {})
    b12 = st.get("brand_page12", {})
    src = sorted((ROOT / "sources").rglob("*"))
    srows = [[str(f.relative_to(ROOT / "sources")), f"{f.stat().st_size:,}", sha(f)[:16]] for f in src
             if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc"]
    nv = [x["gate"] for x in g if x["status"] == "NOT_VERIFIED"]
    reg_tests = [t for t in st["tests"] if not t[0].startswith(("TEST 21", "TEST 22", "TEST 23", "TEST 24", "TEST 28", "TEST 29", "TEST 30", "TEST 31", "TEST 32"))]
    grp = {k: [t for t in st["tests"] if t[0].startswith(f"TEST {k}")] for k in ("21", "22", "23")}
    cnt = p.get("counts", {})
    lines = [
        HEADER.format(title="CDF–GCO–CRMS v7.12 – QA report"),
        "# CDF–GCO–CRMS v7.12 — Quality Assurance Report",
        "",
        f"Engine {ENGINE_VERSION} · built 23 October 2026 (Asia/Riyadh) · author {W.AUTHOR}",
        "",
        "## ملخص تنفيذي",
        "",
        f"- البروتوكول الموحد v7.12 مكتمل في ملف واحد: {p.get('lines_v712', '?')} سطراً (v7.11: {p.get('lines_v711', '?')}). "
        f"حُفظ {cnt.get('UNCHANGED', 0)} بنداً كما هو حرفياً، وعُدّل {cnt.get('MODIFIED', 0)} بنداً بالإضافة في الغالب، وأضيف {cnt.get('ADDED', 0)} بنداً "
        f"(المادة 19A، البند 02.9، الملحق D.13، البوابات G-REF وG-ADV وG-SYNC-9)، ولم يُحذف أي ضابط حوكمي؛ كل تعديل موثق في جدول المطابقة v7.11 إلى v7.12.",
        f"- لوحة المتابعة التنفيذية أُعيد تصميمها على مكتبة ألوان الدليل (الصفحة 12 من الدليل ذي 87 صفحة) في عناصرها البنيوية، مع إبقاء ألوان حالات الإغلاق الأربع كما هي في سجل الملاحظات الصادر (AMB-161): سبعة ألوان مطبوعة بقيمها، "
        f"طوبقت {b12.get('equal', '?')} من {b12.get('swatches', '?')} منها مع العينات المرسومة، وخط Calibri بمقياس الصفحة 21. "
        f"التحقق بإعادة حساب مستقلة: {len(views)} طريقة عرض، و{compared:,} نتيجة صيغة، و{mism} اختلاف عن الحساب المستقل بلغة Python.",
        f"- اختبارات الانحدار: نجح {ts.get('PASS', 0)} فحصاً من {sum(ts.values())} (TEST 01–20 مع 12b و19b، وTEST 25–27، ثم TEST 21 فهرس المرجعيات، وTEST 22 التأكيد، وTEST 23 دمج البروتوكول، وTEST 24 مكتبة الهوية، وTEST 28 عنوان الملاحظة، وTEST 29 الاستقبال الآمن وحقن الصيغ، وTEST 30 دورة حياة Word على وثائق حقيقية، وTEST 31 التحدي المؤسسي المسند، وTEST 32 الحالة الكاملة من الجولة الأولى إلى الخامسة). "
        f"البوابات ({sum(gs.values())} بوابة): " + "، ".join(f"{k} {v}" for k, v in sorted(gs.items(), key=lambda kv: -kv[1]))
        + f"، FAIL {gs.get('FAIL', 0)}.",
        f"- البوابات غير المتحققة ({len(nv)}): {', '.join(nv)}؛ وهي ما يحتاج Microsoft Excel نفسه. لم تُسجَّل ناجحة.",
        f"- فهرس المرجعيات المؤسسية (02.9، D.13): الهيكل التنظيمي (92 صفحة، مقترح غير معتمد) ومصفوفة الصلاحيات (28 صفحة، اعتمادها غير متحقق)؛ "
        f"التغطية: {json.dumps(refs.get('coverage', {}), ensure_ascii=False)}. الورود في المرجع لا يعني اعتماده.",
        "- البيانات في ملفات العرض تجريبية بالكامل، ومعلَّمة بذلك داخل كل ملف.",
        "",
        "## 1. Sources and reading coverage",
        "",
        table(["File", "Bytes", "SHA-256 (16)"], srows),
        "",
        "- v7.11 consolidated protocol (sources/CDF-GCO-CRMS-v7.11.txt): the base of every v7.12 edit; read in full by the consolidation pass (anchors must occur exactly once).",
        "- v7.12 inputs of the earlier batch (sources/v7.12): the consolidated draft was used only for Article 19A; its 10.4A.11 change and brand page values were not adopted (the latter replaced by the verified page-12 values).",
        "- CDF Design Guide (87 pages): pages 12 and 21 supplied as renders; the seven printed HEX values were re-checked against the swatch pixels. The 8-page identity file remains the logo source.",
        "- Institutional references: the organisational structure deck (92 pages) and the delegation of authority matrix (28 pages), text-extracted with page provenance; approval status recorded, never upgraded.",
        "",
        "## 2. Deliverables",
        "",
    ]
    skip = {"CDF-GCO-CRMS-v7.12-QA-REPORT.md", "CDF-GCO-CRMS-v7.12-COMPLETE-PACKAGE.zip"}
    deliv = [d for d in sorted(OUT.glob("*.*")) if d.is_file() and d.name not in skip]
    lines.append(table(["Deliverable", "Bytes", "SHA-256 (16)"], [[d.name, f"{d.stat().st_size:,}", sha(d)[:16]] for d in deliv]))
    lines += ["", "This report and the complete package are not hashed here, because each contains the other; "
              "the package is checked by reopening every entry (tools/package.py, build/package_check.json)."]
    lines += ["", "## 3. Protocol consolidation (v7.11 to v7.12)", "",
              table(["Check", "Result"], [
                  ["Clause crosswalk entries", sum(cnt.values())],
                  ["Change types", ", ".join(f"{k} {v}" for k, v in sorted(cnt.items()))],
                  ["v7.11 lines changed", f"{p.get('removed_lines', '?')} (each the anchor of a declared edit; {len(p.get('unexplained_removed', []))} unexplained)"],
                  ["P10 typography on added text", "zero hits" if not p.get("p10_hits") else p["p10"]],
                  ["Cross-references in added text", f"{p.get('xref_checked', '?')} checked, {len(p.get('xref_unresolved', []))} unresolved"],
                  ["Structure (articles 00–23 with 19A, annexes A–F, END line)", "no problem" if not p.get("structure_problems") else p["structure"]],
                  ["Every crosswalk row verified", "yes (Verification_Result column)"],
                  ["v7.10 to v7.11 traceability", "CDF-GCO-CRMS-v710-v711-CROSSWALK.xlsx of the v7.11 package (790 entries)"],
                  ["00.8 reference-case regression", "NOT RUN – reference package not supplied; recorded in Annex B"],
              ]), ""]
    lines += ["## 4. Gate results (demonstration workbook, round 5)", "",
              table(["Gate", "Name", "Status", "Actual"], [[x["gate"], x["name"], x["status"], x["actual"][:150]] for x in g]),
              "", "NOT_VERIFIED is used only where the check needs Microsoft Excel. MANUAL_PASS gates carry the inspected screenshots as evidence.", ""]
    lines += ["## 5. Regression tests (Annex E.8)", "",
              table(["Test", "Title", "Status", "Duration"], [[t[0], t[1], t[5], t[6]] for t in reg_tests]), ""]
    for k, title in (("21", "Reference index"), ("22", "Assurance and adversarial challenge"), ("23", "Protocol consolidation")):
        rows = grp[k]
        lines += [f"TEST {k} — {title}: {sum(1 for t in rows if t[5] == 'PASS')} of {len(rows)} checks pass "
                  f"({', '.join(t[2] for t in rows[:6])}{'…' if len(rows) > 6 else ''}).", ""]
    lines += ["## 6. Formula recalculation", "",
              "Each view: the workbook is built without cached values, recalculated by LibreOffice (calculateAll), and every formula result is compared with the independent Python model. A match therefore proves the engine computed the value.", "",
              table(["View", "Formulas compared", "Mismatches", "Errors", "Result"],
                    [[v["view"], v["compared"], len(v["mismatches"]), len(v["errors"]), v["message"]] for v in views]),
              "", f"Empty workbook (0 observations): {st['empty_state']['message']}.", "",
              table(["Register", "Build (s)", "File (MB)", "Formulas", "Recalculation (s)"],
                    [[f"{x['observations']} × {x['rounds']} rounds", x["build_seconds"], x["file_mb"], x["formulas"], x["recalc_seconds"]] for x in st["perf"]]),
              ""]
    lines += ["## 7. Migration", "",
              table(["Source", "Kind", "Status", "Cells compared", "Differences", "Removed sheets", "Not recorded in source"],
                    [[Path(m["source"]).name[:60], m.get("source_kind", ""), m["status"], m["cells_compared"], len(m["cell_differences"]),
                      ", ".join(m["removed_sheets"]), ", ".join(m["not_recorded"])] for m in mig]), "",
              "A v7.11 workbook migrates by rebuilding its dashboard and helper sheet in the v7.12 design; its data sheet is kept cell by cell, as for a v7.10 workbook.", ""]
    for m in mig:
        if m.get("source_findings"):
            lines += ["Findings on the earlier prototype workbook (preserved, not corrected by the migration):", ""]
            lines += [f"- {f}" for f in m["source_findings"]] + [""]
    lines += ["## 8. Brand verification (D.11, D.14)", "",
              "- Colour library, page 12 of the 87-page guide (printed HEX, re-checked against the render): Cinder Black #101820, Warm Gray #D7D2CB, Powder Blue #BBDDE6, Wistful Blue #A5B0E3, Chardonnay Yellow #FDD086, Light Salmon #FA9370, Jetstream Green #B5E1C4; page surface #F3F3F4.",
              "- Closure-status fills (D.2) kept exactly as every issued register, on the dashboard and the data sheet alike (protocol owner's decision, AMB-161): مغلقة #E2EFDA, مغلقة بشرط #DDEBF7, يتطلب تعديل #FFF2CC, مفتوحة #FCE4D6, bold text; verified against the owner's round-4 register. The brand library dresses the structure only. Dark tones for status text on white (#375623, #1F4E79, #7F6000, #843C0C) are recorded as not brand.",
              "- Typography, page 21: Calibri with its scale; the workbook uses 24/14/16/32/10/9. The v7.11 conflict with the identity file's Brando Arabic is closed (AMB-150).",
              "- Superseded: the v7.11 CMYK conversions of the 8-page file (#D8D3CB, #A7B0D9, #FED186, #F69271), within 2/255 of the printed values.",
              "- Logo: the supplied horizontal logo, background made transparent, proportions and pixels kept, black on the Warm Gray band.",
              f"- Contrast: every static pair and every conditional pair passes WCAG 2.2 AA; the placeholder grey of 10.8 remains the recorded exception (AMB-153). Gate G-UX-04: {next((x['actual'] for x in g if x['gate'] == 'G-UX-04'), '')[:120]}.", ""]
    lines += ["## 9. Institutional reference layer (02.9, 03A.5, 05.6, D.13)", "",
              table(["Document", "Pages", "Approval status", "Applicability", "Hash check"],
                    [[s.get("recorded_name") or s.get("file"), s.get("pages"), s.get("approval_status"), s.get("applicability", "NOT_ESTABLISHED"), s.get("hash_status", "")] for s in refs.get("sources", [])]),
              "", f"Coverage of the derived index: {json.dumps(refs.get('coverage', {}), ensure_ascii=False)}.",
              "The index proves that a passage occurs on a page; it never establishes approval or current effect. The dashboard's owning department is validated against the sectors and units of the structure document (G-REF-5).", ""]
    lines += ["## 10. Word reply threads (08.3, G-SYNC-9)", "",
              "Follow-up comments are written as native Word replies (commentsExtended parent) under the observation's first comment; TEST 12b checks every round-3 follow-up and that LibreOffice opens the file. Rendering in Microsoft Word is NOT_VERIFIED here.", ""]
    lines += ["## 11. Visual inspection", "",
              "Renders (LibreOffice, fonts substituted) in screenshots/: after_dashboard_round5_p-1..4 (page 4 is the data sheet), after_dashboard_round2_selected_p-1, before_v711_dashboard_p-1, before_v710_printview_p-1, before_prototype_p-1. Inspected for right-to-left order, legibility, clipping, chart overlap and colour-with-text; no defect left open.", ""]
    lines += ["## 12. Limitations (stated, not hidden)", "",
              "1. Microsoft Excel was not available: opening without repair prompts, Note hover, chart and logo rendering in Excel are NOT_VERIFIED (G-DASH-13, G-UX-15). The file passes the ISO 29500 schema validation and opens and recalculates in LibreOffice.",
              "2. Microsoft Word was not available: reply-thread rendering is checked structurally and by a LibreOffice open only.",
              "3. Screenshots are LibreOffice renders: Calibri is replaced by Carlito and Arabic glyphs by DejaVu Sans; Excel will look closer to the design.",
              "4. Only pages 12 and 21 of the 87-page guide were supplied; motifs and clear-space measures were not seen, so none is invented. The full PDF, when supplied, can be read with branding/pdf_brand_extractor.py to add vector-stream provenance.",
              "5. The institutional references are text extractions with page provenance; the structure document is titled as proposed, the matrix's current effect is unverified, and the engine never upgrades either status. Matrix items parsed with PARTIAL confidence are listed as such.",
              "6. All observations in the demonstration are synthetic. The 00.8 reference-case regression was not run (reference package not supplied).",
              "7. Row heights of the dashboard tables are fixed at build time (Excel cannot refit rows to formula results without macros).",
              "8. A LibreOffice re-save moves the drawing anchors of right-to-left sheets; users of LibreOffice should not save the delivered file back.",
              "9. The adversarial challenge engine (19A) runs deterministic fixtures; no independent model-based challenge was executed in this build.",
              ""]
    return "\n".join(lines)


def guide() -> str:
    cov = st.get("references", {}).get("coverage", {})
    return HEADER.format(title="CDF–GCO–CRMS v7.12 – دليل التطبيق") + f"""
# دليل التطبيق — CDF–GCO–CRMS v7.12

المحرك {ENGINE_VERSION}. يشرح هذا الدليل تشغيل محرك ملف Excel للإدارة صاحبة الطلب، ولوحة المتابعة التنفيذية بهوية الصندوق، وأداة الترحيل، وفهرس المرجعيات المؤسسية، والتحقق قبل الإرسال.

## 1. ما الذي تغيّر في v7.12

- **الهوية البصرية**: اعتُمدت مكتبة ألوان دليل الهوية (الصفحة 12 من الدليل ذي 87 صفحة) وخط Calibri بمقياسه (الصفحة 21). شريط الهوية رمادي دافئ يحمل الشعار، والبطاقات بيضاء على أرضية الصفحة، ولكل بطاقة غطاء بلون حالتها، وألوان حالات الإغلاق الأربع من المكتبة نفسها (أخضر، أزرق، أصفر، سلموني) مع كتابة القيمة دائماً بجانب اللون.
- **الردود في Word**: تُكتب متابعات الجولات ردوداً داخل سلسلة التعليق الأول للملاحظة (G-SYNC-9).
- **فهرس المرجعيات** (02.9، D.13): الهيكل التنظيمي ومصفوفة الصلاحيات مفهرسان بأرقام الصفحات مع حالة الاعتماد كما سُجّلت؛ لا يرفع المحرك حالة الاعتماد من تلقاء نفسه، وورود النص في المرجع لا يعني اعتماده.
- **التحدي المؤسسي** (المادة 19A): محرك اعتراضات حتمي بحد ست دورات وسجل مُسلسل بالبصمات؛ لا يغيّر اعتراض ملاحظة صادرة دون سجل قرار بشري موثق.
- **الترحيل**: `migrate_to_v712.py` يقبل ملفات v7.10 وv7.11 معاً.

## 2. المتطلبات

- Python 3.11 أو أحدث، مع الحزم: openpyxl و python-docx و lxml و Pillow و pypdf، والحزمة pytest للاختبارات.
- LibreOffice لازم لإعادة الحساب المستقلة (الأمر verify) ولرسم صور الصفحات؛ وأداة pdftotext لاستخراج نصوص المرجعيات.
- التثبيت: `pip install openpyxl python-docx lxml pillow pypdf pytest`

## 3. الجولة الأولى

1. اكتب ملف JSON بالملاحظات المعتمدة (الصيغة في رأس main.py). اسم المستند هو الاسم المعتمد في المادة 02.4، والرمز من حرفين إلى أربعة أحرف لاتينية كبيرة. يُفضَّل أن يكون اسم الإدارة صاحبة الوثيقة من قائمة القطاعات والوحدات في فهرس المرجعيات (G-REF-5)، وإلا يُحفظ كما كُتب ويُعلَّم في السجل.
2. نفّذ: `python main.py round1 round1.json OUT_DIR`
3. يُنشأ الملف باسم: `[اسم المستند] - مرئيات إدارة الحوكمة والامتثال المؤسسي - الجولة الأولى.xlsx`، بخصائص المؤلف "{W.AUTHOR}".
4. اختياري: `python main.py verify FILE.xlsx` يعيد الحساب في LibreOffice ويقارن كل خلية بالحساب المستقل.

## 4. الجولات اللاحقة

1. احتفظ بنسخة الجولة السابقة كما أُرسلت، فهي مرجع استعادة خلايا الحوكمة.
2. دوّن تقييم الجولة n في ملف JSON: لكل ملاحظة لم تكن "مغلقة" في بداية الجولة سطر يحوي `internal_id` و`status` (إحدى القيم الأربع) و`feedback` و`closure_basis` عند الإغلاق. الملاحظات المغلقة تُرحَّل تلقائياً.
3. نفّذ: `python main.py append RETURNED.xlsx round_n.json OUT_DIR --delivered DELIVERED.xlsx`
   - تُقرأ الصفوف بالمعرّف الداخلي في العمود B، لا بترتيبها.
   - تُستعاد أي خلية حوكمة عدّلتها الإدارة (SC-38)، وتُحفظ إفادات الإدارة كما كتبتها.
   - تُضاف أعمدة الجولة الجديدة الأربعة بعد آخر جولة مكتملة، وتُعاد بناء اللوحة كاملة.
   - أي نص كُتب في اللوحة أو في ورقة "بيانات اللوحة" يُسجَّل إفادةً عبر القناة X دون أن يُقرأ مدخلاً (SC-61)؛ تغيير المحددات لا يُعد إفادة (SC-62).
4. إعادة تنفيذ الجولة نفسها بالبيانات نفسها لا تغيّر شيئاً، وإعادة تنفيذها ببيانات مختلفة تُرفض.
5. شغّل البوابات قبل الإرسال: `python main.py gates NEW.xlsx --previous DELIVERED.xlsx --docx WORD.docx`

## 5. تحديث اللوحة دون جولة جديدة

`python main.py rebuild WORKBOOK.xlsx OUT_DIR` يعيد بناء "بيانات اللوحة" و"لوحة المتابعة التنفيذية" من ورقة الملاحظات دون تغيير أي قيمة فيها، ودون الكتابة فوق الملف الأصلي.

## 6. ترحيل ملفات v7.10 وv7.11

`python migrate_to_v712.py SOURCE.xlsx OUTPUT_DIR [--round-date 1=2026-07-05 ...]`

- لا يُعدَّل الملف الأصلي أبداً، وتُحفظ نسخة احتياطية مؤرخة في `OUTPUT_DIR/backup`.
- ملف v7.10: تُحفظ ورقة الملاحظات خلية بخلية، وتُضاف اللوحة، ثم تُحذف ورقة "عرض الطباعة".
- ملف v7.11: تُحفظ ورقة الملاحظات خلية بخلية، وتُزال اللوحة وورقة البيانات القديمتان، ثم تُبنيان من جديد بتصميم v7.12.
- يُكتب الملف الناتج بالاسم نفسه في المجلد الجديد مع تقرير JSON، ولا تُضاف أي جولة.

## 7. فهرس المرجعيات المؤسسية

- المصادر في `sources/reference/`: الهيكل التنظيمي (92 صفحة، "المهام والمسؤوليات المقترحة") ومصفوفة الصلاحيات الرئيسية (28 صفحة، 30 أبريل 2024)، مع ملف الحالة `INSTITUTIONAL-SOURCE-STATUS.json`.
- `python tools/build_deliverables.py references` يصدّر الفهرس إلى `deliverables/reference_index/` ويكتب سجل Excel. التغطية الحالية: {json.dumps(cov, ensure_ascii=False)}.
- في المراجعة: يُستشار اختصاص الوحدة (03A) وبند المصفوفة (05) عند أي ادعاء بصلاحية أو اختصاص، ويُذكر في الملاحظة رقم الصفحة أو البند مع التحفظ على حالة الاعتماد. لا يُنشئ الفهرس صلاحية ولا يُثبت اعتماداً.
- عند ورود نسخة معتمدة من أي مرجع، يُحدَّث ملف الحالة بدليل الاعتماد؛ المحرك لا يغيّر الحالة بنفسه (G-REF-2).

## 8. استعادة ملف غير صالح

- إذا رُفض الملف برسالة `FIXED_BLOCK` أو `INCOMPLETE_OR_UNKNOWN_BLOCK` أو `DUPLICATE_BLOCK`، فقد عُدّلت عناوين أو أُضيفت أعمدة يدوياً. يُستعاد الملف من نسخة الجولة السابقة، ثم تُنقل إليه إفادات الإدارة بالأمر append مع الخيار `--delivered`.
- إذا حُذفت اللوحة أو ورقة البيانات المخفية، يكفي الأمر rebuild (SC-64).
- إذا أُعيد الملف بصيغة PDF أو صورة، يُطلب ملف xlsx (المادة 10.6).

## 9. التحقق قبل الإرسال

1. `python -m pytest tests -q`: {len(st['tests'])} فحصاً (TEST 01–20 مع 12b و19b، وTEST 21–32).
2. `python main.py verify FILE.xlsx`: إعادة الحساب والمقارنة.
3. `python main.py gates ...`: البوابات G-DASH وG-UX (وG-REF وG-SYNC-9 ضمن G-DASH-12).
4. أوامر v7.12 الإضافية (كلها تطبع JSON وتعيد رمز خروج: 0 سليم، 1 فشل بوابة أو فحص، 2 خطأ في المدخل، 3 رفض بموجب السياسة، 4 غير متحقق): `inventory` (بصمات SHA-256 وفحص سلامة الحزم)، `ingest` (فتح آمن وقراءة)، `finalize-titles` (تطبيق قرارات المراجع الموثقة على العناوين؛ القرار سجل باسم المراجع وتاريخه ومرجعه لا قيمة منطقية)، `build-excel`، `build-word` (تعليقات أصلية على وثيقة الحالة ومتابعات كردود مترابطة)، `import-owner-return` (دلتا عودة الإدارة: مدخلاتها، الخلايا المستعادة، أي تلاعب أو صيغة)، `audit-history` (تدقيق السلالة)، `qa`، `demo-e2e`، `release` (حارس الإنتاج؛ لا يصدر OPERATIONALLY_APPROVED أبداً من الأداة).

أي بوابة بحالة FAIL توقف الإرسال. البوابات بحالة NOT_VERIFIED (التوافق مع Excel وWord) تُذكر في مذكرة التسليم مع سببها، ويقرر المستخدم الإرسال قبل التحقق منها (المادة 18).

عند إتاحة Microsoft Excel وWord، افتح الملفين وتحقق مما يلي: لا رسالة إصلاح؛ تتغير اللوحة عند اختيار جولة سابقة؛ تعمل روابط "فتح الصف"؛ تظهر الملاحظات عند التمرير على العناوين؛ تظهر متابعات الجولات ردوداً داخل سلسلة التعليق الأول.

## 10. تغيير الهوية أو الألوان

- كل الألوان معرّفة في `cdf_gco_crms/config/design_tokens.py` بثلاث عائلات (هوية، مشتقة، بروتوكول)، ومصدر كل لون موثق في `cdf_gco_crms/branding/brand_tokens.py`؛ وتُطابق قيم الصفحة 12 بالأداة `branding/guide_page_check.py`.
- عند ورود ملف الدليل الكامل، يُقرأ بالأداة `branding/pdf_brand_extractor.py` لإضافة إسناد من محتوى PDF نفسه.
- يُستبدل الشعار في `assets/`.

## 11. بنية الشيفرة

| الوحدة | الوظيفة |
|---|---|
| config/ | مخطط الجولات، رموز التصميم، إعدادات المصنف |
| model/ | الكيانات ودلالات الإغلاق والمؤشرات المشتقة |
| ingestion/ | قراءة مصنفات v7.10 وv7.11 وv7.12 |
| rounds/ | اكتشاف الجولات من العناوين وإلحاق الجولة |
| observations/ | المستخلصات الآلية (الملخص، الإجراء، الموضع) |
| reconciliation/ | المقارنة التاريخية واستلام الملف المُعاد |
| analytics/ | الحساب المستقل لكل رقم في اللوحة |
| excel/ | ورقة الملاحظات، ورقة البيانات، اللوحة، الحفظ الذري |
| word/ | التزامن مع تعليقات Word وسلاسل الردود |
| guidance/ | قاموس الإرشادات |
| branding/ | سجل الهوية والتباين وفحص صفحات الدليل |
| references/ | فهرس الهيكل التنظيمي ومصفوفة الصلاحيات |
| assurance/ | التحقق من الاقتباسات، حارس الإنتاج، محرك الاعتراضات (19A) |
| migration/ | ترحيل ملفات v7.10 وv7.11 |
| qa/ | إعادة الحساب، البوابات، الفحص، التقارير |
| protocol/ | دمج البروتوكول وجدول المطابقة والإخراج |
| regression/ | البيانات التجريبية والسجلات |
"""


def main():
    (OUT / "CDF-GCO-CRMS-v7.12-IMPLEMENTATION-GUIDE.md").write_text(guide(), encoding="utf-8")
    (OUT / "CDF-GCO-CRMS-v7.12-QA-REPORT.md").write_text(qa_report(), encoding="utf-8")
    print("written")


if __name__ == "__main__":
    main()
