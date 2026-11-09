#!/usr/bin/env python3
"""cdfkit: the CDF–GCO–CRMS engine for a chat assistant's code sandbox (Claude chat or ChatGPT).

The assistant reads, applies the GCO lens and drafts under the protocol; this script builds, checks and records.
It never drafts or changes the substance of an observation. Every command prints JSON and returns:
0 OK, 1 FAIL (a check or gate failed), 2 input error, 3 refused by policy, 4 NOT_VERIFIED only.

Commands (run ``python cdfkit.py <command> -h`` for options):
  info                         environment check: Python packages, renderer, kit version
  selftest                     three synthetic rounds end to end; run once in every new sandbox
  dump WORKBOOK [--round N]    comments, anchors and titles only: the input of the independent read (Art. 20)
  stage-packet STAGE --draft D --protocol P --out DIR [--doc DOC | --workbook X]
                               a self-contained packet for one fresh-chat stage: MAT-01, CHALLENGE, MAT-02,
                               MAT-03, ADJUDICATE, READ (Art. 19A, 19B, 20; 00A.8)
  stage-record STAGE ANSWER.json --draft D
                               validate the stage's JSON answer and file it; READ rates computed here (20.4)
  pages PDF --out DIR          scanned PDF: page images for the assistant to read (02.6A)
  transcript TXT --source PDF --out DIR
                               the assistant's transcription becomes the review Word file, marked as transcribed
  receipt FILE                 read a text file (the protocol) in numbered chunks; prints the 00.6 receipt
  show FILE --lines A-B        print lines A to B of a text file (to read a chunk into the conversation)
  read DOC                     inventory of the document under review (SHA-256, tracked changes, comments by
                               author) and its accepted-view paragraphs, numbered, in chunks
  check DRAFT.json --doc DOC   the automated detector (Art. 19, 07.2, 07.4) and the register-field checks
                               (03A.3, 04.4, 04.6, 07.10) on a round-1 draft or round-n new observations
  build DRAFT.json --doc DOC --out DIR [--logo-on-dark PNG] [--issue --decision TEXT]
                               round 1: Word with native GCO comments, requester workbook (two sheets: the
                               one-sheet executive dashboard and the data sheet), internal register, gates
  intake --register R.json --delivered-xlsx X --returned-xlsx Y [--delivered-docx D --returned-docx E] --out DIR
                               round n: forensic checks on the owner's return (15A.3, 16.1) and a ROUND template
  next ROUND.json --register R.json --delivered-xlsx X --returned-xlsx Y --returned-docx E --out DIR
       [--delivered-docx D] [--logo-on-dark PNG] [--issue --decision TEXT]
                               round n: append the round block, follow-up replies in the owner's Word file,
                               updated register, gates

Files are working copies (INTERNAL_DRAFT__ prefix, marked in their properties) unless --issue is given with the
GCO user's recorded decision (Art. 00A chat mode). Nothing here sends anything anywhere.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import shutil
import statistics
import sys
import os
import zipfile
from collections import Counter
from pathlib import Path

KIT_VERSION = "1.2.0"                # built from the repository by tools/build_chat_kit.py
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE if (HERE / "cdf_gco_crms").is_dir() else HERE.parent))   # built kit, or kit/ in the repository

RC_OK, RC_FAIL, RC_INPUT, RC_REFUSED, RC_NOT_VERIFIED = 0, 1, 2, 3, 4
CHUNK_CHARS = 12000
RECALC = True                      # independent recalculation when LibreOffice exists; --no-recalc turns it off

FORMS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "EDITORIAL")
LENS = ("a", "b", "c", "d", "e", "f")
STATUSES = ("مغلقة", "مغلقة بشرط", "يتطلب تعديل", "مفتوحة")
CLOSURE_PATHS = ("VERIFIED_TEXT", "GCO_REASSESSMENT", "ROUTED_RESIDUAL", "RISK_ACCEPTED")
LABELS = ("التوصية:", "النص المقترح:", "المطلوب:", "شرط الإغلاق:")
F7_CONNECTOR = "، بالنص الآتي: "


def emit(obj, path: Path | None = None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text)


def fail(msg: str, code: int = RC_INPUT) -> int:
    emit({"status": "INPUT_ERROR" if code == RC_INPUT else "REFUSED", "detail": msg})
    return code


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(fail(f"cannot read JSON {path}: {exc}"))


# ===================================================================================== words (07.7)
_DIAC = re.compile("[ً-ْٰـ]")
_WORD = re.compile(r"[0-9A-Za-zء-غف-ي٠-٩ٱ-ۓۺ-ۿ]+")


def words(text: str | None) -> int:
    """07.7 word count: the engine's (``cdf_gco_crms.comments.words``)."""
    from cdf_gco_crms.comments import words as _words
    return _words(text)


def tokens(text: str | None) -> list[str]:
    return _WORD.findall(_DIAC.sub("", text or ""))


# ===================================================================================== documents
def doc_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".docx", ".pdf", ".xlsx"):
        return ext[1:]
    raise SystemExit(fail(f"{path.name}: only .docx, .pdf and .xlsx are read (save .doc as .docx first)"))


def review_docx(doc: Path, work: Path) -> Path:
    """The Word file that carries the comments: the document itself, or a Word rendition of a PDF/XLSX."""
    kind = doc_kind(doc)
    if kind == "docx":
        return doc
    from cdf_gco_crms.documents.ingest import extract, to_docx
    out = work / (doc.stem + " - نص المراجعة.docx")
    if not out.exists():
        try:
            src = extract(doc, kind)
        except ImportError as exc:
            raise SystemExit(fail(f"reading a {kind.upper()} needs pdfplumber ({exc}); install it in the sandbox "
                                  "(pip install pdfplumber) or ask the user for the .docx version"))
        empty = [w for w in src.warnings if w.endswith("_HAS_NO_TEXT_LAYER")]
        if not src.blocks or empty:
            raise SystemExit(fail(
                f"{doc.name}: {'no text layer' if not src.blocks else f'{len(empty)} page(s) without a text layer'} "
                "(scanned). 02.6A: first ask the GCO user for the Word version. Only if they confirm none exists: "
                "`pages` to render the pages, transcribe them yourself into the transcript format, then `transcript`, "
                "and use the Word file it writes as --doc (AGENT-GUIDE section 8)."))
        to_docx(src, doc.stem, out)
    return out


def doc_paragraphs(docx: Path) -> list[str]:
    from lxml import etree
    from cdf_gco_crms.word.document_comments import DocText
    with zipfile.ZipFile(docx) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    return [p.text for p in DocText(root).paras]


def norm(text: str) -> str:
    from cdf_gco_crms.word.document_comments import normalise
    return normalise(text or "")[0]


def find_quote(paras_n: list[str], quote: str, occurrence: int = 1) -> tuple[int | None, int]:
    """(paragraph index of the requested occurrence, total occurrences); quotes are matched within one paragraph."""
    q = norm(quote)
    if not q:
        return None, 0
    hits = []
    for i, p in enumerate(paras_n):
        start = 0
        while True:
            k = p.find(q, start)
            if k < 0:
                break
            hits.append((i, k))
            start = k + 1
    if not hits:
        return None, 0
    occ = max(1, int(occurrence or 1))
    return (hits[occ - 1][0] if occ <= len(hits) else None), len(hits)


# ===================================================================================== scanned inputs (02.6A)
TRANSCRIBED_MARK = "TRANSCRIBED_NOT_EXTRACTED"
UNREADABLE = "[؟]"
_PAGE_MARK = re.compile(r"^=+\s*(?:صفحة|ص\.|page)\s*(\d+)\s*=+$", re.I)


def render_pages(pdf: Path, out: Path, dpi: int = 150, first: int = 1, last: int | None = None) -> tuple[list, str]:
    """PDF pages to PNG files with whatever the sandbox has: PyMuPDF, pypdfium2, then pdftoppm."""
    out.mkdir(parents=True, exist_ok=True)
    try:
        import fitz                                            # PyMuPDF
        doc = fitz.open(str(pdf))
        last = min(last or doc.page_count, doc.page_count)
        files = []
        for n in range(first, last + 1):
            f = out / f"page-{n:03d}.png"
            doc[n - 1].get_pixmap(dpi=dpi).save(str(f))
            files.append(f)
        return files, "PyMuPDF"
    except ImportError:
        pass
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf))
        last = min(last or len(doc), len(doc))
        files = []
        for n in range(first, last + 1):
            f = out / f"page-{n:03d}.png"
            doc[n - 1].render(scale=dpi / 72).to_pil().save(f)
            files.append(f)
        return files, "pypdfium2"
    except ImportError:
        pass
    tool = shutil.which("pdftoppm")
    if tool:
        import subprocess
        args = [tool, "-png", "-r", str(dpi), "-f", str(first)] + (["-l", str(last)] if last else []) + \
               [str(pdf), str(out / "page")]
        subprocess.run(args, check=True, capture_output=True)
        files = sorted(out.glob("page-*.png"))
        return files, "pdftoppm"
    return [], "none"


