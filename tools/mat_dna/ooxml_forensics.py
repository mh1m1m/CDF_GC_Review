#!/usr/bin/env python3
"""Native Word (OOXML) forensic extraction and version comparison for the MAT professional-DNA study.

Generic, public-safe code: it reads any .docx pair and writes an observation-evolution register. It never
embeds, prints or ships document content by default; the outputs it writes go to the private workspace
(``private/mat_dna_workspace``), which is git-ignored.

What is extracted (Article 02.2 of the MAT directive)
  * native comments (word/comments.xml): id, author, initials, date, text, anchored paragraph(s), anchored text
  * threads (word/commentsExtended.xml): paraId → parent paraId, resolved flag; people.xml authors
  * tracked changes in the body: w:ins / w:del runs with author and date (text replaced / deleted)
  * comments living in headers, footers, footnotes, endnotes and text boxes (same parser over every part)
  * document provenance: docProps/core.xml (creator, lastModifiedBy, revision, created/modified)
  * integrity: SHA-256 of the file, part list, missing parts reported as absent (never as errors)

Comparison (Article 03)
  Original ↔ reviewed comments are matched by a hierarchy: identical comment id + identical anchor text; identical
  anchor text; identical normalised comment text; article/clause of the anchor paragraph; then a conservative
  similarity on comment text (supporting evidence only, flagged for manual review). A comment absent from the
  reviewed version is REMOVED_FROM_VERSION — never "withdrawn": a withdrawal needs a documented decision.

Usage
  python tools/mat_dna/ooxml_forensics.py extract FILE.docx --out private/mat_dna_workspace/extract
  python tools/mat_dna/ooxml_forensics.py compare ORIGINAL.docx REVIEWED.docx --out private/mat_dna_workspace/compare
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import sys
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
DCT = "http://purl.org/dc/terms/"
NS = {"w": W, "w14": W14, "w15": W15}
BODY_PARTS_RE = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
COMMENTS = "word/comments.xml"
COMMENTS_EX = "word/commentsExtended.xml"
PEOPLE = "word/people.xml"
CORE = "docProps/core.xml"
ARTICLE_RE = re.compile(r"(?:المادة|البند|الفقرة)\s*\(?\s*([\d٠-٩]+(?:[-–.][\d٠-٩]+)*)\s*\)?")
_DIACRITICS = re.compile("[ً-ْٰـ]")

CHANGE_TYPES = ("KEEP_UNCHANGED", "KEEP_WITH_REVISIONS", "STRENGTHEN", "SOFTEN", "SHORTEN", "EXPAND", "CONVERT_TO_QUESTION",
                "CONVERT_TO_RECOMMENDATION", "MERGE", "SPLIT", "NARROW_SCOPE", "REQUEST_EVIDENCE", "ESCALATE",
                "REMOVED_FROM_VERSION", "DOCUMENTED_WITHDRAWAL", "ADDED_IN_REVIEW", "EMPTIED_IN_PLACE", "UNMATCHED", "DECISION_NOT_OBSERVED",
                "DROP_NUMBER_HEADER", "DROP_REF", "DROP_RATIONALE", "DROP_RECOMMENDATION", "DROP_PROPOSED_TEXT", "REWRITTEN", "REFERRAL_TO_COLLEAGUE")
_QUESTION_MARKERS = ("؟", "?", "هل ", "ما مدى", "ما الاساس", "ما هي", "ما هو", "من الجهة", "كيف ", "يرجى التوضيح", "يرجى الافادة", "نامل التوضيح", "نامل الافادة")
_RECOMMEND_MARKERS = ("نوصي", "يوصى", "التوصية", "نقترح", "يقترح", "يتعين", "يجب", "ينبغي", "نرى اهمية", "نؤكد", "التاكيد على", "المطلوب", "يستبدل",
                      "تضاف", "يضاف", "يحذف", "تحذف", "احلال", "اضافة بند", "تحديد سقف", "بالنص الاتي")
_FLAG_MARKERS = ("يوجد خطا", "خطا في", "ناقص", "مكرر", "غير واضح", "لا يتسق", "يتعارض")
_REQUEST_MARKERS = ("يرجى", "نامل", "نرجو")
_ASSERTIVE = ("يجب", "يتعين", "لا يجوز", "يخالف", "مخالف", "باطل", "إلزام", "ملزم")
_SOFT = ("قد ", "يُفضّل", "يفضل", "نرى", "نأمل", "يُستحسن", "يمكن", "ربما", "بحسب الاقتضاء")


def norm(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "")
    t = _DIACRITICS.sub("", t)
    t = t.replace("ـ", "").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", t).strip().lower()


_QUESTION_MARKERS = tuple(norm(m) for m in _QUESTION_MARKERS)
_RECOMMEND_MARKERS = tuple(norm(m) for m in _RECOMMEND_MARKERS)
_FLAG_MARKERS = tuple(norm(m) for m in _FLAG_MARKERS)
_REQUEST_MARKERS = tuple(norm(m) for m in _REQUEST_MARKERS)
_ASSERTIVE = tuple(norm(m) for m in _ASSERTIVE)
_SOFT = tuple(norm(m) for m in _SOFT)
_REFERRAL_MARKERS = tuple(norm(m) for m in ("الزملاء", "الأخ ", "الاخ ", "قطاع ", "من قبل ", "الإدارة المختصة", "الجهة المختصة"))
_HEADER_RE = re.compile(r"^\s*الملاحظة\s*#?\s*[\d٠-٩]+\s*$", re.M)
_RATIONALE_SPLIT = re.compile(r"التوصي[ةه]\s*:")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ data
@dataclass
class TrackedChange:
    part: str
    kind: str                 # ins | del
    author: str
    date: str
    text: str
    paragraph_index: int
    paragraph_text: str


@dataclass
class Comment:
    comment_id: str
    part: str
    author: str
    initials: str
    date: str
    text: str
    para_id: str
    parent_para_id: str
    parent_comment_id: str
    resolved: bool
    anchor_text: str
    anchor_paragraph_index: int
    anchor_paragraph_text: str
    anchor_article: str
    anchor_part: str
    anchored: bool
    text_sha256: str
    classification: str = ""   # DIRECT_QUESTION / DIRECT_RECOMMENDATION / QUESTION_WITH_RECOMMENDATION / ...


@dataclass
class Extraction:
    file: str
    sha256: str
    size: int
    parts: list[str]
    missing_parts: list[str]
    core: dict
    people: list[dict]
    comments: list[Comment]
    tracked_changes: list[TrackedChange]
    paragraphs: dict[str, list[str]]
    unanchored_comments: list[str]
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"file": Path(self.file).name, "sha256": self.sha256, "size": self.size, "parts": len(self.parts),
                "missing_parts": self.missing_parts, "core": self.core, "people": self.people,
                "comments": len(self.comments), "threads": sum(1 for c in self.comments if c.parent_comment_id),
                "comments_by_author": _count(c.author for c in self.comments),
                "comments_by_part": _count(c.anchor_part for c in self.comments),
                "unanchored_comments": self.unanchored_comments,
                "tracked_changes": len(self.tracked_changes),
                "tracked_changes_by_author": _count(f"{t.author}:{t.kind}" for t in self.tracked_changes),
                "paragraphs": {k: len(v) for k, v in self.paragraphs.items()}, "warnings": self.warnings}


def _count(items) -> dict:
    out: dict = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))


# ------------------------------------------------------------------ parsing
def _text_of(el) -> str:
    """Visible text of an element: w:t and w:delText inside w:del, tabs and breaks as spaces."""
    parts = []
    for node in el.iter():
        tag = etree.QName(node).localname if isinstance(node.tag, str) else ""
        if tag in ("t", "delText"):
            parts.append(node.text or "")
        elif tag in ("tab", "br", "cr"):
            parts.append(" ")
    return re.sub(r"[  ]+", " ", "".join(parts)).strip()


def _paragraph_text_without_deletions(p) -> str:
    parts = []
    for node in p.iter():
        tag = etree.QName(node).localname if isinstance(node.tag, str) else ""
        if tag == "t":
            anc = node.getparent()
            inside_del = False
            while anc is not None and anc is not p:
                if etree.QName(anc).localname == "del":
                    inside_del = True
                    break
                anc = anc.getparent()
            if not inside_del:
                parts.append(node.text or "")
        elif tag in ("tab", "br", "cr"):
            parts.append(" ")
    return re.sub(r"[  ]+", " ", "".join(parts)).strip()


def _article_of(text: str, prior: list[str]) -> str:
    for t in [text] + prior[::-1][:6]:
        m = ARTICLE_RE.search(t or "")
        if m:
            return m.group(0).strip()
    return ""


def extract(path) -> Extraction:
    p = Path(path)
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        parts = {n: z.read(n) for n in names if n.endswith(".xml")}
    missing = [x for x in (COMMENTS, COMMENTS_EX, PEOPLE, CORE, "word/commentsIds.xml") if x not in names]
    warnings: list[str] = []
    core = {}
    if CORE in parts:
        root = etree.fromstring(parts[CORE])
        for tag, ns in (("creator", DC), ("lastModifiedBy", CP), ("revision", CP), ("created", DCT), ("modified", DCT), ("title", DC)):
            el = root.find(f"{{{ns}}}{tag}")
            core[tag] = (el.text or "") if el is not None else None
    people = []
    if PEOPLE in parts:
        for person in etree.fromstring(parts[PEOPLE]).findall(f"{{{W15}}}person"):
            pid = person.find(f"{{{W15}}}presenceInfo")
            people.append({"author": person.get(f"{{{W15}}}author"), "provider_id": pid.get(f"{{{W15}}}providerId") if pid is not None else None})
    threads: dict[str, dict] = {}
    if COMMENTS_EX in parts:
        for ex in etree.fromstring(parts[COMMENTS_EX]).findall(f"{{{W15}}}commentEx"):
            threads[(ex.get(f"{{{W15}}}paraId") or "").upper()] = {"parent": (ex.get(f"{{{W15}}}paraIdParent") or "").upper(),
                                                                   "done": ex.get(f"{{{W15}}}done") == "1"}
    # comment bodies
    raw_comments: dict[str, dict] = {}
    if COMMENTS in parts:
        for c in etree.fromstring(parts[COMMENTS]).findall(f"{{{W}}}comment"):
            cid = c.get(f"{{{W}}}id")
            first_p = c.find(f"{{{W}}}p")
            para_id = (first_p.get(f"{{{W14}}}paraId") if first_p is not None else "") or ""
            raw_comments[cid] = {"author": c.get(f"{{{W}}}author") or "", "initials": c.get(f"{{{W}}}initials") or "",
                                 "date": c.get(f"{{{W}}}date") or "", "text": "\n".join(_text_of(pp) for pp in c.findall(f"{{{W}}}p")).strip(),
                                 "para_id": para_id.upper()}
    para_id_to_cid = {v["para_id"]: k for k, v in raw_comments.items() if v["para_id"]}
    # body parts: paragraphs, anchors, tracked changes
    paragraphs: dict[str, list[str]] = {}
    anchors: dict[str, dict] = {}
    tracked: list[TrackedChange] = []
    for name in sorted(n for n in names if BODY_PARTS_RE.match(n)):
        root = etree.fromstring(parts[name])
        texts: list[str] = []
        open_ranges: dict[str, dict] = {}
        for idx, pel in enumerate(root.iter(f"{{{W}}}p")):
            ptext = _paragraph_text_without_deletions(pel)
            texts.append(ptext)
            # range markers inside this paragraph (also inside text boxes, which are nested w:p)
            for node in pel.iter():
                if not isinstance(node.tag, str):
                    continue
                tag = etree.QName(node).localname
                if tag == "commentRangeStart":
                    open_ranges[node.get(f"{{{W}}}id")] = {"part": name, "start_idx": idx, "chunks": []}
                elif tag == "commentRangeEnd":
                    cid = node.get(f"{{{W}}}id")
                    r = open_ranges.pop(cid, {"part": name, "start_idx": idx, "chunks": []})
                    anchors[cid] = {"part": name, "paragraph_index": r["start_idx"], "text": " ".join(r["chunks"]).strip(),
                                    "paragraph_text": ptext, "prior": texts[max(0, r["start_idx"] - 6):r["start_idx"]]}
                elif tag == "commentReference" and node.get(f"{{{W}}}id") not in anchors:
                    cid = node.get(f"{{{W}}}id")
                    anchors.setdefault(cid, {"part": name, "paragraph_index": idx, "text": "", "paragraph_text": ptext,
                                             "prior": texts[max(0, idx - 6):idx]})
                elif tag == "t":
                    for r in open_ranges.values():
                        r["chunks"].append(node.text or "")
                elif tag in ("ins", "del"):
                    tracked.append(TrackedChange(name, tag, node.get(f"{{{W}}}author") or "", node.get(f"{{{W}}}date") or "",
                                                 _text_of(node), idx, ptext))
        paragraphs[name] = texts
    comments: list[Comment] = []
    unanchored: list[str] = []
    for cid, c in raw_comments.items():
        a = anchors.get(cid)
        th = threads.get(c["para_id"], {})
        parent_pid = th.get("parent", "")
        text = c["text"]
        comments.append(Comment(cid, COMMENTS, c["author"], c["initials"], c["date"], text, c["para_id"], parent_pid,
                                para_id_to_cid.get(parent_pid, ""), bool(th.get("done")),
                                a["text"] if a else "", a["paragraph_index"] if a else -1, a["paragraph_text"] if a else "",
                                _article_of(a["paragraph_text"], a["prior"]) if a else "", a["part"] if a else "",
                                a is not None, sha256_text(text), classify_comment(text)))
        if a is None:
            unanchored.append(cid)
    if unanchored:
        warnings.append(f"{len(unanchored)} comment(s) without a range or reference in any part; kept, not discarded")
    comments.sort(key=lambda c: (c.anchor_part, c.anchor_paragraph_index, int(c.comment_id) if c.comment_id.isdigit() else 0))
    return Extraction(str(p), sha256_file(p), p.stat().st_size, names, missing, core, people, comments, tracked, paragraphs, unanchored, warnings)


# ------------------------------------------------------------------ classification helpers (deterministic, documented)
def _has(normalised: str, markers) -> bool:
    """Marker present as a whole word or phrase: a word marker never matches inside another word (هل inside المؤهلة);
    a punctuation marker (؟) matches anywhere."""
    for m in markers:
        pat = re.escape(m)
        if re.match(r"\w", m):
            pat = r"(?<!\w)" + pat
        if re.search(r"\w$", m):
            pat = pat + r"(?!\w)"
        if re.search(pat, normalised):
            return True
    return False


def classify_comment(text: str) -> str:
    """Primary functional class of a comment (Article 06.1 of the directive); mutually exclusive.

    Markers are matched on a hamza- and diacritic-insensitive form so that quickly typed comments (نامل, اضافة, التاكيد)
    classify like their formal spellings. Classes: DIRECT_QUESTION, QUESTION_WITH_RECOMMENDATION, CONDITIONAL_RECOMMENDATION,
    PROPOSED_AMENDMENT (carries replacement wording), DIRECT_RECOMMENDATION, INFORMATION_REQUEST, DEFECT_FLAG (states a defect,
    prescribes nothing), WORDING_INSERTION (a few words to be inserted in the passage), EMPTY, OTHER.
    """
    t = norm(text or "")
    if not t:
        return "EMPTY"
    has_q = _has(t, _QUESTION_MARKERS)
    has_r = _has(t, _RECOMMEND_MARKERS)
    if has_q and has_r:
        return "QUESTION_WITH_RECOMMENDATION"
    if has_q:
        return "DIRECT_QUESTION"
    if has_r:
        if any(k in t for k in ("في حال", "اذا ", "ان كان", "متى ما", "بشرط")):
            return "CONDITIONAL_RECOMMENDATION"
        if any(k in t for k in ("بالنص الاتي", "النص المقترح", "يستبدل", "تضاف", "يضاف", "يحذف", "تحذف", "لتصبح", "احلال")):
            return "PROPOSED_AMENDMENT"
        return "DIRECT_RECOMMENDATION"
    if _has(t, _REQUEST_MARKERS):
        return "INFORMATION_REQUEST"
    if _has(t, _FLAG_MARKERS):
        return "DEFECT_FLAG"
    if len(t.split()) <= 5:
        return "WORDING_INSERTION"
    return "OTHER"


def tone_score(text: str) -> dict:
    t = norm(text or "")
    return {"assertive_markers": sum(t.count(m) for m in _ASSERTIVE), "soft_markers": sum(t.count(m) for m in _SOFT),
            "words": len(re.findall(r"\w+", t)), "sentences": max(1, len(re.findall(r"[.؟!?]\s|\n", t)) + (0 if t.rstrip().endswith((".", "؟", "?", "!")) else 1))}


def change_type(original: str, revised: str) -> list[str]:
    """Observed textual change types between two versions of one comment (several may apply)."""
    out: list[str] = []
    if norm(original) == norm(revised):
        return ["KEEP_UNCHANGED"]
    co, cr = classify_comment(original), classify_comment(revised)
    if co != cr:
        if "QUESTION" in cr and "QUESTION" not in co:
            out.append("CONVERT_TO_QUESTION")
        elif "RECOMMENDATION" in cr and "QUESTION" in co and "RECOMMENDATION" not in co:
            out.append("CONVERT_TO_RECOMMENDATION")
    so, sr = tone_score(original), tone_score(revised)
    if sr["words"] <= 0.75 * so["words"]:
        out.append("SHORTEN")
    elif sr["words"] >= 1.33 * so["words"]:
        out.append("EXPAND")
    if sr["assertive_markers"] > so["assertive_markers"] and sr["soft_markers"] <= so["soft_markers"]:
        out.append("STRENGTHEN")
    elif sr["soft_markers"] > so["soft_markers"] or sr["assertive_markers"] < so["assertive_markers"]:
        out.append("SOFTEN")
    if any(k in revised and k not in original for k in ("يرجى تزويدنا", "يرجى إرفاق", "الدليل", "ما يثبت", "المستند")):
        out.append("REQUEST_EVIDENCE")
    out.extend(_structural_changes(original, revised))
    if not out:
        out.append("KEEP_WITH_REVISIONS")
    return out


def _parts(text: str) -> dict:
    """Header line, reference line, rationale (before التوصية:) and recommendation (after it) of an engine-style comment."""
    t = text or ""
    header = bool(_HEADER_RE.search(t))
    ref = bool(REF_RE.search(t))
    body = _HEADER_RE.sub("", t)
    body = REF_RE.sub("", body).replace("REF:", "")
    sp = _RATIONALE_SPLIT.split(body, maxsplit=1)
    rationale = norm(sp[0]) if len(sp) == 2 else ""
    recommendation = norm(sp[1]) if len(sp) == 2 else norm(body)
    return {"header": header, "ref": ref, "rationale": rationale, "recommendation": recommendation,
            "bullets": t.count("•"), "proposed_text": ("بالنص الاتي" in norm(t)) or ('("' in t) or ("(\"" in t)}


def _structural_changes(original: str, revised: str) -> list[str]:
    """Which parts of an engine-style comment survived into the revised text (documented, deterministic)."""
    po, pr = _parts(original), _parts(revised)
    out: list[str] = []
    if po["header"] and not pr["header"]:
        out.append("DROP_NUMBER_HEADER")
    if po["ref"] and not pr["ref"]:
        out.append("DROP_REF")
    nr = norm(revised)
    if po["rationale"] and po["recommendation"]:
        rat_kept = po["rationale"][:60] in nr or difflib.SequenceMatcher(None, po["rationale"], nr).ratio() >= 0.5
        rec_kept = po["recommendation"][:60] in nr or difflib.SequenceMatcher(None, po["recommendation"], nr).ratio() >= 0.5
        if not rat_kept and rec_kept:
            out.append("DROP_RATIONALE")
        if rat_kept and not rec_kept:
            out.append("DROP_RECOMMENDATION")
        if not rat_kept and not rec_kept and nr:
            out.append("REWRITTEN")
    if po["proposed_text"] and not pr["proposed_text"] and nr:
        out.append("DROP_PROPOSED_TEXT")
    if po["bullets"] > 1 and pr["bullets"] < po["bullets"] and nr:
        out.append("NARROW_SCOPE")
    if any(m in nr for m in _REFERRAL_MARKERS) and not any(m in norm(original) for m in _REFERRAL_MARKERS):
        out.append("REFERRAL_TO_COLLEAGUE")
    return out


# ------------------------------------------------------------------ comparison
@dataclass
class Match:
    observation_id: str
    original_comment_id: str
    reviewed_comment_id: str
    document_article: str
    document_anchor: str
    original_text: str
    reviewed_text: str
    original_author: str
    reviewed_author: str
    matching_method: str
    matching_confidence: float
    change_types: list[str]
    original_class: str
    reviewed_class: str
    attribution_status: str
    manual_review: bool
    provenance: str = ""
    replaces_at_same_passage: str = ""


REF_RE = re.compile(r"(?:[A-Z]{1,3}-)?[A-Z]{2,4}-R\d-(\d{3})")
MATCH_METHODS = ("PARA_ID", "REF_CODE", "ANCHOR_TEXT", "COMMENT_TEXT_EXACT", "SAME_PARAGRAPH_DATE_CONTINUITY", "TEXT_SIMILARITY", "NONE")
PROVENANCE = ("UNCHANGED", "EDITED_IN_PLACE", "RECREATED_AT_ANCHOR", "NEW_COMMENT", "ABSENT")


def _minute(date: str) -> str:
    return (date or "")[:16]


def _derived(original: str, revised: str) -> bool:
    """True when the revised text is textually derived from the original (substring or ≥ 0.3 similarity)."""
    a, b = norm(original), norm(revised)
    if not b:
        return True   # emptied in place
    if b in a or a in b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.3


def _ref_number(text: str) -> str:
    m = REF_RE.search(text or "")
    return m.group(1) if m else ""


def compare(original: Extraction, reviewed: Extraction, *, reviewer_name_hint: str | None = None) -> dict:
    """Observation-level register between two versions (Article 03).

    Matching uses package evidence in this order, never article numbers alone:
      PARA_ID    the comment's first-paragraph w14:paraId survived (comment edited in place or untouched)
      REF_CODE   the reviewed text still carries the original reference number (even truncated)
      ANCHOR_TEXT the commented passage is the same text
      COMMENT_TEXT_EXACT identical comment text at a different place
      SAME_PARAGRAPH_DATE_CONTINUITY same commented paragraph and the reviewed comment keeps the original creation date
      TEXT_SIMILARITY ≥ 0.6 as a last resort (flagged for manual review)
    Provenance per reviewed comment: UNCHANGED, EDITED_IN_PLACE (original creation date kept), RECREATED_AT_ANCHOR (new date,
    text derived from the original), NEW_COMMENT. A new comment on a passage whose original comment disappeared is linked
    through replaces_at_same_passage, which is an observed co-location, not evidence of a decision.
    """
    orig_dates = {_minute(c.date) for c in original.comments if c.date}   # Word drops the seconds on re-save
    used: set[str] = set()
    matches: list[Match] = []
    rev_by_pid = {c.para_id: c for c in reviewed.comments if c.para_id}
    rev_by_ref: dict[str, list[Comment]] = {}
    rev_by_anchor: dict[str, list[Comment]] = {}
    rev_by_text: dict[str, list[Comment]] = {}
    rev_by_par: dict[tuple[str, int], list[Comment]] = {}
    for c in reviewed.comments:
        if (r := _ref_number(c.text)):
            rev_by_ref.setdefault(r, []).append(c)
        rev_by_anchor.setdefault(norm(c.anchor_text), []).append(c)
        rev_by_text.setdefault(norm(c.text), []).append(c)
        rev_by_par.setdefault((c.anchor_part, c.anchor_paragraph_index), []).append(c)

    def free(cs):
        return [c for c in cs if c.comment_id not in used]

    def provenance(o: Comment, c: Comment) -> str:
        if norm(o.text) == norm(c.text):
            return "UNCHANGED"
        if c.date and _minute(c.date) in orig_dates:
            return "EDITED_IN_PLACE"
        return "RECREATED_AT_ANCHOR"

    n = 0
    for o in original.comments:
        n += 1
        oid = f"OBS-{n:03d}"
        cand = None; method = ""; conf = 0.0
        if o.para_id and o.para_id in rev_by_pid and rev_by_pid[o.para_id].comment_id not in used:
            cand, method, conf = rev_by_pid[o.para_id], "PARA_ID", 1.0
        if cand is None and (r := _ref_number(o.text)):
            for c in free(rev_by_ref.get(r, [])):
                cand, method, conf = c, "REF_CODE", 0.98
                break
        if cand is None and o.anchor_text:
            for c in free(rev_by_anchor.get(norm(o.anchor_text), [])):
                if _ref_number(c.text) and _ref_number(c.text) != _ref_number(o.text):
                    continue   # carries another observation's reference: not this one
                if not (_minute(c.date) in orig_dates or _derived(o.text, c.text)):
                    continue   # a newly created comment with unrelated text is a new observation, not a rephrasing
                cand, method, conf = c, "ANCHOR_TEXT", 0.95
                break
        if cand is None:
            for c in free(rev_by_text.get(norm(o.text), [])):
                cand, method, conf = c, "COMMENT_TEXT_EXACT", 0.9
                break
        if cand is None and o.anchored:
            for c in free(rev_by_par.get((o.anchor_part, o.anchor_paragraph_index), [])):
                if c.date and _minute(c.date) in orig_dates and not _ref_number(c.text):
                    cand, method, conf = c, "SAME_PARAGRAPH_DATE_CONTINUITY", 0.8
                    break
        if cand is None:
            best, ratio = None, 0.0
            for c in free(reviewed.comments):
                if c.date and _minute(c.date) not in orig_dates:
                    continue   # a newly created comment is never matched by similarity alone
                rt = difflib.SequenceMatcher(None, norm(o.text), norm(c.text)).ratio()
                if rt > ratio:
                    best, ratio = c, rt
            if best is not None and ratio >= 0.6:
                cand, method, conf = best, "TEXT_SIMILARITY", round(0.3 + 0.3 * ratio, 2)
        if cand is not None:
            used.add(cand.comment_id)
            types = change_type(o.text, cand.text)
            if not norm(cand.text):
                types = ["EMPTIED_IN_PLACE"]
            matches.append(Match(oid, o.comment_id, cand.comment_id, o.anchor_article or cand.anchor_article, o.anchor_text[:160],
                                 o.text, cand.text, o.author, cand.author, method, conf, types, o.classification, cand.classification,
                                 _attribution(cand.author, reviewer_name_hint), conf < 0.8, provenance(o, cand), ""))
        else:
            matches.append(Match(oid, o.comment_id, "", o.anchor_article, o.anchor_text[:160], o.text, "", o.author, "",
                                 "NONE", 0.0, ["REMOVED_FROM_VERSION"], o.classification, "", "DECISION_NOT_OBSERVED", True, "ABSENT", ""))
    removed_by_par: dict[tuple[str, int], list[Match]] = {}
    for m in matches:
        if "REMOVED_FROM_VERSION" in m.change_types:
            o = next(c for c in original.comments if c.comment_id == m.original_comment_id)
            removed_by_par.setdefault((o.anchor_part, o.anchor_paragraph_index), []).append(m)
    for c in reviewed.comments:
        if c.comment_id not in used:
            n += 1
            co_located = removed_by_par.get((c.anchor_part, c.anchor_paragraph_index), [])
            link = ",".join(m.observation_id for m in co_located)
            for m in co_located:
                m.replaces_at_same_passage = (m.replaces_at_same_passage + "," if m.replaces_at_same_passage else "") + f"OBS-{n:03d}"
            matches.append(Match(f"OBS-{n:03d}", "", c.comment_id, c.anchor_article, c.anchor_text[:160], "", c.text, "", c.author,
                                 "NONE", 0.0, ["ADDED_IN_REVIEW"], "", c.classification, _attribution(c.author, reviewer_name_hint), False,
                                 "NEW_COMMENT", link))
    by_rev: dict[str, list[Match]] = {}
    for m in matches:
        if m.reviewed_comment_id:
            by_rev.setdefault(m.reviewed_comment_id, []).append(m)
    for ms in by_rev.values():
        if len(ms) > 1:
            for m in ms:
                if "MERGE" not in m.change_types:
                    m.change_types.append("MERGE")
    return {"original": original.summary(), "reviewed": reviewed.summary(), "matches": [asdict(m) for m in matches],
            "statistics": statistics(original, reviewed, matches), "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "note": ("REMOVED_FROM_VERSION is an observed file change, not a documented withdrawal; ADDED_IN_REVIEW is a comment present "
                     "only in the reviewed version; replaces_at_same_passage records co-location only; attribution comes from the "
                     "comment author field and the reviewer name hint, which is not proof of authorship of every passage")}


def _attribution(author: str, hint: str | None) -> str:
    if not author:
        return "UNKNOWN_AUTHOR"
    if hint and norm(hint) and norm(hint) in norm(author):
        return "REVIEWER_NAME_RECORDED_AS_AUTHOR"
    return "RECORDED_AUTHOR_DIFFERS_FROM_REVIEWER_NAME"


def statistics(original: Extraction, reviewed: Extraction, matches: list[Match]) -> dict:
    def dist(comments):
        counts = _count(c.classification for c in comments)
        total = len(comments) or 1
        return {"count": len(comments), "by_class": counts,
                "question_pct": round(100 * sum(v for k, v in counts.items() if k == "DIRECT_QUESTION") / total, 1),
                "recommendation_pct": round(100 * sum(v for k, v in counts.items() if k in ("DIRECT_RECOMMENDATION", "CONDITIONAL_RECOMMENDATION", "PROPOSED_AMENDMENT")) / total, 1),
                "mixed_pct": round(100 * counts.get("QUESTION_WITH_RECOMMENDATION", 0) / total, 1)}
    kinds = _count(t for m in matches for t in m.change_types)
    return {"original": dist(original.comments), "reviewed": dist(reviewed.comments), "change_types": kinds,
            "retained": sum(1 for m in matches if "KEEP_UNCHANGED" in m.change_types),
            "revised": sum(1 for m in matches if m.reviewed_comment_id and m.original_comment_id and "KEEP_UNCHANGED" not in m.change_types),
            "removed_from_version": kinds.get("REMOVED_FROM_VERSION", 0), "added_in_review": kinds.get("ADDED_IN_REVIEW", 0),
            "converted_to_question": kinds.get("CONVERT_TO_QUESTION", 0), "converted_to_recommendation": kinds.get("CONVERT_TO_RECOMMENDATION", 0),
            "emptied_in_place": kinds.get("EMPTIED_IN_PLACE", 0), "provenance": _count(m.provenance for m in matches),
            "merged": kinds.get("MERGE", 0), "manual_review_queue": sum(1 for m in matches if m.manual_review),
            "documented_withdrawals": 0, "denominator_note": "percentages over the comments of each version; one observation per original comment"}


# ------------------------------------------------------------------ outputs
def write_extraction(ex: Extraction, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(ex.summary(), ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "comments.json").write_text(json.dumps([asdict(c) for c in ex.comments], ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "tracked_changes.json").write_text(json.dumps([asdict(t) for t in ex.tracked_changes], ensure_ascii=False, indent=1), encoding="utf-8")


def write_register_xlsx(report: dict, path: Path) -> None:
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Evolution"
    cols = ["observation_id", "original_comment_id", "reviewed_comment_id", "document_article", "document_anchor", "original_text",
            "reviewed_text", "original_author", "reviewed_author", "matching_method", "matching_confidence", "change_types",
            "original_class", "reviewed_class", "attribution_status", "manual_review", "provenance", "replaces_at_same_passage"]
    ws.append(cols)
    for m in report["matches"]:
        ws.append([", ".join(m[c]) if isinstance(m[c], list) else m[c] for c in cols])
    ws2 = wb.create_sheet("Statistics")
    for k, v in report["statistics"].items():
        ws2.append([k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v])
    ws3 = wb.create_sheet("Sources")
    for label, s in (("original", report["original"]), ("reviewed", report["reviewed"])):
        for k, v in s.items():
            ws3.append([label, k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v])
    wb.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract"); e.add_argument("docx"); e.add_argument("--out", required=True)
    c = sub.add_parser("compare"); c.add_argument("original"); c.add_argument("reviewed"); c.add_argument("--out", required=True)
    c.add_argument("--reviewer-name", help="name hint used only for the attribution flag (never printed in public outputs)")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        ex = extract(a.docx)
        write_extraction(ex, Path(a.out))
        print(json.dumps(ex.summary(), ensure_ascii=False, indent=1))
        return 0
    o, r = extract(a.original), extract(a.reviewed)
    rep = compare(o, r, reviewer_name_hint=a.reviewer_name)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "MAT_OBSERVATION_EVOLUTION_REGISTER.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    write_register_xlsx(rep, out / "MAT_OBSERVATION_EVOLUTION_REGISTER.xlsx")
    print(json.dumps({"original": rep["original"]["comments"], "reviewed": rep["reviewed"]["comments"], **rep["statistics"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