def text_layer_pages(pdf: Path) -> dict:
    """{page: characters of text layer}, or {} when no PDF reader is present."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf)) as d:
            return {i: len("".join(c["text"] for c in pg.chars).strip()) for i, pg in enumerate(d.pages, 1)}
    except ImportError:
        pass
    try:
        import fitz
        d = fitz.open(str(pdf))
        return {i: len(pg.get_text().strip()) for i, pg in enumerate(d, 1)}
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
        return {i: len((pg.extract_text() or "").strip()) for i, pg in enumerate(PdfReader(str(pdf)).pages, 1)}
    except ImportError:
        return {}


def parse_transcript(text: str) -> list[tuple[int, str]]:
    """'=== صفحة N ===' lines open each page; every other non-empty line is one paragraph of that page."""
    page, out = None, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _PAGE_MARK.match(line)
        if m:
            page = int(m.group(1))
            continue
        if page is None:
            raise ValueError("the transcription must start with a page line such as '=== صفحة 1 ==='")
        out.append((page, line))
    if not out:
        raise ValueError("the transcription holds no text")
    return out


def is_transcribed(docx: Path | None) -> bool:
    if docx is None or Path(docx).suffix.lower() != ".docx":
        return False
    try:
        with zipfile.ZipFile(docx) as z:
            return TRANSCRIBED_MARK in z.read("docProps/core.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile, OSError):
        return False


def transcription_record(docx: Path) -> dict | None:
    side = Path(docx).with_suffix(".transcription.json")
    return json.loads(side.read_text(encoding="utf-8")) if side.exists() else None


# ===================================================================================== comment text (07.1, 07.4, 08.2)
def _segments_from_text(text: str, bold_labels: bool = True):
    """Plain text with \\n line breaks; fixed labels at a line start become bold segments."""
    from cdf_gco_crms.model.entities import Segment
    segs = []
    lines = (text or "").split("\n")
    for k, line in enumerate(lines):
        if k:
            segs.append(Segment("\n"))
        label = next((lb for lb in LABELS if bold_labels and line.startswith(lb)), None)
        if label:
            segs.append(Segment(label, True))
            rest = line[len(label):]
            if rest:
                segs.append(Segment(rest))
        elif line:
            segs.append(Segment(line))
    return segs


CLOSURE_LABEL = "الإجراء المتوقع للإغلاق:"


IMPROVEMENT_LABEL = "ملاحظة تحسينية:"


def compose_comment(o: dict):
    """The comment body from the register fields (07.4A, 08.2A, 08.2B): the engine's composer
    (``cdf_gco_crms.comments.compose_comment``), so the kit and the repository build the same text."""
    from cdf_gco_crms.comments import compose_comment as _compose
    return _compose(o)


def compose_feedback(a: dict):
    """Round-n feedback: either ``feedback`` text (labels bolded) or the late-round three parts of 08.3A."""
    from cdf_gco_crms.model.entities import GText, Segment
    if a.get("recommendation") or a.get("proposed_text"):
        segs = []
        if a.get("location_line"):
            segs += [Segment(a["location_line"].strip()), Segment("\n")]
        if a.get("comment"):
            segs += _segments_from_text(a["comment"].strip(), bold_labels=False) + [Segment("\n")]
        segs += [Segment("التوصية:", True), Segment(" " + (a.get("recommendation") or "").strip())]
        if a.get("proposed_text"):
            segs += [Segment("\n"), Segment("النص المقترح:", True), Segment(" "),
                     Segment("(" + a["proposed_text"].strip().strip("()") + ")", True)]
        return GText(segs)
    text = (a.get("feedback") or "").strip()
    if a.get("location_line") and not text.startswith(a["location_line"].strip()):
        text = a["location_line"].strip() + "\n" + text
    return GText(_segments_from_text(text)) if text else None


def plain(gtext) -> str:
    from cdf_gco_crms.model.entities import plain_text
    return plain_text(gtext)


# ===================================================================================== detector (Art. 19) and fields
_ARROWS = re.compile("[←-⇿⟰-⟿]|->|=>")
_FIRST_PERSON = ("أرى", "لا أرى", "أقترح", "أوصي")
_VERDICTS = ("يُبطل", "يبطل", "باطل", "غير نافذ", "لاغٍ", "لاغية", "فاسد", "يُفسد", "غير صحيح شرعاً", "محرم")
_INTEGRITY = ("احتيال", "تلاعب", "تزوير", "إخفاء", "سوء نية", "متعمد")
_HEADINGS = ("التعليق:", "الملاحظة:", "أشار المراجع", "لوحظ")
_VAGUE = ("يفضل تحسين النص", "يرجى التوضيح", "قد توجد مخاطر")
_PERSONAL = ("الأخ ", "الأخت ", "الأستاذ ", "الأستاذة ", " أبو ", " أبا ", " أم ")
_SELF_REVERSAL = ("خلافاً لطلبنا", "نعدل عن", "تراجعاً عن", "بعد إعادة تقييم التعديل")
_OPENER_EXEMPT = ("نوصي", "نأمل", "نؤكد", "نرجو", "نقترح", "هل")


def _first_word(text: str) -> str:
    t = tokens(text)
    if not t:
        return ""
    w0 = t[0]
    return w0[1:] if len(w0) > 3 and w0[0] in "وف" else w0


def _ngrams(toks: list[str], n: int) -> set:
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def detector(observations: list[dict], protocol: str = "7.15") -> list[dict]:
    """Per-document metrics of Art. 19.2 that a script can measure; P1 is the reader's (Art. 20)."""
    res = []

    def add(metric, value, threshold, ok, warn=False, items=None):
        res.append({"metric": metric, "value": value, "threshold": threshold,
                    "result": "PASS" if ok else ("WARN" if warn else "FAIL"), "items": items or []})

    n = len(observations)
    if n == 0:
        return res
    whole = [plain(compose_comment(o)) for o in observations]
    lengths = [words(t) for t in whole]
    # P2 connective repetition, measured on the drafted words: the fixed labels of 07.4A, 08.2A and 08.2B appear in
    # every new comment by design and are not repetition
    fixed = LABELS + (CLOSURE_LABEL, IMPROVEMENT_LABEL)
    bodies = []
    for t in whole:
        for lb in fixed:
            t = t.replace(lb, " ")
        bodies.append(" ".join(t.split()))
    exempt = set(LABELS) | {"بالنص الآتي"}
    counts = Counter()
    for t in bodies:
        counts.update(_ngrams(tokens(t), 3))
    rep = [(g, c) for g, c in counts.items() if c / n > 0.15 and c > 1 and g not in exempt and "بالنص الآتي" not in g]
    add("P2 connective repetition", len(rep), "no 3-word phrase in > 15 %", not rep, warn=n < 8,
        items=[f"{g} ({c})" for g, c in sorted(rep, key=lambda x: -x[1])[:10]])
    # P3 uniform length
    if n >= 8:
        cv = statistics.pstdev(lengths) / statistics.mean(lengths) if statistics.mean(lengths) else 0
        add("P3 uniform length (CV)", round(cv, 2), ">= 0.25", cv >= 0.25)
    # P4 same opener
    openers = Counter(_first_word(t) for t in bodies)
    top = [(w0, c) for w0, c in openers.items() if w0 and w0 not in _OPENER_EXEMPT and c / n > 0.20 and c > 1]
    add("P4 same opener", len(top), "no opener in > 20 %", not top, items=[f"{w0} ({c})" for w0, c in top])
    # P6 parenthetical lists of four or more items
    p6 = [o.get("id") or i + 1 for i, (o, t) in enumerate(zip(observations, whole))
          if any(m.count("،") >= 3 for m in re.findall(r"\(([^()]*)\)", t))
          and (o.get("form") or "").upper() != "F7"]
    add("P6 parenthetical lists", len(p6), "none", not p6, warn=True, items=p6)
    # P8 mirror recommendations
    p8 = []
    for i, o in enumerate(observations):
        a, r = set(tokens(o.get("analysis"))), set(tokens(o.get("recommendation")))
        if a and r and len(a & r) / max(1, len(r)) >= 0.6:
            p8.append(o.get("id") or i + 1)
    add("P8 mirror recommendations", len(p8), "none", not p8, items=p8)
    # P9 form mix (07.4)
    forms = [(o.get("form") or "").upper() for o in observations]
    fc = Counter(forms)
    issues = []
    for f, c in fc.items():
        if f != "F7" and c / n > 0.5 and n >= 4:
            issues.append(f"{f} {c}/{n} > 50 %")
    need = 3 if n >= 8 else (2 if n >= 4 else 0)
    if len(fc) < need:
        issues.append(f"{len(fc)} forms < {need}")
    if fc.get("F5", 0) / n > 0.30 and n >= 4:
        issues.append(f"F5 {fc['F5']}/{n} > 30 %")
    run = 1
    for i in range(1, n):
        run = run + 1 if forms[i] == forms[i - 1] else 1
        if run > 2:
            issues.append(f"three adjacent {forms[i]} at #{i + 1}")
            break
    add("P9 form mix", "; ".join(issues) or "ok", "07.4 limits", not issues, warn=n < 4, items=issues)
    if fc.get("F7", 0) / n > 0.40:
        add("P9 F7 share", f"{fc['F7']}/{n}", "<= 40 % (over-drafting flag)", False, warn=True)
    # P10 typography
    p10 = []
    for i, t in enumerate(whole):
        if _ARROWS.search(t) or "«" in t or "»" in t or '""' in t or " - " in t:
            p10.append(observations[i].get("id") or i + 1)
    add("P10 typography", len(p10), "no arrow, angle quote, doubled quote, spaced hyphen", not p10, items=p10)
    # P11 remedy overlap
    p11 = []
    for i in range(n):
        for j in range(i + 1, n):
            ti = set(observations[i].get("target_clauses") or [])
            tj = set(observations[j].get("target_clauses") or [])
            gi = _ngrams(tokens((observations[i].get("recommendation") or "") + " " +
                                (observations[i].get("proposed_wording") or "")), 4)
            gj = _ngrams(tokens((observations[j].get("recommendation") or "") + " " +
                                (observations[j].get("proposed_wording") or "")), 4)
            ov = len(gi & gj) / max(1, min(len(gi), len(gj))) if gi and gj else 0
            if (ti & tj) or ov >= 0.25:
                p11.append(f"{i + 1}&{j + 1}")
    add("P11 remedy overlap", len(p11), "none (consolidate per 07.5)", not p11, items=p11)
    # P13 voice
    p13 = []
    for i, t in enumerate(whole):
        if any(re.search(rf"(^|\s){re.escape(x)}(\s|$|[.،])", t) for x in _FIRST_PERSON) or any(v in t for v in _VERDICTS):
            p13.append(observations[i].get("id") or i + 1)
    add("P13 voice (first person, verdicts)", len(p13), "none", not p13, items=p13)
    # P14 (engine): v7.15 flags each new comment with more than one reason sentence or a part above its 07.2
    # ceiling; before v7.15 the explanation load (reasons <= 50 %, median <= 40), WARN only.
    from cdf_gco_crms.comments import p14_findings
    p14 = p14_findings(observations, protocol=protocol)
    if "flagged" in p14:
        add("P14 reason sentences and 07.2 ceilings", len(p14["flagged"]), "none", p14["ok"], items=p14["flagged"])
    else:
        add("P14 explanation load", f"reasons {p14['reasons']}/{n}, median {p14['median']}",
            "reasons <= 50 %, median <= 40", p14["ok"], warn=True)
    return res


def field_checks(o: dict, idx: int, paras_n: list[str], round_no: int, protocol: str = "7.15") -> list[str]:
    """Per-observation register and text rules. Returns problems (FAIL) prefixed with the rule."""
    p = []
    form = (o.get("form") or "").upper()
    if form not in FORMS:
        p.append("G-TXT-4 form F1–F7 missing")
    lens = str(o.get("lens_category") or "").strip()
    if not (lens in LENS or lens.startswith("routed:")):
        p.append("G-SUB-11 lens_category (a–f or 'routed: <class>') missing")
    mt = o.get("materiality_test") or {}
    vals = [mt.get(k) for k in ("q1_lens", "q2_worse_off", "q3_handled_elsewhere", "q4_duplicate")]
    if not lens.startswith("routed:") and vals != [True, True, False, False]:
        p.append("04.4 materiality_test must read yes/yes/no/no (q1_lens, q2_worse_off, q3_handled_elsewhere, "
                 "q4_duplicate)")
    if not o.get("searched_clauses"):
        p.append("04.4 searched_clauses empty (always include indemnity, liability, termination, same subject)")
    if (o.get("severity") or "").upper() not in SEVERITIES:
        p.append("04.2 severity missing")
    elif not (o.get("severity_basis") or "").strip():
        p.append("04.2a severity_basis missing")
    edit = (o.get("edit_type") or "").lower()
    if edit and edit != "question to owner" and not (o.get("conflicts_checked") or "").strip():
        p.append("G-SUB-13 conflicts_checked empty for an obligation-changing remedy (07.10(4))")
    if o.get("action_summary") and len(" ".join(o["action_summary"].split())) > 75:
        p.append(f"kit 1.1.3 action_summary {len(o['action_summary'])} characters > 75 (ACTION_MAX)")
    if not (o.get("title") or "").strip():
        p.append("10.4A.16 title missing (≤ 12 words)")
    elif words(o["title"]) > 12:
        p.append(f"10.4A.16 title {words(o['title'])} words > 12")
    # quote (G-SUB-2) and anchor (08.4)
    q = o.get("quote") or ""
    if UNREADABLE in q or UNREADABLE in (o.get("closure_text") or ""):
        p.append("02.6A quote contains an unreadable mark [؟]: quote readable text only, make the recommendation conditional on the original, or withhold")
    if paras_n is not None:
        pi, hits = find_quote(paras_n, q, o.get("occurrence") or 1)
        if not q.strip():
            p.append("08.4 quote empty")
        elif hits == 0:
            p.append("G-SUB-2 quote not found verbatim in one paragraph of the accepted view")
        elif hits > 1 and not o.get("occurrence"):
            p.append(f"08.4 quote occurs {hits} times: give occurrence")
        elif pi is None:
            p.append(f"08.4 occurrence {o.get('occurrence')} > {hits}")
    if not (o.get("location") or "").strip():
        p.append("10.3 location (column C) empty")
    # comment shape (engine, cdf_gco_crms.comments): 07.1, 07.2 ceilings, 07.4A, G-SUB-12, 08.2A, 08.2B; a review
    # under a version before v7.15 keeps the earlier rules (00.2 carve-out)
    from cdf_gco_crms.comments import check_comment
    p += check_comment(o, protocol=protocol, round_of_birth=True)
    if form == "F7" and not (o.get("proposed_wording") or "").strip():
        p.append("07.4 F7 needs proposed_wording (the clause)")
    text = plain(compose_comment(o))
    for h in _HEADINGS:
        if h in text:
            p.append(f"G-TXT-2 prohibited heading or attribution '{h}'")
    for x in _INTEGRITY:
        if x in text:
            p.append(f"G-INT-3 prohibited word '{x}'")
    for x in _SELF_REVERSAL:
        if x in text:
            p.append(f"G-HIST-2 self-reversal phrase '{x}'")
    for x in _PERSONAL:
        if x in " " + text:
            p.append(f"G-MAT-05 possible personal reference '{x.strip()}' (address by role)")
    for x in _VAGUE:
        if x in text:
            p.append(f"06.2 vague phrase '{x}' (allowed only with the deficiency and action in the same sentence)")
    if round_no > 1 and not (o.get("reason") or "").strip():
        p.append("10.2 a new observation in a verification round needs reason (≤ 20 words)")
    return p


def run_check(draft: dict, docx: Path | None, round_no: int = 1) -> dict:
    obs = draft.get("observations") if round_no == 1 else draft.get("new_observations")
    obs = obs or []
    protocol = str(draft.get("protocol_version") or "7.15")
    paras_n = [norm(t) for t in doc_paragraphs(docx)] if docx else None
    rows = []
    for i, o in enumerate(obs):
        probs = field_checks(o, i, paras_n, round_no, protocol)
        rows.append({"n": i + 1, "id": o.get("id"), "form": o.get("form"), "words": words(plain(compose_comment(o))),
                     "problems": probs, "result": "FAIL" if probs else "PASS"})
    det = detector(obs, protocol) if round_no == 1 else []
    doc = draft.get("document") or {}
    doc_probs = []
    if round_no == 1:
        name = (doc.get("name") or "").strip()
        if not name:
            doc_probs.append("02.4 document.name missing")
        elif len(name) > 60:
            doc_probs.append(f"02.4 document.name {len(name)} characters > 60")
        if not re.fullmatch(r"[A-Z]{2,4}", doc.get("code") or ""):
            doc_probs.append("02.5 document.code must be 2–4 Latin capitals")
    fails = sum(1 for r in rows if r["problems"]) + sum(1 for d in det if d["result"] == "FAIL") + len(doc_probs)
    return {"status": "FAIL" if fails else "PASS", "observations": len(obs), "document_problems": doc_probs,
            "per_observation": rows, "detector": det,
            "not_measured_here": ["P1 identical skeleton (reader, Art. 20)", "P5 stacked nominalisations",
                                  "P7 double hedging", "P12 cross-reference drift", "P15 remedy conflict",
                                  "R1–R6 independent read (Art. 20)"]}


# ===================================================================================== register (Art. 12)
REGISTER_SHEETS = ("لوحة المؤشرات", "فهرس الوثائق والحالات", "الإصدارات", "فهرس المستند", "ملاحظات المراجعة",
                   "ربط تعليقات Word", "تصنيف الحوكمة", "المراجع النظامية", "سجل المخاطر", "التعديلات المقترحة",
                   "ردود الإدارة", "مقارنة الإصدارات", "الإغلاق", "الأدلة", "المخاطر المتبقية", "مسار الاعتماد",
                   "سجل التدقيق", "قاعدة المعرفة", "إعدادات الجودة", "متطلبات الرقابة", "علاقات الوثائق",
                   "ضمان الأثر النظامي", "تدهور الحوكمة", "إدارة العيوب")
OBS_FIELDS = ("internal_id", "reader_no", "birth_round", "location", "quote", "occurrence", "title", "form",
              "analysis", "recommendation", "proposed_wording", "lens_category", "severity", "severity_basis",
              "materiality_test", "searched_clauses", "depends_on_unseen", "basis_class", "legal_basis",
              "policy_basis", "risk_consequence", "control_objective", "target_clauses", "edit_type",
              "annex_created", "depends_on", "commitment_points", "conflicts_checked", "material_categories",
              "reason", "words")


def _cell(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def write_register_xlsx(reg: dict, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="BBDDE6")
    font, bold = Font(name="Calibri", size=10), Font(name="Calibri", size=10, bold=True)
    data: dict[str, tuple[list[str], list[list]]] = {}
    doc = reg.get("document", {})
    rounds = reg.get("rounds", {})
    obs = reg.get("observations", {})
    last = max((int(k) for k in rounds), default=1)
    data["فهرس الوثائق والحالات"] = (["الحقل", "القيمة"], [[k, _cell(v)] for k, v in doc.items()] +
                                     [["package_short_name", reg.get("package_short_name")],
                                      ["current_round", last]])
    data["الإصدارات"] = (["الجولة", "التاريخ", "الملف", "SHA-256", "إصدار الغلاف"],
                        [[k, r.get("date"), r.get("base_file"), r.get("base_sha256"), r.get("document_version")]
                         for k, r in sorted(rounds.items(), key=lambda x: int(x[0]))])
    cols = list(OBS_FIELDS)
    data["ملاحظات المراجعة"] = (cols, [[_cell(o.get(c)) for c in cols] for o in obs.values()])
    data["ربط تعليقات Word"] = (["Internal_ID", "Reader_No", "Anchor_Text", "Occurrence", "Location"],
                                [[o.get("internal_id"), o.get("reader_no"), o.get("quote"), o.get("occurrence") or 1,
                                  o.get("location")] for o in obs.values()])
    data["تصنيف الحوكمة"] = (["Internal_ID", "Lens_Category", "Target_Clauses", "Severity"],
                             [[o.get("internal_id"), o.get("lens_category"), _cell(o.get("target_clauses")),
                               o.get("severity")] for o in obs.values()])
    data["التعديلات المقترحة"] = (["Internal_ID", "Form", "Edit_Type", "Proposed_Wording", "Conflicts_Checked"],
                                  [[o.get("internal_id"), o.get("form"), o.get("edit_type"),
                                    o.get("proposed_wording"), o.get("conflicts_checked")]
                                   for o in obs.values() if o.get("proposed_wording") or o.get("edit_type")])
    hist = []
    for o in obs.values():
        for n, h in sorted((o.get("history") or {}).items(), key=lambda x: int(x[0])):
            hist.append([o.get("internal_id"), o.get("reader_no"), int(n), h.get("status"), h.get("closure_path"),
                         h.get("closure_basis"), h.get("severity"), h.get("feedback")])
    data["الإغلاق"] = (["Internal_ID", "Reader_No", "الجولة", "قيمة الإغلاق", "Closure_Path", "Closure_Basis",
                        "Severity_R[n]", "مرئيات الحوكمة"], hist)
    data["ردود الإدارة"] = (["الجولة", "Internal_ID", "الإفادة", "حالة التطبيق", "Integrity_Signal", "Integrity_Class",
                              "Evidence_Ref"],
                             [[r.get("round"), r.get("internal_id"), r.get("response"), r.get("impl"),
                               _cell(r.get("integrity_signal")), r.get("integrity_class"), r.get("evidence_ref")]
                              for r in reg.get("responses", [])])
    data["تدهور الحوكمة"] = (["الجولة", "Internal_ID", "النتيجة", "التفاصيل"],
                             [[r.get("round"), r.get("internal_id"), r.get("status"), r.get("detail")]
                              for r in reg.get("closed_text", [])])
    data["الأدلة"] = (["الجولة", "الملف", "SHA-256", "الخصائص"],
                      [[r.get("round"), r.get("file"), r.get("sha256"), _cell(r.get("properties"))]
                       for r in reg.get("evidence", [])])
    data["سجل التدقيق"] = (["الوقت", "الحدث", "التفاصيل"],
                           [[e.get("at"), e.get("event"), _cell(e.get("detail"))] for e in reg.get("events", [])] +
                           [[None, "WITHDRAWN_BEFORE_ISSUE", _cell(w)] for w in reg.get("withdrawn", [])])
    data["مسار الاعتماد"] = (["الجولة", "القرار", "الوقت"],
                             [[k, r.get("decision"), r.get("issued_at")] for k, r in rounds.items() if r.get("decision")])
    q = []
    for k, r in sorted(rounds.items(), key=lambda x: int(x[0])):
        for d in (r.get("check") or {}).get("detector", []):
            q.append([k, "detector", d["metric"], _cell(d["value"]), d["result"]])
        for g in (r.get("gates") or []):
            q.append([k, "gate", g.get("gate"), _cell(g.get("actual")), g.get("status")])
        for key in ("read_receipt", "red_team", "manifest"):
            if r.get(key):
                q.append([k, key, None, _cell(r[key]), None])
    for k, r in sorted(rounds.items(), key=lambda x: int(x[0])):
        st = r.get("stages") or {}
        for stage in ("MAT-01", "MAT-02", "MAT-03"):
            for x in (st.get(stage) or {}).get("positions", []):
                q.append([k, stage + " (advisory only)", x.get("id"), x.get("advice"), x.get("position")])
        for x in (st.get("CHALLENGE") or {}).get("records", []):
            q.append([k, "CHALLENGE", x.get("id"),
                      _cell({"objection": x.get("objection"), "ground": x.get("ground"), "response": x.get("response"),
                             "revision": x.get("revision")}), f"cycles {x.get('cycles') or 0}"])
        for x in (st.get("ADJUDICATE") or {}).get("dispositions", []):
            q.append([k, "ADJUDICATE", x.get("id"), x.get("rationale"), x.get("disposition")])
        for i, rd in enumerate(st.get("READ_HISTORY") or [], 1):
            comp = rd.get("computed") or {}
            q.append([k, f"READ cycle {i}", f"seed {rd.get('seed')}; sample {len(rd.get('sample') or [])}",
                      _cell({r_: v["rate"] for r_, v in (comp.get("rates") or {}).items()}),
                      "PASS" if comp.get("pass") else "FAIL"])
        if st.get("HUMAN-REVIEW"):
            h = st["HUMAN-REVIEW"]
            q.append([k, "HUMAN-REVIEW (14.4)", h.get("reviewer_role"), f"{h.get('date')} covers {h.get('covers')}",
                      "RECORDED"])
        for prob in r.get("stage_problems") or []:
            q.append([k, "stage gate", None, prob, "BLOCKS ISSUE"])
    data["إعدادات الجودة"] = (["الجولة", "النوع", "المقياس", "القيمة", "النتيجة"], q)
    data["علاقات الوثائق"] = (["الوثيقة", "الحالة"], [[d.get("document"), d.get("status")]
                                                     for d in reg.get("evidence_pack", [])])
    kb = []
    for k, r in sorted(rounds.items(), key=lambda x: int(x[0])):
        vals = Counter((o.get("history") or {}).get(k, {}).get("status") for o in obs.values())
        kb.append([k, sum(1 for o in obs.values() if int(o.get("birth_round", 1)) <= int(k))] +
                  [vals.get(s, 0) for s in STATUSES])
    data["قاعدة المعرفة"] = (["الجولة", "الملاحظات"] + list(STATUSES), kb)
    data["لوحة المؤشرات"] = (["المؤشر", "القيمة"], [["عدد الملاحظات", len(obs)], ["الجولة الحالية", last]])
    for name in REGISTER_SHEETS:
        ws = wb.create_sheet(name[:31])
        ws.sheet_view.rightToLeft = True
        head, rows = data.get(name, (["ملاحظة"], [["لا توجد بيانات لهذه الورقة في هذا الإصدار من الأداة"]]))
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = bold, head_fill
            c.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
        for row in rows:
            ws.append([_cell(v) for v in row])
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font = font
                c.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
        for i in range(1, len(head) + 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = 24
        ws.freeze_panes = "A2"
        if ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions
    write_internal_dashboard(wb["لوحة المؤشرات"], reg)
    from cdf_gco_crms.config import workbook_settings as W
    p = wb.properties
    p.creator = p.lastModifiedBy = W.AUTHOR
    p.title = "سجل مراجعة " + (reg.get("package_short_name") or doc.get("name") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    # 09.4 / D5: library-free app properties with the Company, as the requester workbook has (kit 1.1.0)
    from cdf_gco_crms.excel.workbook_builder import APP_XML
    tmp = str(path) + ".pp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = APP_XML.encode("utf-8") if item.filename == "docProps/app.xml" else zin.read(item.filename)
            zout.writestr(item, data)
    os.replace(tmp, path)


def write_internal_dashboard(ws, reg: dict) -> None:
    """The register's own dashboard (12.3): internal quality indicators. Never sent to the owner (D1, 09.3)."""
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    for row in ws.iter_rows():
        for c in row:
            c.value = None
    ws.auto_filter.ref = None
    ws.freeze_panes = None
    ws.sheet_view.rightToLeft = True
    ws.sheet_view.showGridLines = False
    f = lambda sz=10, b=False, color="000000": Font(name="Calibri", size=sz, bold=b, color=color)
    band = PatternFill("solid", fgColor="BBDDE6")
    light = PatternFill("solid", fgColor="F2F2F2")
    doc, rounds, obs = reg.get("document", {}), reg.get("rounds", {}), reg.get("observations", {})
    order = sorted(rounds, key=int)
    last = order[-1] if order else "1"
    r = 1

    def title(text):
        nonlocal r
        r += 1
        ws.cell(r, 1, text).font = f(12, True)
        for col in range(1, 9):
            ws.cell(r, col).fill = band
        r += 1

    def row(*vals, bold=False, fill=None):
        nonlocal r
        for i, v in enumerate(vals, 1):
            c = ws.cell(r, i, _cell(v))
            c.font = f(10, bold)
            c.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
            if fill:
                c.fill = fill
        r += 1

    ws.cell(r, 1, "لوحة المؤشرات الداخلية – " + (doc.get("name") or "")).font = f(16, True)
    r += 1
    ws.cell(r, 1, "داخلية: لا تُرسل إلى الإدارة صاحبة الطلب ولا تُرفق بالخطاب (D1، 09.3).").font = f(9, False, "595959")
    r += 1
    title("الوثيقة والتنفيذ")
    st_last = (rounds.get(last) or {}).get("stages") or {}
    prof = next((((rounds.get(k) or {}).get("stages") or {}).get("MAT-01", {}).get("meta", {}).get("profile") or {}
                 for k in reversed(order) if (((rounds.get(k) or {}).get("stages") or {}).get("MAT-01"))), {})
    for k, v in (("الرمز", doc.get("code")), ("الجولة الحالية", last), ("مصدر النص", doc.get("source_mode") or "مستخرج"),
                 ("إصدار الأداة", reg.get("kit_version")), ("MAT PROFILE", prof.get("line") or "none")):
        row(k, v)
    title("الملاحظات")
    vals = list(obs.values())
    row("الإجمالي", len(vals), bold=True)
    for label, key, cats in (("حسب الشكل", "form", ("F1", "F2", "F3", "F4", "F5", "F6", "F7")),
                             ("حسب العدسة", "lens_category", None), ("حسب الأهمية", "severity", SEVERITIES)):
        cnt = Counter((str(o.get(key) or "—")) for o in vals)
        keys = list(cats) if cats else sorted(cnt)
        row(label, *keys, bold=True, fill=light)
        row("", *[cnt.get(x, 0) for x in keys])
    title("الكاشف الآلي (المادة 19)")
    for d in ((rounds.get("1") or {}).get("check") or {}).get("detector", []):
        row(d["metric"], d["value"], d["threshold"], d["result"])
    title("التحدي المؤسسي (19A) والمستشار MAT (19B، استشاري فقط)")
    row("الجولة", "اعتراضات", "دورات", *DISP_SHORT.values(), bold=True, fill=light)
    for k in order:
        st = (rounds.get(k) or {}).get("stages") or {}
        recs = (st.get("CHALLENGE") or {}).get("records", [])
        dc = Counter(x.get("disposition") for x in (st.get("ADJUDICATE") or {}).get("dispositions", []))
        row(k, sum(1 for x in recs if x.get("objection")), sum(int(x.get("cycles") or 0) for x in recs),
            *[dc.get(d, 0) for d in DISP_SHORT])
    row("المرحلة", *POS_LIST, bold=True, fill=light)
    for k in order:
        st = (rounds.get(k) or {}).get("stages") or {}
        for stage in ("MAT-01", "MAT-02", "MAT-03"):
            pc = Counter(x.get("position") for x in (st.get(stage) or {}).get("positions", []))
            if pc:
                row(f"{stage} (الجولة {k})", *[pc.get(x, 0) for x in POS_LIST])
    title("القراءة المستقلة (المادة 20)")
    row("الجولة", "الدورات", "R1", "R2", "R3", "R4", "R5", "R6", "R7", bold=True, fill=light)
    for k in order:
        st = (rounds.get(k) or {}).get("stages") or {}
        hist = st.get("READ_HISTORY") or []
        if hist:
            rates = (hist[-1].get("computed") or {}).get("rates") or {}
            row(k, len(hist), *[f"{int(rates[x]['rate'] * 100)}%{'' if rates[x]['pass'] else ' ✗'}"
                                if x in rates else "" for x in ("R1", "R2", "R3", "R4", "R5", "R6", "R7")])
        elif st.get("HUMAN-REVIEW"):
            row(k, "مراجعة بشرية (14.4)", st["HUMAN-REVIEW"].get("reviewer_role"))
        else:
            row(k, "لم تُسجل")
    title("البوابات")
    row("الجولة", "PASS", "FAIL", "NOT_VERIFIED", "NOT_APPLICABLE", bold=True, fill=light)
    for k in order:
        gc = Counter(g.get("status") for g in (rounds.get(k) or {}).get("gates") or [])
        row(k, gc.get("PASS", 0), gc.get("FAIL", 0), gc.get("NOT_VERIFIED", 0), gc.get("NOT_APPLICABLE", 0))
    title("الإغلاق حسب الجولة")
    head_row = r
    row("الجولة", *STATUSES, bold=True, fill=light)
    for k in order:
        vc = Counter((o.get("history") or {}).get(k, {}).get("status") for o in vals)
        row(f"الجولة {k}", *[vc.get(x, 0) for x in STATUSES])
    if order:
        ch = BarChart()
        ch.type, ch.grouping, ch.overlap = "col", "stacked", 100
        ch.title, ch.height, ch.width = "قيم الإغلاق حسب الجولة", 7, 16
        ch.add_data(Reference(ws, min_col=2, max_col=5, min_row=head_row, max_row=head_row + len(order)),
                    titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=head_row + 1, max_row=head_row + len(order)))
        ws.add_chart(ch, f"K{head_row}")
    paths = Counter(h.get("closure_path") for o in vals for h in (o.get("history") or {}).values()
                    if h.get("status") == "مغلقة" and h.get("closure_path"))
    row("مسارات الإغلاق (17.6)", *[f"{k}: {v}" for k, v in paths.items()] or ["—"])
    title("موانع الإصدار الحالية")
    for prob in (rounds.get(last) or {}).get("stage_problems") or ["لا توجد"]:
        row(prob)
    for col, width in zip("ABCDEFGHI", (34, 16, 16, 16, 16, 16, 16, 16, 16)):
        ws.column_dimensions[col].width = width
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0


DISP_SHORT = {"UPHELD_UNCHANGED": "مؤيدة", "UPHELD_WITH_REVISION": "مؤيدة بتعديل", "NARROWED_TO_GCO_SCOPE": "مضيّقة",
              "ROUTED_OUTSIDE_GCO": "محالة", "WITHHELD_FOR_EVIDENCE": "محجوبة للدليل",
              "ESCALATED_TO_GCO_REVIEWER": "مصعّدة"}
POS_LIST = ("KEEP", "REVISE", "ROUTE", "ASK", "ESCALATE")


def register_name(reg: dict, round_no: int) -> str:
    from cdf_gco_crms.config import round_schema as S
    short = re.sub(r'[\\/:*?"<>|]', "", reg.get("package_short_name") or reg["document"]["name"]).strip()
    return f"CDF-GCO-CRMS_سجل مراجعة_{short}_{dt.date.today().isoformat()}_الجولة {S.ordinal(round_no)}.xlsx"


# ===================================================================================== outputs, metadata, gates
def set_docx_properties(path: Path, title: str, working_copy: bool) -> None:
    """09.4 on a commented Word package: Author, LastModifiedBy, Title, times, Company; working-copy mark."""
    from cdf_gco_crms.config import workbook_settings as W
    from cdf_gco_crms.protocol.render import _set_company
    from cdf_gco_crms.release.authorization_gate import _EMPTY_CORE, _set_core_element, mark_working_copy_docx
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    core = parts.get("docProps/core.xml", _EMPTY_CORE.encode()).decode("utf-8")
    core = re.sub(r"<dc:creator>.*?</dc:creator>|<dc:creator/>", "", core, flags=re.S)
    core = re.sub(r"<dc:title>.*?</dc:title>|<dc:title/>", "", core, flags=re.S)
    core = re.sub(r"<dcterms:(created|modified)[^>]*>.*?</dcterms:\1>", "", core, flags=re.S)
    core = re.sub(r"<cp:(category|keywords)>.*?</cp:\1>", "", core, flags=re.S)
    core = _set_core_element(core, "lastModifiedBy", W.AUTHOR)
    extra = (f"<dc:creator>{W.AUTHOR}</dc:creator><dc:title>{title}</dc:title>"
             f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
             f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>')
    core = core.replace("</cp:coreProperties>", extra + "</cp:coreProperties>", 1)
    parts["docProps/core.xml"] = core.encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        names = [i.filename for i in infos]
        for name in names + [n for n in parts if n not in names]:
            z.writestr(name, parts[name])
    tmp.replace(path)
    _set_company(path)
    if working_copy:
        mark_working_copy_docx(path)


def out_name(out: Path, stem: str, ext: str, working_copy: bool) -> Path:
    from cdf_gco_crms.release.authorization_gate import working_copy_name
    p = out / f"{stem}{ext}"
    return working_copy_name(p) if working_copy else p


def brand_logo() -> Path | None:
    """The on-light wordmark shipped with the kit (Word/register use only; never recoloured for the dark band)."""
    p = HERE / "shared" / "brand" / "cdf-wordmark-on-light.png"
    return p if p.exists() else None


def logo_on_dark(a=None) -> Path | None:
    """The official white-on-dark logo for the dashboard's identity band (DASH_HEADER): only a file the GCO user
    supplies with --logo-on-dark, used unchanged. None leaves the logo slot empty (G-UX-02 NOT_VERIFIED)."""
    p = getattr(a, "logo_on_dark", None) if a is not None else None
    if p and Path(p).exists():
        return Path(p)
    p = HERE / "shared" / "brand" / "cdf-logo-on-dark.png"     # drop-in place for the official file
    return p if p.exists() else None


def run_gates(xlsx: Path, docx: Path, state, previous: Path | None = None,
              returned_state=None, logo: Path | None = None) -> tuple[list[dict], dict]:
    from cdf_gco_crms.qa.gates import GateContext, run_dash_gates
    from cdf_gco_crms.qa.ux_gates import run_ux_gates
    from cdf_gco_crms.word.document_comments import check_package
    rows = []
    vcs = []
    if RECALC and (shutil.which("soffice") or shutil.which("libreoffice")):   # independent recalculation (10.4A.15)
        try:
            from cdf_gco_crms.qa.recalc_verify import check_view, standard_views
            work = Path(xlsx).parent / "_work" / "recalc"
            work.mkdir(parents=True, exist_ok=True)
            vcs = [check_view(state, vs, work) for vs in standard_views(state)]
        except Exception as exc:                               # noqa: BLE001
            rows.append({"gate": "recalculation", "status": "NOT_VERIFIED", "name": "LibreOffice recalculation",
                         "actual": f"{type(exc).__name__}: {exc}"})
    try:
        ctx = GateContext(xlsx=xlsx, previous_xlsx=previous, docx=docx, view_checks=vcs, returned_state=returned_state,
                          refresh={"before": str(previous), "after": str(xlsx)} if previous else None,
                          logo_source=logo)
        dash = run_dash_gates(ctx)
        res = dash + run_ux_gates(ctx, dash)
        for g in res:
            status = g.status
            if g.gate == "G-DASH-14" and previous is None:
                status = "NOT_APPLICABLE"                      # round 1: nothing was appended
            rows.append({"gate": g.gate, "status": status, "name": g.name, "actual": _cell(g.actual)})
    except Exception as exc:                                   # a gate that cannot run is never a pass
        rows.append({"gate": "G-DASH/G-UX", "status": "NOT_VERIFIED", "name": "gate run",
                     "actual": f"{type(exc).__name__}: {exc}"})
    try:
        probs = check_package(docx, xlsx, state)
        rows.append({"gate": "G-SYNC (package)", "status": "FAIL" if probs else "PASS", "name": "Word–Excel parity",
                     "actual": probs[:20]})
    except Exception as exc:
        rows.append({"gate": "G-SYNC (package)", "status": "NOT_VERIFIED", "name": "Word–Excel parity",
                     "actual": f"{type(exc).__name__}: {exc}"})
    stems = {Path(xlsx).stem.replace("INTERNAL_DRAFT__", ""), Path(docx).stem.replace("INTERNAL_DRAFT__", "")}
    import unicodedata
    rows.append({"gate": "G-STEM-1", "status": "PASS" if len({unicodedata.normalize("NFC", s) for s in stems}) == 1
                 else "FAIL", "name": "docx and xlsx stems identical", "actual": sorted(stems)})
    counts = Counter(r["status"] for r in rows)
    return rows, dict(counts)


def approve_titles(state, decision: str, approver: str, issue: bool = True):
    """At issue, the GCO user's recorded decision approves the proposed titles (10.4A.16) and freezes them.
    kit 1.1.3: with issue=False (``--approve-titles``) the GCO user's decision approves them in a working copy,
    so the dashboard shows them without the mechanical-summary tag; they are frozen only at issue."""
    from cdf_gco_crms.config import round_schema as S
    from cdf_gco_crms.rounds.round_expansion import TitleDecision, finalize_titles, mark_titles_issued
    ref = "GCO-USER-DECISION-" + hashlib.sha256(decision.encode("utf-8")).hexdigest()[:8].upper()
    today = dt.date.today().isoformat()
    todo = [TitleDecision(o.internal_id, "APPROVE", approver, today, ref) for o in state.observations
            if o.title and o.title_status == S.TITLE_PROPOSED]
    state, rep = finalize_titles(state, todo)
    if issue:
        mark_titles_issued(state)
    return state, {"decision_ref": ref, "approved": len(rep.approved), "refused": rep.refused}


def issue_allowed(args, check_status: str | None, transcribed: bool = False) -> tuple[bool, str]:
    if not args.issue:
        return False, ""
    if transcribed and not getattr(args, "quotes_confirmed", False):
        return False, ("the review text is a transcription (02.6A): issue needs --quotes-confirmed, given only after "
                       "the GCO user confirmed every quote against the original pages")
    if not (args.decision or "").strip():
        return False, "--issue needs --decision with the GCO user's instruction to issue (00A chat mode)"
    if check_status == "FAIL":
        return False, "the check failed: fix the draft before issuing"
    return True, args.decision.strip()


# ===================================================================================== commands
def cmd_info(a) -> int:
    mods = {}
    for m in ("openpyxl", "docx", "lxml", "PIL", "pdfplumber", "pypdf"):
        try:
            mod = __import__(m)
            mods[m] = getattr(mod, "__version__", "present")
        except Exception as exc:                               # noqa: BLE001
            mods[m] = f"MISSING ({type(exc).__name__})"
    required = all(not str(mods[m]).startswith("MISSING") for m in ("openpyxl", "docx", "lxml", "PIL"))
    emit({"kit_version": KIT_VERSION, "python": sys.version.split()[0], "packages": mods,
          "renderer": shutil.which("soffice") or shutil.which("libreoffice") or "not available (pages ≈, "
                      "independent recalculation NOT_VERIFIED)",
          "engine": str(HERE / "cdf_gco_crms"), "logo": str(brand_logo()) if brand_logo() else "missing",
          "logo_on_dark": str(logo_on_dark()) if logo_on_dark() else ("not supplied: the dashboard's logo slot stays "
                                                                      "empty; pass --logo-on-dark to build/next"),
          "dashboard": "one-sheet executive dashboard, two sheets (protocol v7.15 draft, pending approval)",
          "status": "OK" if required else "MISSING_PACKAGES",
          "note": "pdfplumber is needed only to review a PDF"})
    return RC_OK if required else RC_INPUT


def _chunks(lines: list[str]) -> list[tuple[int, int]]:
    out, start, size = [], 0, 0
    for i, ln in enumerate(lines):
        size += len(ln) + 1
        if size >= CHUNK_CHARS:
            out.append((start + 1, i + 1))
            start, size = i + 1, 0
    if start < len(lines):
        out.append((start + 1, len(lines)))
    return out


def cmd_receipt(a) -> int:
    lines = Path(a.file).read_text(encoding="utf-8").splitlines()
    end = next((i + 1 for i in range(len(lines) - 1, -1, -1) if lines[i].startswith("END OF PROTOCOL")), len(lines))
    rows = []
    for s, e in _chunks(lines[:end]):
        body = " ".join(lines[s - 1:e]).split()
        rows.append({"lines": f"{s}-{e}", "first8": " ".join(body[:8]), "last8": " ".join(body[-8:])})
    emit({"file": a.file, "sha256": sha256(a.file), "lines": end, "chunks": rows,
          "how_to_read": f"python cdfkit.py show {a.file} --lines A-B for each chunk, in order; the READ line of the "
                         "manifest is written only after every chunk was printed and read (00.6)"})
    return RC_OK


def cmd_show(a) -> int:
    lines = Path(a.file).read_text(encoding="utf-8").splitlines()
    m = re.fullmatch(r"(\d+)-(\d+)", a.lines or "")
    if not m:
        return fail("--lines A-B")
    s, e = int(m.group(1)), min(int(m.group(2)), len(lines))
    for i in range(s, e + 1):
        print(f"{i}\t{lines[i - 1]}")
    return RC_OK


def cmd_read(a) -> int:
    doc = Path(a.doc)
    if not doc.is_file():
        return fail(f"{doc} not found")
    out = Path(a.out or doc.parent)
    out.mkdir(parents=True, exist_ok=True)
    kind = doc_kind(doc)
    info = {"file": doc.name, "kind": kind, "sha256": sha256(doc), "bytes": doc.stat().st_size}
    rdocx = review_docx(doc, out)
    if kind != "docx":
        info["review_rendition"] = str(rdocx)
        info["note"] = ("comments are placed on this Word rendition of the PDF/XLSX; its paragraphs are exactly the "
                        "text extracted from the original")
    if kind == "docx":
        from lxml import etree
        from cdf_gco_crms.word.document_comments import DocText, _tracked_changes
        from cdf_gco_crms.word.word_sync import extract_comments
        with zipfile.ZipFile(doc) as z:
            root = etree.fromstring(z.read("word/document.xml"))
        tc = _tracked_changes(DocText(root))
        info["tracked_changes"] = {"total": len(tc), "by_author": dict(Counter(t.author for t in tc))}
        try:
            cm = extract_comments(doc)
            info["comments_by_author"] = dict(Counter(c.author for c in cm))
            info["gco_comments_with_ref"] = sum(1 for c in cm if c.internal_id)
        except Exception as exc:                               # noqa: BLE001
            info["comments_by_author"] = f"unreadable: {type(exc).__name__}"
        with zipfile.ZipFile(doc) as z:
            if "docProps/core.xml" in z.namelist():
                core = z.read("docProps/core.xml").decode("utf-8", "replace")
                info["properties"] = {k: (re.search(rf"<{k}[^>]*>(.*?)</{k}>", core, re.S) or [None, None])[1]
                                      for k in ("dc:creator", "cp:lastModifiedBy", "dc:title", "cp:revision",
                                                "dcterms:modified")}
    if is_transcribed(rdocx):
        info["source_mode"] = "TRANSCRIBED (02.6A): a reading aid, not the base version"
        info["transcription"] = transcription_record(rdocx)
    paras = doc_paragraphs(rdocx)
    lines = [f"[¶{i + 1}] {t}" for i, t in enumerate(paras) if t.strip()]
    txt = out / (doc.stem + ".paragraphs.txt")
    txt.write_text("\n".join(lines), encoding="utf-8")
    chunks = []
    for s, e in _chunks(lines):
        body = " ".join(lines[s - 1:e]).split()
        chunks.append({"lines": f"{s}-{e}", "first8": " ".join(body[:8]), "last8": " ".join(body[-8:])})
    info.update({"paragraphs": len(paras), "non_empty": len(lines), "paragraph_file": str(txt), "chunks": chunks,
                 "how_to_read": f"python cdfkit.py show '{txt}' --lines A-B for every chunk (00.6(3)); quote "
                                "observations from these paragraphs, within one paragraph each"})
    emit(info)
    return RC_OK


def cmd_check(a) -> int:
    draft = load_json(a.draft)
    rnd = int(draft.get("round") or 1)
    doc = Path(a.doc) if a.doc else None
    docx = review_docx(doc, Path(a.out or doc.parent)) if doc else None
    rep = run_check(draft, docx, rnd)
    emit(rep, Path(a.json) if a.json else None)
    return RC_FAIL if rep["status"] == "FAIL" else RC_OK


def _sorted_by_position(obs: list[dict], docx: Path) -> list[dict]:
    paras_n = [norm(t) for t in doc_paragraphs(docx)]

    def key(o):
        pi, _ = find_quote(paras_n, o.get("quote") or "", o.get("occurrence") or 1)
        para = paras_n[pi] if pi is not None else ""
        return (pi if pi is not None else 10 ** 9, para.find(norm(o.get("quote") or "")))
    return sorted(obs, key=key)


def cmd_build(a) -> int:
    from cdf_gco_crms.config import workbook_settings as W
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    from cdf_gco_crms.model.entities import Document
    from cdf_gco_crms.rounds.round_expansion import NewObservation, build_round1
    from cdf_gco_crms.word.document_comments import comment_document
    draft = load_json(a.draft)
    doc_path = Path(a.doc)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    work.mkdir(exist_ok=True)
    rdocx = review_docx(doc_path, work)
    check = run_check(draft, rdocx, 1)
    if check["status"] == "FAIL" and not a.force:
        emit({"status": "FAIL", "detail": "the draft does not pass `check`; fix it (or --force to build a working "
                                          "copy for inspection)", "check": check})
        return RC_FAIL
    transcribed = is_transcribed(rdocx)
    ok_issue, decision = issue_allowed(a, check["status"], transcribed)
    if a.issue and not ok_issue:
        return fail(decision, RC_REFUSED)
    wc = not ok_issue
    d = draft["document"]
    obs = _sorted_by_position(draft["observations"], rdocx)          # Reader_No = document order (11.3)
    document = Document(name=d["name"].strip(), code=d["code"], cover_version=d.get("cover_version"),
                        owning_department=d.get("owning_department"), is_demo=bool(d.get("is_demo")))
    new = [NewObservation(o["location"], o["quote"], compose_comment(o), None, title=o.get("title"),
                          action_summary=o.get("action_summary")) for o in obs]
    state = build_round1(document, new, date=draft.get("date") or dt.date.today().isoformat(),
                         document_version=d.get("cover_version"))
    import kit_stages as KS
    stage_problems = KS.gate(draft, state, 1)
    if not wc and stage_problems:
        emit({"status": "REFUSED", "detail": "issue blocked by the review stages (00A.7, 00A.8, G-RT-1, G-ENG-3)",
              "problems": stage_problems})
        return RC_REFUSED
    titles = None
    if not wc:
        state, titles = approve_titles(state, decision, a.approver)
    elif getattr(a, "approve_titles", None):
        state, titles = approve_titles(state, a.approve_titles, a.approver, issue=False)
    stem = W.file_stem(document.name, 1)
    xlsx = out_name(out, stem, ".xlsx", wc)
    docx_out = out_name(out, stem, ".docx", wc)
    build_workbook(state, xlsx, working_copy=wc, logo_path=logo_on_dark(a))
    rep = comment_document(rdocx, state, docx_out, round_no=1)
    set_docx_properties(docx_out, stem, wc)
    gates, counts = run_gates(xlsx, docx_out, state, logo=logo_on_dark(a))
    # register
    reg = {"kit_version": KIT_VERSION, "document": {**d, "sha256": sha256(doc_path), "base_file": doc_path.name},
           "package_short_name": draft.get("package_short_name") or d["name"],
           "rounds": {}, "observations": {}, "withdrawn": draft.get("withdrawn") or [],
           "routed": draft.get("routed") or [], "evidence_pack": draft.get("evidence_pack") or [],
           "responses": [], "closed_text": [], "evidence": [], "events": []}
    for o, so in zip(obs, state.ordered()):
        rec = {k: o.get(k) for k in OBS_FIELDS if k in o}
        rec.update({"internal_id": so.internal_id, "reader_no": so.reader_no, "birth_round": 1,
                    "words": words(plain(so.comment)),
                    "history": {"1": {"status": "مفتوحة", "severity": o.get("severity")}}})
        reg["observations"][so.internal_id] = rec
    reg["rounds"]["1"] = {"date": draft.get("date") or dt.date.today().isoformat(), "base_file": doc_path.name,
                          "base_sha256": sha256(doc_path), "document_version": d.get("cover_version"),
                          "files": {"docx": docx_out.name, "xlsx": xlsx.name}, "check": check, "gates": gates,
                          "word_report": _cell(getattr(rep, "summary", lambda: {})()),
                          "manifest": draft.get("manifest"), "read_receipt": draft.get("read_receipt"),
                          "red_team": draft.get("red_team"), "stages": draft.get("stages"),
                          "stage_problems": stage_problems, "decision": decision or None,
                          "issued_at": dt.datetime.now(dt.timezone.utc).isoformat() if decision else None}
    limitations = []
    if transcribed:
        reg["document"]["source_mode"] = "TRANSCRIBED"
        reg["document"]["transcription"] = transcription_record(rdocx)
        limitations.append("02.6A: the source is a scanned file; the review text is the assistant's transcription of the "
                           "page images, and the comments sit on a Word rendition of it. Every quote is to be checked "
                           "against the original pages before issue.")
    reg["rounds"]["1"]["limitations"] = limitations
    reg["events"].append({"at": dt.datetime.now(dt.timezone.utc).isoformat(), "event": "BUILD_ROUND_1",
                          "detail": {"working_copy": wc, "observations": len(obs)}})
    reg_json = out / "register.json"
    reg_json.write_text(json.dumps(reg, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    reg_xlsx = out / register_name(reg, 1)
    write_register_xlsx(reg, reg_xlsx)
    status = "FAIL" if counts.get("FAIL") else ("NOT_VERIFIED" if counts.get("NOT_VERIFIED") else "OK")
    emit({"status": status, "working_copy": wc, "decision": decision or None, "limitations": limitations,
          "stages_before_issue": stage_problems or "all recorded and current",
          "files": {"word": str(docx_out), "excel": str(xlsx), "register_xlsx": str(reg_xlsx),
                    "register_json": str(reg_json)},
          "titles": titles,
          "observations": [{"reader_no": so.reader_no, "internal_id": so.internal_id, "title": so.title}
                           for so in state.ordered()],
          "word": _cell(getattr(rep, "summary", lambda: {})()), "gate_counts": counts,
          "gates_not_passed": [g for g in gates if g["status"] != "PASS"],
          "keep": "register.json is the case memory: upload it again in every later round"})
    return RC_FAIL if counts.get("FAIL") else (RC_NOT_VERIFIED if counts.get("NOT_VERIFIED") else RC_OK)


def _accepted_text(docx: Path) -> str:
    return "\n".join(t for t in doc_paragraphs(docx) if t.strip())


def _core_props(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            core = z.read("docProps/core.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile, OSError):
        return {}
    return {k: (re.search(rf"<{k}[^>]*>(.*?)</{k}>", core, re.S) or [None, None])[1]
            for k in ("dc:creator", "cp:lastModifiedBy", "dc:title", "cp:revision", "dcterms:modified")}


def _intake(a, reg: dict):
    from cdf_gco_crms.ingestion.workbook_reader import parse_workbook
    from cdf_gco_crms.reconciliation.historical import merge_returned, view_sheet_edits
    delivered = parse_workbook(a.delivered_xlsx).state
    returned = parse_workbook(a.returned_xlsx)
    merged, intake = merge_returned(delivered, returned.state)
    vedits, vmissing = view_sheet_edits(a.delivered_xlsx, a.returned_xlsx)
    n = delivered.current_round + 1
    rep = {"round_to_build": n,
           "workbook": {"owner_inputs": intake.owner_inputs,
                        "gco_cell_edits_restored_I08": [f"{x.internal_id}:{x.key}" for x in intake.gco_cell_edits],
                        "late_owner_edits_I09": [f"{x.internal_id}:{x.key}" for x in intake.late_owner_edits],
                        "format_losses_restored_SC60": [f"{x.internal_id}:{x.key}" for x in intake.format_losses],
                        "missing_rows_SC40": intake.missing_rows, "notes": intake.notes,
                        "dashboard_or_helper_edits_channel_x": [f"{e.sheet}!{e.coordinate}: {e.returned!r}"
                                                               for e in vedits],
                        "dashboard_or_helper_missing": vmissing,
                        "formula_flags": [w for w in returned.warnings if w.startswith("FORMULA_IN_DATA")]},
           "files": {k: {"file": Path(v).name, "sha256": sha256(v)} for k, v in
                     (("delivered_xlsx", a.delivered_xlsx), ("returned_xlsx", a.returned_xlsx),
                      ("delivered_docx", a.delivered_docx), ("returned_docx", a.returned_docx)) if v}}
    sixth = "مغلقة – تم إغلاق الملاحظة في جولة سابقة"
    R = delivered.current_round
    if a.returned_docx:
        from cdf_gco_crms.word.document_comments import closed_text_integrity, diff_returned
        rep["properties_returned_docx_I13"] = _core_props(Path(a.returned_docx))
        if a.delivered_docx:
            diff = diff_returned(a.delivered_docx, a.returned_docx, merged)
            rep["word"] = diff.summary()
            rep["word"]["silent_edits_I03"] = [{"kind": c.kind, "paragraph": c.returned_index, "before": c.before[:200],
                                                "after": c.after[:200]} for c in diff.silent_edits][:40]
            rep["word"]["tracked_changes_by_author"] = dict(Counter(t.author for t in diff.tracked_changes))
            rep["word"]["owner_comments"] = [{"author_is_recorded_in_register_only": True, "text": c.text[:300],
                                              "nearest_ref": c.nearest_ref, "reply_to_ref": c.reply_to_ref}
                                             for c in diff.owner_comments][:60]
            rep["word"]["altered_gco_comments_detail"] = [{"internal_id": c.internal_id, "before": c.before[:200],
                                                           "after": c.after[:200]} for c in diff.altered_gco_comments]
            ratio = difflib.SequenceMatcher(None, _accepted_text(Path(a.delivered_docx)),
                                            _accepted_text(Path(a.returned_docx)), autojunk=False).ratio()
            rep["lineage_ratio_I11"] = round(ratio, 3)
            rep["lineage_note"] = ("below 0.80: base substitution (SC-56, INTEGRITY_ESCALATION); 0.80–0.90: decide "
                                   "by the comment-lineage test" if ratio < 0.9 else "derived from the issued file")
        closed = closed_text_integrity(merged, a.returned_docx, n)
        ret_paras = [norm(t) for t in doc_paragraphs(Path(a.returned_docx))]
        out16 = []
        for c in closed:
            row = {"internal_id": c.internal_id, "reader_no": c.reader_no, "status": c.status,
                   "closed_in_round": c.closed_in_round, "excerpt": c.excerpt[:300], "detail": c.detail,
                   "compared_with": "round-1 quote (no closure_text recorded)"}
            hist = (reg.get("observations", {}).get(c.internal_id, {}).get("history") or {})
            basis = next((h.get("closure_text") for k, h in sorted(hist.items(), key=lambda kv: -int(kv[0]))
                          if h.get("status") == "مغلقة" and h.get("closure_text")), None)
            if basis:
                found = find_quote(ret_paras, basis)[1] > 0
                row.update({"status": "INTACT" if found else "CHANGED_OR_MISSING", "compared_with": "closure_text",
                            "closure_text": basis[:300],
                            "detail": "" if found else "the text the row was closed on is no longer in the document "
                                                       "verbatim: assess deterioration (16.1, SC-52)"})
            out16.append(row)
        rep["closed_text_16_1"] = out16
    if any(is_transcribed(Path(x)) for x in (a.delivered_docx, a.returned_docx) if x):
        rep["transcription_caution_02_6A"] = (
            "at least one Word file is a transcription: differences, silent edits, closed-text changes and claim flags "
            "may be reading errors. Confirm each against the original pages before reopening a row, raising an "
            "integrity signal or closing on VERIFIED_TEXT (set confirmed_against_original: true).")
    rows = []
    claimed = ("تم التطبيق", "تم التطبيق بصيغة بديلة", "تم التطبيق جزئياً")
    ret_paras = [norm(t) for t in doc_paragraphs(Path(a.returned_docx))] if a.returned_docx else None
    for o in merged.ordered():
        prev = o.value(R)
        cells = o.cells.get(R)
        resp = plain(cells.response) if cells and cells.response else None
        impl = cells.impl if cells else None
        no_input = resp in (None, "") or (resp or "").startswith("يرجى بيان الإجراء")
        flag = []
        if prev != "مغلقة" and impl == sixth:
            flag.append("I-10 sixth value in an open row (no input, SC-54)")
        if (prev != "مغلقة" and impl in claimed and ret_paras is not None
                and find_quote(ret_paras, plain(o.quote))[1] > 0):
            flag.append("I-01 candidate: implementation claimed but the quoted text is unchanged; check the "
                        "location the owner names before closing (E.0.2)")
        if prev == "مغلقة" and resp and not resp.startswith("لا يلزم إجراء"):
            flag.append("closure disputed in the text cell (SC-06, 10.6)")
        needs = prev != "مغلقة" or bool(flag) or any(c["internal_id"] == o.internal_id and c["status"] in
                                                      ("CHANGED", "MISSING", "CHANGED_OR_MISSING")
                                                      for c in rep.get("closed_text_16_1", []))
        rows.append({"internal_id": o.internal_id, "reader_no": o.reader_no, "status_round_" + str(R): prev,
                     "owner_response": None if no_input else resp,
                     "owner_status": None if (impl or "").startswith("اختر") else impl, "flags": flag,
                     "quote": plain(o.quote)[:300], "needs_assessment": needs})
    rep["rows"] = rows
    return merged, rep, n


def cmd_intake(a) -> int:
    reg = load_json(a.register)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    merged, rep, n = _intake(a, reg)
    template = {"round": n, "date": dt.date.today().isoformat(), "document_version": None,
                "assessments": [{"internal_id": r["internal_id"], "reader_no": r["reader_no"],
                                 "status": "", "feedback": "", "closure_path": None, "closure_basis": None,
                                 "severity": None, "integrity_signals": []}
                                for r in rep["rows"] if r["needs_assessment"]],
                "new_observations": [],
                "_help": {"status": list(STATUSES),
                          "feedback": "≤ 40 words (07.2); opens with the location line when the passage moved; "
                                      "ends with 'المطلوب: …' (يتطلب تعديل, مفتوحة) or 'شرط الإغلاق: …' (مغلقة بشرط)",
                          "late_round": "from round 3, rows not closed use comment / recommendation / proposed_text "
                                        "(08.3A) instead of feedback",
                          "closure_path": list(CLOSURE_PATHS) + ["required when status is مغلقة (17.6)"],
                          "rows_closed_without_entry": "carried closed automatically"}}
    tpath = out / f"ROUND-{n}.template.json"
    tpath.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    rep["template"] = str(tpath)
    emit(rep, out / f"intake-round-{n}.json")
    flagged = rep["workbook"]["gco_cell_edits_restored_I08"] or rep["workbook"]["formula_flags"]
    return RC_FAIL if flagged else RC_OK


def cmd_next(a) -> int:
    from cdf_gco_crms.config import round_schema as S
    from cdf_gco_crms.config import workbook_settings as W
    from cdf_gco_crms.excel.workbook_builder import build_workbook
    from cdf_gco_crms.rounds.round_expansion import NewObservation, RoundAssessment, RoundInput, apply_round
    from cdf_gco_crms.word.document_comments import comment_document
    reg = load_json(a.register)
    spec = load_json(a.round)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    merged, intake, n = _intake(a, reg)
    if int(spec.get("round") or 0) != n:
        return fail(f"ROUND.json says round {spec.get('round')}, the workbook needs round {n}")
    problems = []
    ret_paras = [norm(t) for t in doc_paragraphs(Path(a.returned_docx))]
    for x in spec.get("assessments", []):
        if x.get("status") not in STATUSES:
            problems.append(f"{x.get('internal_id')}: status must be one of {STATUSES}")
        if x.get("status") == "مغلقة" and x.get("closure_path") not in CLOSURE_PATHS:
            problems.append(f"{x.get('internal_id')}: closure_path required for مغلقة (17.6)")
        if x.get("status") in ("مغلقة", "مغلقة بشرط") and x.get("closure_path") in ("GCO_REASSESSMENT",
                                                                                   "RISK_ACCEPTED") \
                and not (x.get("decision_ref") or "").strip():
            problems.append(f"{x.get('internal_id')}: {x.get('closure_path')} needs decision_ref (the reviewer's "
                            "recorded decision, 17.6–17.7)")
        if x.get("status") in ("مغلقة", "مغلقة بشرط") and x.get("closure_path") in (None, "VERIFIED_TEXT"):
            ct = (x.get("closure_text") or "").strip()
            if not ct:
                problems.append(f"{x.get('internal_id')}: closure_text required (the exact current text the row "
                                "is closed on, within one paragraph; 16.1)")
            elif find_quote(ret_paras, ct)[1] == 0:
                problems.append(f"{x.get('internal_id')}: closure_text not found verbatim in the returned document")
            elif is_transcribed(Path(a.returned_docx)) and x.get("confirmed_against_original") is not True:
                problems.append(f"{x.get('internal_id')}: the returned text is a transcription; closing on it needs "
                                "confirmed_against_original: true from the GCO user (02.6A)")
        fb = compose_feedback(x)
        text = plain(fb) if fb else ""
        late = bool(x.get("recommendation") or x.get("proposed_text"))
        if not late:
            body = "\n".join(ln for ln in text.split("\n") if not ln.startswith("الجولة "))
            if words(body) > 40 + words(x.get("acknowledgment") or ""):
                problems.append(f"{x.get('internal_id')}: feedback {words(body)} words > 40 (07.2)")
            if x.get("status") in ("يتطلب تعديل", "مفتوحة") and "المطلوب:" not in text:
                problems.append(f"{x.get('internal_id')}: 'المطلوب:' line missing (08.3)")
            if x.get("status") == "مغلقة بشرط" and "شرط الإغلاق:" not in text:
                problems.append(f"{x.get('internal_id')}: 'شرط الإغلاق:' line missing (08.3)")
        for bad in _INTEGRITY + _SELF_REVERSAL:
            if bad in text:
                problems.append(f"{x.get('internal_id')}: prohibited phrase '{bad}' (G-INT-3 / G-HIST-2)")
    rdocx = Path(a.returned_docx)
    check = run_check(spec, rdocx, n) if spec.get("new_observations") else {"status": "PASS"}
    if check["status"] == "FAIL":
        problems.append("new observations fail `check`")
    if problems and not a.force:
        emit({"status": "FAIL", "problems": problems, "check": check if spec.get("new_observations") else None})
        return RC_FAIL
    ok_issue, decision = issue_allowed(a, "FAIL" if problems else "PASS", is_transcribed(rdocx))
    if a.issue and not ok_issue:
        return fail(decision, RC_REFUSED)
    wc = not ok_issue
    try:
        assessments = [RoundAssessment(x["internal_id"], n, x["status"], compose_feedback(x),
                                       x.get("closure_path") if x["status"] == "مغلقة" else None,
                                       action_summary=x.get("action_summary"))
                       for x in spec.get("assessments", [])]
    except (KeyError, ValueError) as exc:
        return fail(f"assessment rejected: {exc}")
    rin = RoundInput(n, spec.get("date") or dt.date.today().isoformat(), spec.get("document_version"),
                     assessments,
                     [NewObservation(o["location"], o["quote"], compose_comment(o), o.get("reason"),
                                     title=o.get("title"), action_summary=o.get("action_summary"))
                      for o in _sorted_by_position(spec.get("new_observations") or [], rdocx)])
    from cdf_gco_crms.rounds.round_parser import SchemaError
    try:
        new_state, rep = apply_round(merged, rin)
    except SchemaError as exc:
        return fail(f"{exc} (every row not مغلقة at the start of the round needs an assessment)")
    import kit_stages as KS
    stage_problems = KS.gate(spec, new_state, n)
    if not wc and stage_problems:
        emit({"status": "REFUSED", "detail": "issue blocked by the review stages (00A.7, 00A.8, G-RT-1, G-ENG-3)",
              "problems": stage_problems})
        return RC_REFUSED
    titles = None
    if not wc:
        new_state, titles = approve_titles(new_state, decision, a.approver)
    elif getattr(a, "approve_titles", None):
        new_state, titles = approve_titles(new_state, a.approve_titles, a.approver, issue=False)
    stem = W.file_stem(new_state.document.name, n)
    xlsx = out_name(out, stem, ".xlsx", wc)
    docx_out = out_name(out, stem, ".docx", wc)
    build_workbook(new_state, xlsx, working_copy=wc, logo_path=logo_on_dark(a))
    wrep = comment_document(rdocx, new_state, docx_out, round_no=n,
                            prior_docx=Path(a.delivered_docx) if a.delivered_docx else None)
    set_docx_properties(docx_out, stem, wc)
    from cdf_gco_crms.ingestion.workbook_reader import parse_workbook
    gates, counts = run_gates(xlsx, docx_out, new_state, previous=Path(a.delivered_xlsx),
                              returned_state=parse_workbook(a.returned_xlsx).state, logo=logo_on_dark(a))
    # register
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    amap = {x["internal_id"]: x for x in spec.get("assessments", [])}
    for o in new_state.ordered():
        rec = reg["observations"].setdefault(o.internal_id, {"internal_id": o.internal_id, "reader_no": o.reader_no,
                                                             "birth_round": o.birth_round, "history": {}})
        x = amap.get(o.internal_id, {})
        rec.setdefault("history", {})[str(n)] = {"status": o.value(n), "feedback": plain(o.cells[n].feedback)
                                                 if o.cells.get(n) and o.cells[n].feedback else None,
                                                 "closure_path": x.get("closure_path"),
                                                 "closure_basis": x.get("closure_basis"),
                                                 "decision_ref": x.get("decision_ref"),
                                                 "closure_text": x.get("closure_text"),
                                                 "severity": x.get("severity") or rec.get("severity")}
    by_quote = {(o.get("quote") or "").strip(): o for o in spec.get("new_observations") or []}
    for iid in rep.new_ids:
        o = new_state.by_id()[iid]
        src = by_quote.get(plain(o.quote).strip(), {})
        reg["observations"][iid].update({k: src.get(k) for k in OBS_FIELDS if k in src})
        reg["observations"][iid].update({"internal_id": iid, "reader_no": o.reader_no, "birth_round": n,
                                         "words": words(plain(o.comment))})
    for r in intake["rows"]:
        if r["owner_response"] or r["owner_status"] or r["flags"]:
            x = amap.get(r["internal_id"], {})
            reg.setdefault("responses", []).append({"round": n - 1, "internal_id": r["internal_id"],
                                                    "response": r["owner_response"], "impl": r["owner_status"],
                                                    "integrity_signal": x.get("integrity_signals") or r["flags"],
                                                    "integrity_class": x.get("integrity_class")})
    for c in intake.get("closed_text_16_1", []):
        reg.setdefault("closed_text", []).append({"round": n, **c})
    for k, v in intake["files"].items():
        reg.setdefault("evidence", []).append({"round": n, "file": v["file"], "sha256": v["sha256"],
                                               "properties": intake.get("properties_returned_docx_I13")
                                               if k == "returned_docx" else None})
    reg["rounds"][str(n)] = {"date": rin.date, "base_file": rdocx.name, "base_sha256": sha256(rdocx),
                             "document_version": spec.get("document_version"),
                             "files": {"docx": docx_out.name, "xlsx": xlsx.name}, "gates": gates,
                             "intake": {k: intake[k] for k in ("workbook", "lineage_ratio_I11", "word")
                                        if k in intake},
                             "word_report": _cell(getattr(wrep, "summary", lambda: {})()),
                             "manifest": spec.get("manifest"), "red_team": spec.get("red_team"),
                             "stages": spec.get("stages"), "stage_problems": stage_problems,
                             "decision": decision or None, "issued_at": now if decision else None}
    reg.setdefault("events", []).append({"at": now, "event": f"BUILD_ROUND_{n}",
                                         "detail": {"working_copy": wc, "assessed": len(rep.assessed),
                                                    "carried_closed": len(rep.carried_closed),
                                                    "reopened": rep.reopened, "new": rep.new_ids}})
    reg_json = out / "register.json"
    reg_json.write_text(json.dumps(reg, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    reg_xlsx = out / register_name(reg, n)
    write_register_xlsx(reg, reg_xlsx)
    counts_v = Counter(o.value(n) for o in new_state.ordered())
    emit({"status": "FAIL" if counts.get("FAIL") else ("NOT_VERIFIED" if counts.get("NOT_VERIFIED") else "OK"),
          "round": n, "working_copy": wc, "decision": decision or None,
          "files": {"word": str(docx_out), "excel": str(xlsx), "register_xlsx": str(reg_xlsx),
                    "register_json": str(reg_json)},
          "closure_counts": dict(counts_v), "titles": titles,
          "stages_before_issue": stage_problems or "all recorded and current", "assessed": len(rep.assessed), "carried_closed": len(rep.carried_closed),
          "reopened": rep.reopened, "new": rep.new_ids, "word": _cell(getattr(wrep, "summary", lambda: {})()),
          "gate_counts": counts, "gates_not_passed": [g for g in gates if g["status"] != "PASS"],
          "keep": "upload the new register.json, Word and Excel files in the next round"})
    return RC_FAIL if counts.get("FAIL") else (RC_NOT_VERIFIED if counts.get("NOT_VERIFIED") else RC_OK)


def cmd_pages(a) -> int:
    pdf = Path(a.pdf)
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        return fail("pages takes a .pdf file")
    layer = text_layer_pages(pdf)
    files, method = render_pages(pdf, Path(a.out), int(a.dpi), int(a.first), int(a.last) if a.last else None)
    if not files:
        emit({"status": "NOT_AVAILABLE", "detail": "no PDF renderer in this sandbox (PyMuPDF, pypdfium2 or pdftoppm). "
              "Ask the user to upload one image per page (screenshots or scans), then transcribe from those.",
              "text_layer_characters_by_page": layer})
        return RC_INPUT
    emit({"status": "OK", "method": method, "dpi": int(a.dpi), "pages": [str(f) for f in files],
          "text_layer_characters_by_page": layer,
          "next": "view every page image and transcribe it verbatim in the transcript format (AGENT-GUIDE section 8): "
                  "'=== صفحة N ===' then one paragraph per line; mark every word you cannot read with certainty as "
                  "[؟]; never complete a word from context; then run `transcript`."})
    return RC_OK


def cmd_transcript(a) -> int:
    """The assistant's page-by-page transcription becomes a Word rendition marked as transcribed (02.6A)."""
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    src = Path(a.source)
    if not src.is_file():
        return fail(f"{src} not found (the original scanned file)")
    try:
        rows = parse_transcript(Path(a.transcript).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return fail(str(exc))
    pages = sorted({pg for pg, _ in rows})
    layer = text_layer_pages(src) if src.suffix.lower() == ".pdf" else {}
    missing = [n for n in range(1, (max(layer) if layer else max(pages)) + 1) if n not in pages]

    def rtl(par):
        ppr = par._p.get_or_add_pPr()
        bidi = OxmlElement("w:bidi")
        bidi.set(qn("w:val"), "1")
        ppr.append(bidi)

    d = Document()
    h = d.add_paragraph()
    r = h.add_run(src.stem)
    r.bold, r.font.size = True, Pt(14)
    rtl(h)
    note = d.add_paragraph()
    n = note.add_run("نص مُفرَّغ من صور صفحات المستند الممسوح ضوئياً لأغراض المراجعة؛ ليس النسخة الأصلية، "
                     "و[؟] كلمة لم تُقرأ بيقين.")
    n.font.size, n.font.color.rgb = Pt(8), RGBColor(0x66, 0x74, 0x82)
    rtl(note)
    current = None
    for pg, line in rows:
        if pg != current:
            current = pg
            sep = d.add_paragraph()
            sr = sep.add_run(f"— صفحة {pg} —")
            sr.font.size, sr.font.color.rgb = Pt(8), RGBColor(0x66, 0x74, 0x82)
            rtl(sep)
        rtl(d.add_paragraph(line))
    cp = d.core_properties
    cp.keywords = TRANSCRIBED_MARK
    cp.title = src.stem + " – نص مُفرَّغ"
    from cdf_gco_crms.config import workbook_settings as W
    cp.author = cp.last_modified_by = W.AUTHOR
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{src.stem} - نص مُفرَّغ.docx"
    d.save(dest)
    unreadable = sum(line.count(UNREADABLE) for _, line in rows)
    rec = {"method": "AI_VISION_TRANSCRIPTION", "platform": a.platform, "source_file": src.name,
           "source_sha256": sha256(src), "transcript_file": Path(a.transcript).name,
           "transcript_sha256": sha256(a.transcript), "pages_transcribed": pages, "pages_missing": missing,
           "paragraphs": len(rows), "unreadable_marks": unreadable,
           "at": dt.datetime.now(dt.timezone.utc).isoformat()}
    dest.with_suffix(".transcription.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    emit({"status": "OK" if not missing else "INCOMPLETE", "review_docx": str(dest), "record": rec,
          "next": "use this Word file as --doc for read, check and build; quote only readable text; list the "
                  "limitation in the delivery note (02.6A)" if not missing else
                  f"pages {missing} are not transcribed: transcribe them (00.6(3)) or list them and withhold every "
                  "observation that depends on them"})
    return RC_OK if not missing else RC_FAIL


def cmd_dump(a) -> int:
    """The independent reader's input (Art. 20.1): Reader_No, title, location, quote and comment text (and follow-ups),
    read from the delivered workbook. No Internal_ID, register field, challenge record or severity is included."""
    from cdf_gco_crms.ingestion.workbook_reader import parse_workbook
    st = parse_workbook(a.workbook).state
    import kit_stages as KS
    R = int(a.round or st.current_round)
    rows = KS.read_rows(st, R)
    emit({"document": st.document.name, "round": R, "comments": rows,
          "for": "the independent read of Art. 20 in a new conversation; give it this output, Art. 20, 03A, 07.4 "
                 "and Annex F only"})
    return RC_OK


def cmd_selftest(a) -> int:
    import kit_selftest
    kit_selftest.RECALC = bool(a.recalc)
    rep = kit_selftest.run(a.keep)
    emit(rep)
    return RC_OK if rep["status"] == "PASS" else RC_FAIL


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cdfkit", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    p = sub.add_parser("pages")
    p.add_argument("pdf")
    p.add_argument("--out", required=True)
    p.add_argument("--dpi", default="150")
    p.add_argument("--first", default="1")
    p.add_argument("--last")
    p = sub.add_parser("transcript")
    p.add_argument("transcript")
    p.add_argument("--source", required=True, help="the original scanned file")
    p.add_argument("--out", required=True)
    p.add_argument("--platform", default="", help="Claude chat or ChatGPT, and the model shown")
    p = sub.add_parser("stage-packet")
    p.add_argument("stage", choices=["MAT-01", "CHALLENGE", "MAT-02", "MAT-03", "ADJUDICATE", "READ"])
    p.add_argument("--draft", required=True, help="draft.json (round 1) or ROUND-n.json")
    p.add_argument("--protocol", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--doc", help="the document (MAT-01, CHALLENGE)")
    p.add_argument("--workbook", help="the working-copy workbook (READ)")
    p = sub.add_parser("stage-record")
    p.add_argument("stage", choices=["MAT-01", "CHALLENGE", "MAT-02", "MAT-03", "ADJUDICATE", "READ", "HUMAN-REVIEW"])
    p.add_argument("result", help="the JSON the fresh chat returned, saved as a file")
    p.add_argument("--draft", required=True)
    p = sub.add_parser("dump")
    p.add_argument("workbook")
    p.add_argument("--round")
    p = sub.add_parser("selftest")
    p.add_argument("--keep", help="folder to keep the synthetic run in (default: a temporary folder)")
    p.add_argument("--recalc", action="store_true", help="also run the LibreOffice recalculation (slower)")
    p = sub.add_parser("receipt")
    p.add_argument("file")
    p = sub.add_parser("show")
    p.add_argument("file")
    p.add_argument("--lines", required=True)
    p = sub.add_parser("read")
    p.add_argument("doc")
    p.add_argument("--out")
    p = sub.add_parser("check")
    p.add_argument("draft")
    p.add_argument("--doc")
    p.add_argument("--out")
    p.add_argument("--json")
    for name in ("build", "next"):
        p = sub.add_parser(name)
        p.add_argument("draft" if name == "build" else "round")
        p.add_argument("--out", required=True)
        p.add_argument("--issue", action="store_true")
        p.add_argument("--decision")
        p.add_argument("--approver", default="المستخدم المسؤول في إدارة الحوكمة والامتثال المؤسسي",
                       help="the role (not a personal name) recorded as approving titles at issue")
        p.add_argument("--approve-titles", metavar="DECISION",
                       help="kit 1.1.3: the GCO user's recorded decision approving the proposed titles in a working "
                            "copy (10.4A.16); titles freeze only at issue")
        p.add_argument("--force", action="store_true", help="build a working copy even when the check fails")
        p.add_argument("--quotes-confirmed", action="store_true",
                       help="transcribed source: the GCO user confirmed every quote against the original pages")
        p.add_argument("--no-recalc", action="store_true",
                       help="skip the LibreOffice recalculation (faster; G-DASH-05/16 stay NOT_VERIFIED)")
        p.add_argument("--logo-on-dark", help="the official white-on-dark logo file (PNG) for the dashboard's dark "
                                              "identity band; used unchanged; without it the logo slot stays empty")
        if name == "build":
            p.add_argument("--doc", required=True)
    for p in (sub.choices["next"], sub.add_parser("intake")):
        p.add_argument("--register", required=True)
        p.add_argument("--delivered-xlsx", required=True)
        p.add_argument("--returned-xlsx", required=True)
        p.add_argument("--delivered-docx")
        p.add_argument("--returned-docx", required=(p.prog.endswith("next")))
        if p.prog.endswith("intake"):
            p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    global RECALC
    RECALC = not getattr(a, "no_recalc", False) and not getattr(a, "recalc_off", False)
    return {"info": cmd_info, "receipt": cmd_receipt, "show": cmd_show, "read": cmd_read, "check": cmd_check,
            "build": cmd_build, "intake": cmd_intake, "next": cmd_next, "selftest": cmd_selftest,
            "dump": cmd_dump, "pages": cmd_pages, "transcript": cmd_transcript,
            "stage-packet": lambda x: __import__("kit_stages").cmd_stage_packet(x),
            "stage-record": lambda x: __import__("kit_stages").cmd_stage_record(x)}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
