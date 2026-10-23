"""Word lifecycle on REAL reviewed documents (patch register V712-028..036; protocol Art. 08.2, 08.3, 13, 16.1).

``word_sync`` builds a *synthetic* reviewed document for the regression suite. This module works on the
document the owner actually sent: any .docx, possibly carrying other authors' comments, tracked changes
(w:ins / w:del), tables, footnotes, numbering, headers. Four operations, one guard:

* ``comment_document`` anchors the GCO comments of a review state onto the real document. Round 1 writes one
  top-level comment per observation (08.2 shape: bold label line, white 2-pt "REF:" line, body with bold
  labels); round n writes the follow-up of every row not مغلقة at the start of the round and of every row
  reopened in the round (16.1) as a NATIVE REPLY (w15 commentsExtended) to the root comment that is already in
  the returned document, found by its REF line, and a new top-level comment for every row born in round n.
  The passage is located in the accepted view of the body (tracked insertions count, deletions do not; tables
  included) at four levels: exact, normalised (NFC, whitespace, diacritics, lam-alef), long prefix, and, as a
  flagged fallback, the best-matching paragraph. Document text is never modified; non-GCO comments and tracked
  changes are never touched; every zip member that is not one of the six comment-related parts is written back
  byte for byte. Range markers are placed at paragraph-child level, so a run inside w:ins or w:hyperlink keeps
  its wrapper's XML intact (the anchor then covers the wrapper, never less than the quote).
* ``diff_returned`` compares the document the owner returned with the one GCO delivered: tracked changes,
  silent paragraph edits (accepted-view diff not explained by a tracked change), GCO comments missing, altered
  or whose anchor moved, and comments the owner added.
* ``closed_text_integrity`` classifies the passage of every row closed in the previous round as INTACT,
  MOVED_IDENTICAL, CHANGED or MISSING (16.1) without touching the state.
* ``check_package`` returns the blocking problems of a Word + Excel package (duplicate REFs, Word/workbook
  mismatch through ``word_sync.reconcile``, broken comment relationships, unresolved thread parents, missing
  comments part).
* ``atomic_output`` is the write guard: the destination is only ever replaced by a complete, verified file; on
  any failure it stays untouched and ``<destination>.rejected.json`` beside it records the reason.

Limitations are documented on the functions: anchor movement is judged from the range markers and the quoted
text only (Word keeps no history of where a range used to be); a passage split across two paragraphs is not
located; the location line of a recorded move names a page/article, not text, so it informs the finding but
cannot itself locate the passage.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import difflib
import hashlib
import json
import os
import re
import traceback
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lxml import etree

from ..config import round_schema as S
from ..model.entities import GText, Observation, ReviewState, Segment, plain_text
from .word_sync import (COMMENTS_EX_CT, COMMENTS_EX_PART, COMMENTS_EX_REL, COMMENTS_IDS_CT, COMMENTS_IDS_PART,
                        COMMENTS_IDS_REL, CT_NS, GCO_AUTHOR, MCNS, REF_RE, REL_NS, W14NS, W15NS, W16CIDNS, WNS,
                        WordComment, extract_comments)

GCO_INITIALS = "حوكمة"
FONT = "Calibri"
COMMENTS_PART = "word/comments.xml"
COMMENTS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
DOC_PART = "word/document.xml"
DOC_RELS = "word/_rels/document.xml.rels"
CT_PART = "[Content_Types].xml"
XMLNS = "http://www.w3.org/XML/1998/namespace"
TOUCHED_PARTS = (DOC_PART, DOC_RELS, CT_PART, COMMENTS_PART, COMMENTS_EX_PART, COMMENTS_IDS_PART)

MOVED_LINE_RE = re.compile(r"تغي[ّ]?ر موضع الملاحظة إلى\s*(?P<where>.+)$")
_ELLIPSIS_RE = re.compile(r"(?:…|\.{3,})")
_MARKS_RE = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")   # tashkeel, tatweel
_ZW = set("​‌‍‎‏‪‫‬‭‮⁦⁧⁨⁩﻿")
_LAM_ALEF_LIG = {c: "لا" for c in "ﻵﻶﻷﻸﻹﻺﻻﻼ"}
_ALEFS = set("أإآٱ")
EXCERPT = 60


def w(tag: str) -> str:
    return f"{{{WNS}}}{tag}"


_T, _P, _R, _TBL, _INS, _DEL, _MOVETO, _MOVEFROM = (w(x) for x in ("t", "p", "r", "tbl", "ins", "del", "moveTo", "moveFrom"))
_RS, _RE_, _RREF, _RPR, _PPR = (w(x) for x in ("commentRangeStart", "commentRangeEnd", "commentReference", "rPr", "pPr"))
_DELETED = {_DEL, _MOVEFROM}


# ================================================================================ text normalisation
def normalise(text: str) -> tuple[str, list[int]]:
    """Matching form of ``text`` and, per normalised character, the index of the original character.

    NFKC per character (presentation forms to base letters), lam-alef ligatures to the two letters, hamza
    forms after lam folded to alef, diacritics/tatweel/zero-width marks dropped, whitespace runs collapsed
    to one space. Both the quote and the document go through the same function, so the map is enough to
    translate a match back to run offsets.
    """
    out: list[str] = []
    idx: list[int] = []
    pending = False
    for i, ch in enumerate(text):
        repl = _LAM_ALEF_LIG.get(ch) or unicodedata.normalize("NFKC", ch)
        for c in repl:
            if c in _ZW or _MARKS_RE.match(c):
                continue
            if c.isspace():
                pending = True
                continue
            if pending:
                if out:
                    out.append(" ")
                    idx.append(i)
                pending = False
            if c in _ALEFS and out and out[-1] == "ل":
                c = "ا"
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def _nkey(text: str) -> str:
    return normalise(text)[0]


def _quote_parts(quote: str) -> list[str]:
    """Fragments of a quote split on ellipses, trimmed ("… text …" and "text … text")."""
    return [p.strip() for p in _ELLIPSIS_RE.split(S.nfc(quote or "")) if p.strip()]


def _containment(needle_n: str, hay_n: str) -> float:
    """Share of the (normalised) needle's words found, in order, in the haystack (0..1). Word level, because
    character-level blocks credit unrelated Arabic paragraphs with their many short common letter runs."""
    qw, hw = needle_n.split(), hay_n.split()
    if not qw or not hw:
        return 0.0
    sm = difflib.SequenceMatcher(None, qw, hw, autojunk=False)
    return min(1.0, sum(b.size for b in sm.get_matching_blocks()) / len(qw))


def _excerpt(text: str, n: int = EXCERPT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ================================================================================ accepted-view model
@dataclass
class Atom:
    run: etree._Element
    text: str
    start: int

    @property
    def end(self) -> int:
        return self.start + len(self.text)


@dataclass
class Para:
    index: int
    el: etree._Element
    atoms: list[Atom]
    text: str
    in_table: bool
    ntext: str = ""
    nmap: list[int] = field(default_factory=list)

    @property
    def has_tracked_change(self) -> bool:
        return any(True for _ in self.el.iter(_INS, _DEL, _MOVETO, _MOVEFROM))


@dataclass
class Match:
    para: Para
    start: int
    end: int
    kind: str                      # exact | normalised | prefix | fallback
    detail: str = ""

    @property
    def text(self) -> str:
        return self.para.text[self.start:self.end]


@dataclass
class RangeInfo:
    cid: str
    start: etree._Element | None = None
    end: etree._Element | None = None
    ref_run: etree._Element | None = None
    atoms: list[Atom] = field(default_factory=list)
    para_indices: list[int] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.start is not None and self.end is not None

    @property
    def text(self) -> str:
        return "".join(a.text for a in self.atoms)


def _run_text(r: etree._Element) -> str:
    parts = []
    for ch in r:
        tag = ch.tag
        if tag == _T:
            parts.append(ch.text or "")
        elif tag == w("tab"):
            parts.append("\t")
        elif tag in (w("br"), w("cr")):
            parts.append("\n")
        elif tag == w("noBreakHyphen"):
            parts.append("-")
    return "".join(parts)


class DocText:
    """Accepted-view text of a document body: paragraphs (tables included), their text-bearing runs, and the
    comment ranges found in it. Runs under w:del / w:moveFrom are not text; runs under w:ins are."""

    def __init__(self, root: etree._Element):
        self.root = root
        self.body = root.find(w("body"))
        if self.body is None:
            raise ValueError("document.xml has no w:body")
        self.paras: list[Para] = []
        self._para_of_el: dict[etree._Element, Para] = {}
        atom_by_run: dict[etree._Element, Atom] = {}
        for i, p in enumerate(self.body.iter(_P)):
            atoms: list[Atom] = []
            pos = 0
            for r in p.iter(_R):
                if not self._belongs(r, p):
                    continue
                txt = S.nfc(_run_text(r))
                a = Atom(r, txt, pos)
                pos += len(txt)
                atoms.append(a)
                atom_by_run[r] = a
            in_table = any(anc.tag == _TBL for anc in p.iterancestors())
            para = Para(i, p, atoms, "".join(a.text for a in atoms), in_table)
            para.ntext, para.nmap = normalise(para.text)
            self.paras.append(para)
            self._para_of_el[p] = para
        # comment ranges, one pass in document order
        self.ranges: dict[str, RangeInfo] = {}
        open_ids: list[str] = []
        for el in self.body.iter():
            tag = el.tag
            if tag == _RS:
                cid = el.get(w("id"))
                self.ranges.setdefault(cid, RangeInfo(cid)).start = el
                open_ids.append(cid)
            elif tag == _RE_:
                cid = el.get(w("id"))
                self.ranges.setdefault(cid, RangeInfo(cid)).end = el
                if cid in open_ids:
                    open_ids.remove(cid)
            elif tag == _RREF:
                cid = el.get(w("id"))
                self.ranges.setdefault(cid, RangeInfo(cid)).ref_run = el.getparent()
            elif tag == _R and open_ids:
                a = atom_by_run.get(el)
                if a is None:
                    continue
                pi = self.para_index_of(el)
                for cid in open_ids:
                    rng = self.ranges[cid]
                    rng.atoms.append(a)
                    if pi is not None and pi not in rng.para_indices:
                        rng.para_indices.append(pi)

    @staticmethod
    def _belongs(r: etree._Element, p: etree._Element) -> bool:
        anc = r.getparent()
        while anc is not None and anc is not p:
            if anc.tag == _P or anc.tag in _DELETED:
                return False
            anc = anc.getparent()
        return anc is p

    def para_index_of(self, el: etree._Element) -> int | None:
        anc = el
        while anc is not None:
            if anc.tag == _P and anc in self._para_of_el:
                return self._para_of_el[anc].index
            anc = anc.getparent()
        return None

    # ---------------------------------------------------------------- locating a quoted passage
    def locate(self, quote: str, paras: list[Para] | None = None, *, allow_prefix: bool = True) -> Match | None:
        parts = _quote_parts(quote)
        if not parts:
            return None
        paras = self.paras if paras is None else paras
        for kind in ("exact", "normalised"):
            for para in paras:
                m = self._find_parts(para, parts, kind)
                if m is not None:
                    return m
        if not allow_prefix:
            return None
        nq, _ = normalise(parts[0])
        min_len = max(24, len(nq) // 3)
        lengths = [len(nq)] + [k for k in range(len(nq) - 1, 0, -1) if nq[k] == " "]
        for L in lengths:
            if L < min_len:
                break
            prefix = nq[:L].rstrip()
            for para in paras:
                pos = para.ntext.find(prefix)
                if pos >= 0:
                    s, e = para.nmap[pos], para.nmap[pos + len(prefix) - 1] + 1
                    return Match(para, s, e, "prefix", f"first {len(prefix)} normalised characters of the quote")
        return None

    @staticmethod
    def _find_parts(para: Para, parts: list[str], kind: str) -> Match | None:
        if kind == "exact":
            hay, nmap = para.text, None
            needles = parts
        else:
            hay, nmap = para.ntext, para.nmap
            needles = [normalise(p)[0] for p in parts]
        pos = 0
        first = last = None
        for nd in needles:
            if not nd:
                continue
            k = hay.find(nd, pos)
            if k < 0:
                return None
            if first is None:
                first = k
            last = k + len(nd)
            pos = last
        if first is None:
            return None
        if nmap is None:
            return Match(para, first, last, kind)
        return Match(para, nmap[first], nmap[last - 1] + 1, kind)

    def best_paragraph(self, quote: str, paras: list[Para] | None = None) -> tuple[Para | None, float]:
        nq = _nkey(" ".join(_quote_parts(quote)))
        best, best_r = None, 0.0
        for para in (self.paras if paras is None else paras):
            if not para.ntext:
                continue
            r = _containment(nq, para.ntext)
            if r > best_r:
                best, best_r = para, r
        return best, best_r

    # ---------------------------------------------------------------- anchoring
    def anchor_bounds(self, m: Match) -> tuple[etree._Element, etree._Element]:
        """The paragraph-level children before/after which the range markers go (wrappers kept intact)."""
        atoms = [a for a in m.para.atoms if a.text]
        if not atoms:
            raise ValueError("paragraph has no text to anchor on")
        first = next((a for a in atoms if a.end > m.start), atoms[0])
        last = next((a for a in reversed(atoms) if a.start < m.end), atoms[-1])
        return self._top_child(first.run, m.para.el), self._top_child(last.run, m.para.el)

    @staticmethod
    def _top_child(el: etree._Element, p: etree._Element) -> etree._Element:
        while el.getparent() is not None and el.getparent() is not p:
            el = el.getparent()
        return el


# ================================================================================ reports
@dataclass
class CommentReport:
    src: str
    out: str
    round: int
    anchored: list[str] = field(default_factory=list)
    unanchored: list[dict] = field(default_factory=list)       # {"id", "reason", "paragraph"}
    anchor_kind: dict[str, str] = field(default_factory=dict)  # id -> exact | normalised | prefix | fallback | reply
    new_comments: list[str] = field(default_factory=list)      # top-level comments written (REF)
    replies_added: list[str] = field(default_factory=list)     # follow-ups written as replies (REF)
    roots_found: list[str] = field(default_factory=list)
    roots_missing: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)           # already present in the source
    parts_preserved: list[str] = field(default_factory=list)   # zip members unchanged by hash
    parts_changed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unanchored and not self.roots_missing

    def summary(self) -> dict:
        return {"round": self.round, "anchored": len(self.anchored), "unanchored": len(self.unanchored),
                "new_comments": len(self.new_comments), "replies_added": len(self.replies_added),
                "roots_found": len(self.roots_found), "roots_missing": len(self.roots_missing),
                "skipped": len(self.skipped), "parts_preserved": len(self.parts_preserved),
                "parts_changed": self.parts_changed, "warnings": len(self.warnings), "ok": self.ok}

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


@dataclass
class TrackedChange:
    kind: str                      # ins | del | moveTo | moveFrom
    author: str
    date: str
    excerpt: str
    paragraph_index: int | None
    pre_existing: bool = False     # the same change was already in the delivered file


@dataclass
class ParagraphChange:
    kind: str                      # inserted | deleted | modified
    delivered_index: int | None
    returned_index: int | None
    before: str
    after: str
    tracked: bool                  # explained by a tracked change in the returned file


@dataclass
class AlteredComment:
    internal_id: str
    follow_up_round: int | None
    cid: str
    line_index: int
    before: str
    after: str


@dataclass
class AnchorIssue:
    kind: str                      # range_missing | anchor_moved | quote_missing | range_text_changed
    internal_id: str
    follow_up_round: int | None
    cid: str
    detail: str
    before: str = ""
    after: str = ""


@dataclass
class OwnerComment:
    cid: str
    author: str
    text: str
    nearest_ref: str | None
    paragraph_index: int | None
    reply_to_ref: str | None = None


@dataclass
class ReturnDiff:
    delivered: str
    returned: str
    tracked_changes: list[TrackedChange] = field(default_factory=list)
    paragraph_changes: list[ParagraphChange] = field(default_factory=list)
    missing_gco_comments: list[str] = field(default_factory=list)
    altered_gco_comments: list[AlteredComment] = field(default_factory=list)
    anchor_issues: list[AnchorIssue] = field(default_factory=list)
    owner_comments: list[OwnerComment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def silent_edits(self) -> list[ParagraphChange]:
        return [c for c in self.paragraph_changes if not c.tracked]

    @property
    def clean(self) -> bool:
        return not (self.silent_edits or self.missing_gco_comments or self.altered_gco_comments or self.anchor_issues)

    def summary(self) -> dict:
        return {"tracked_changes": len(self.tracked_changes),
                "tracked_insertions": sum(1 for t in self.tracked_changes if t.kind in ("ins", "moveTo")),
                "tracked_deletions": sum(1 for t in self.tracked_changes if t.kind in ("del", "moveFrom")),
                "paragraph_changes": len(self.paragraph_changes), "silent_edits": len(self.silent_edits),
                "missing_gco_comments": list(self.missing_gco_comments),
                "altered_gco_comments": [a.internal_id for a in self.altered_gco_comments],
                "anchor_issues": [(a.kind, a.internal_id) for a in self.anchor_issues],
                "owner_comments": len(self.owner_comments), "warnings": len(self.warnings), "clean": self.clean}

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


INTACT, MOVED_IDENTICAL, CHANGED, MISSING = "INTACT", "MOVED_IDENTICAL", "CHANGED", "MISSING"


@dataclass
class ClosedTextFinding:
    internal_id: str
    reader_no: str
    status: str                    # INTACT | MOVED_IDENTICAL | CHANGED | MISSING
    closed_in_round: int
    quote: str
    excerpt: str = ""              # the text found (CHANGED: the new text)
    paragraph_index: int | None = None
    anchored_paragraphs: list[int] = field(default_factory=list)
    location_hint: str | None = None
    ratio: float = 0.0
    detail: str = ""


# ================================================================================ atomic output
@contextlib.contextmanager
def atomic_output(path, *, stage: str = "write"):
    """Yield a temp path in the destination's folder; rename it over the destination only when the block
    completes. On any exception the destination is untouched, the temp file is removed, and
    ``<destination>.rejected.json`` beside it records the reason; the exception is re-raised."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    rejected = rejected_path(path)
    try:
        yield tmp
        if not tmp.exists():
            raise RuntimeError(f"{stage}: nothing was written to the temporary file")
        os.replace(tmp, path)
        with contextlib.suppress(FileNotFoundError):
            rejected.unlink()
    except Exception as exc:
        report = {"destination": str(path), "stage": stage, "reason": f"{type(exc).__name__}: {exc}",
                  "when": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
                  "traceback": traceback.format_exc().splitlines()[-12:]}
        with contextlib.suppress(Exception):
            rejected.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def rejected_path(path) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".rejected.json")


# ================================================================================ comment construction
def _rpr(size_pt: float, *, bold: bool = False, white: bool = False, rtl: bool = True) -> etree._Element:
    rpr = etree.Element(_RPR)
    fonts = etree.SubElement(rpr, w("rFonts"))
    for a in ("ascii", "hAnsi", "cs"):
        fonts.set(w(a), FONT)
    if bold:
        etree.SubElement(rpr, w("b"))
        etree.SubElement(rpr, w("bCs"))
    if white:
        etree.SubElement(rpr, w("color")).set(w("val"), "FFFFFF")
    half = str(int(round(size_pt * 2)))
    etree.SubElement(rpr, w("sz")).set(w("val"), half)
    etree.SubElement(rpr, w("szCs")).set(w("val"), half)
    if rtl:
        etree.SubElement(rpr, w("rtl"))
    return rpr


def _text_run(text: str, style: str) -> etree._Element:
    r = etree.Element(_R)
    if style == "ref":
        r.append(_rpr(2, white=True, rtl=False))
    elif style == "label":
        r.append(_rpr(10, bold=True))
    elif style == "bodybold":
        r.append(_rpr(10, bold=True))
    else:
        r.append(_rpr(10))
    t = etree.SubElement(r, _T)
    t.text = text
    if text != text.strip():
        t.set(f"{{{XMLNS}}}space", "preserve")
    return r


def _comment_paragraph(runs: list[tuple[str, str]], *, first: bool, rtl: bool) -> etree._Element:
    p = etree.Element(_P)
    ppr = etree.SubElement(p, _PPR)
    etree.SubElement(ppr, w("pStyle")).set(w("val"), "CommentText")
    if rtl:
        etree.SubElement(ppr, w("bidi"))
    if first:
        r = etree.SubElement(p, _R)
        rpr = etree.SubElement(r, _RPR)
        etree.SubElement(rpr, w("rStyle")).set(w("val"), "CommentReference")
        etree.SubElement(r, w("annotationRef"))
    for text, style in runs:
        p.append(_text_run(text, style))
    return p


def _gtext_paragraphs(value, prefix: str | None = None) -> list[list[tuple[str, str]]]:
    """Comment body paragraphs of a GText (bold labels kept) or plain value; ``prefix`` opens the first line."""
    segs = value.segments if isinstance(value, GText) else [Segment(plain_text(value), False)]
    paras: list[list[tuple[str, str]]] = [[]]
    for seg in segs:
        for k, ln in enumerate(seg.text.split("\n")):
            if k > 0:
                paras.append([])
            if ln:
                paras[-1].append((ln, "bodybold" if seg.bold else "body"))
    paras = [p for p in paras if p] or [[]]
    if prefix:
        paras[0].insert(0, (prefix, "body"))
    return paras


def root_comment_paragraphs(o: Observation) -> list[list[tuple[str, str]]]:
    """08.2 shape: label line, REF line, body."""
    return [[(f"الملاحظة #{o.reader_no}", "label")], [(f"REF: {o.internal_id}", "ref")]] + _gtext_paragraphs(o.comment)


def follow_up_paragraphs(o: Observation, r: int) -> list[list[tuple[str, str]]]:
    """08.3 shape: follow-up label, REF / Rn-FU line, "status: feedback" body."""
    status = o.value(r)
    fb = o.cells[r].feedback if r in o.cells else None
    return [[(f"متابعة الملاحظة #{o.reader_no} {S.EN_DASH} الجولة {S.ordinal(r)}", "label")],
            [(f"REF: {o.internal_id} / R{r}-FU", "ref")]] + _gtext_paragraphs(fb, prefix=f"{status}: ")


def _comment_element(cid: int, paragraphs: list[list[tuple[str, str]]], para_id: str) -> etree._Element:
    c = etree.Element(w("comment"))
    c.set(w("id"), str(cid))
    c.set(w("author"), GCO_AUTHOR)
    c.set(w("date"), _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"))
    c.set(w("initials"), GCO_INITIALS)
    for i, runs in enumerate(paragraphs):
        rtl = not (len(runs) == 1 and runs[0][1] == "ref")
        p = _comment_paragraph(runs, first=(i == 0), rtl=rtl)
        if i == 0:
            p.set(f"{{{W14NS}}}paraId", para_id)
            p.set(f"{{{W14NS}}}textId", para_id)
        c.append(p)
    return c


def _marker(tag: str, cid: int) -> etree._Element:
    el = etree.Element(tag)
    el.set(w("id"), str(cid))
    return el


def _reference_run(cid: int) -> etree._Element:
    r = etree.Element(_R)
    rpr = etree.SubElement(r, _RPR)
    etree.SubElement(rpr, w("rStyle")).set(w("val"), "CommentReference")
    etree.SubElement(r, _RREF).set(w("id"), str(cid))
    return r


def _with_namespaces(root: etree._Element, needed: dict[str, str]) -> etree._Element:
    """The same root with the given prefixes declared (lxml cannot add nsmap entries in place)."""
    if all(root.nsmap.get(p) == uri for p, uri in needed.items()):
        return root
    nsmap = dict(root.nsmap)
    for p, uri in needed.items():
        nsmap.setdefault(p, uri)
    new = etree.Element(root.tag, nsmap=nsmap)
    for k, v in root.attrib.items():
        new.set(k, v)
    new.text = root.text
    for child in list(root):
        new.append(child)
    return new


def _ignorable(root: etree._Element, prefixes: tuple[str, ...]) -> None:
    have = (root.get(f"{{{MCNS}}}Ignorable") or "").split()
    root.set(f"{{{MCNS}}}Ignorable", " ".join(have + [p for p in prefixes if p not in have]))


def _new_comments_root() -> etree._Element:
    root = etree.Element(w("comments"), nsmap={"w": WNS, "mc": MCNS, "w14": W14NS, "w15": W15NS})
    root.set(f"{{{MCNS}}}Ignorable", "w14 w15")
    return root


def _used_para_ids(*roots: etree._Element) -> set[str]:
    used = set()
    for root in roots:
        if root is None:
            continue
        for el in root.iter():
            pid = el.get(f"{{{W14NS}}}paraId")
            if pid:
                used.add(pid.upper())
    return used


class _ParaIds:
    def __init__(self, used: set[str]):
        self.used = set(used)
        self.n = 0

    def new(self) -> str:
        while True:
            self.n += 1
            pid = f"{0x1F000000 + self.n * 0x0101:08X}"
            if pid not in self.used:
                self.used.add(pid)
                return pid


def _serialise(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _register_part(parts: dict[str, bytes], part: str, ctype: str, rel_type: str) -> None:
    ct = etree.fromstring(parts[CT_PART])
    have = {o.get("PartName") for o in ct.findall(f"{{{CT_NS}}}Override")}
    if f"/{part}" not in have:
        etree.SubElement(ct, f"{{{CT_NS}}}Override", PartName=f"/{part}", ContentType=ctype)
        parts[CT_PART] = _serialise(ct)
    rels = etree.fromstring(parts[DOC_RELS])
    have_types = {r.get("Type") for r in rels.findall(f"{{{REL_NS}}}Relationship")}
    if rel_type not in have_types:
        nums = [int(r.get("Id")[3:]) for r in rels.findall(f"{{{REL_NS}}}Relationship")
                if re.fullmatch(r"rId\d+", r.get("Id") or "")]
        etree.SubElement(rels, f"{{{REL_NS}}}Relationship", Id=f"rId{max(nums, default=0) + 1}", Type=rel_type,
                         Target=part.split("/", 1)[1])
        parts[DOC_RELS] = _serialise(rels)


def _write_zip(parts: dict[str, bytes], infos: list[zipfile.ZipInfo], dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        written = set()
        for item in infos:
            zout.writestr(item, parts[item.filename])
            written.add(item.filename)
        for name, data in parts.items():
            if name not in written:
                zout.writestr(name, data)


def _hashes(path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {i.filename: hashlib.sha256(z.read(i.filename)).hexdigest() for i in z.infolist()}


def rows_for_round(state: ReviewState, R: int) -> tuple[list[Observation], list[Observation]]:
    """(rows needing a round-R follow-up, rows born in round R). Round 1: ([], every observation)."""
    if R <= 1:
        return [], [o for o in state.ordered() if o.birth_round <= 1]
    follow = [o for o in state.ordered() if o.birth_round < R and (o.value(R - 1) != S.CLOSED or o.value(R) != S.CLOSED)]
    born = [o for o in state.ordered() if o.birth_round == R]
    return follow, born


# ================================================================================ 1. comment_document
def comment_document(src_docx, state: ReviewState, out_docx, *, round_no: int | None = None,
                     prior_docx=None) -> CommentReport:
    """Anchor the GCO comments of ``state`` for round ``round_no`` onto the real document ``src_docx``.

    Round 1: a top-level comment per observation. Round n: a native reply under the existing root comment of
    every row not مغلقة at the start of the round or reopened in it (16.1), and a top-level comment for every
    row born in round n. A row whose round-n comment is already in ``src_docx`` is skipped (re-runs are safe).
    A follow-up whose root is missing from the document is written as a top-level comment and reported in
    ``roots_missing`` (``prior_docx``, the file GCO delivered last round, only sharpens the warning: it says
    whether the owner removed the root). Document text, other comments, tracked changes and every untouched
    part are preserved; the write is atomic and verified (see ``atomic_output``).
    """
    src = Path(src_docx)
    out = Path(out_docx)
    R = round_no or state.current_round
    rep = CommentReport(str(src), str(out), R)
    with atomic_output(out, stage=f"comment_document round {R}") as tmp:
        with zipfile.ZipFile(src) as z:
            infos = z.infolist()
            parts = {i.filename: z.read(i.filename) for i in infos}
        if DOC_PART not in parts or DOC_RELS not in parts or CT_PART not in parts:
            raise ValueError(f"{src.name} is not a Word package (document.xml / rels / content types missing)")
        doc_root = etree.fromstring(parts[DOC_PART])
        doc = DocText(doc_root)
        if COMMENTS_PART in parts:
            comments_root = _with_namespaces(etree.fromstring(parts[COMMENTS_PART]),
                                             {"w14": W14NS, "w15": W15NS, "mc": MCNS})
            _ignorable(comments_root, ("w14", "w15"))
        else:
            comments_root = _new_comments_root()
            _register_part(parts, COMMENTS_PART, COMMENTS_CT, COMMENTS_REL)
        existing = extract_comments(src)
        gco_existing = {(c.internal_id, c.follow_up_round): c for c in existing
                        if c.author == GCO_AUTHOR and c.internal_id}
        roots = {iid: c for (iid, fu), c in gco_existing.items() if fu is None}
        prior_roots: set[str] = set()
        if prior_docx is not None and Path(prior_docx).exists():
            prior_roots = {c.internal_id for c in extract_comments(prior_docx)
                           if c.author == GCO_AUTHOR and c.internal_id and c.follow_up_round is None}
        used_ids = [int(c.get(w("id"))) for c in comments_root.findall(w("comment")) if (c.get(w("id")) or "").isdigit()]
        used_ids += [int(x) for x in doc.ranges if x.isdigit()]
        next_id = max(used_ids, default=-1) + 1
        ex_root = (_with_namespaces(etree.fromstring(parts[COMMENTS_EX_PART]), {"mc": MCNS, "w15": W15NS})
                   if COMMENTS_EX_PART in parts
                   else etree.Element(f"{{{W15NS}}}commentsEx", nsmap={"mc": MCNS, "w15": W15NS}))
        _ignorable(ex_root, ("w15",))
        ids_root = (_with_namespaces(etree.fromstring(parts[COMMENTS_IDS_PART]), {"mc": MCNS, "w16cid": W16CIDNS})
                    if COMMENTS_IDS_PART in parts
                    else etree.Element(f"{{{W16CIDNS}}}commentsIds", nsmap={"mc": MCNS, "w16cid": W16CIDNS}))
        _ignorable(ids_root, ("w16cid",))
        pids = _ParaIds(_used_para_ids(comments_root, doc_root))
        comment_by_cid = {c.get(w("id")): c for c in comments_root.findall(w("comment"))}
        ex_by_pid = {(e.get(f"{{{W15NS}}}paraId") or "").upper(): e for e in ex_root.findall(f"{{{W15NS}}}commentEx")}
        durable_used = {(e.get(f"{{{W16CIDNS}}}durableId") or "").upper() for e in ids_root}
        ids_by_pid = {(e.get(f"{{{W16CIDNS}}}paraId") or "").upper() for e in ids_root}

        def para_id_of(cid: str) -> str:
            """w14:paraId of an existing comment's first paragraph, generated when missing (GCO comments only)."""
            c = comment_by_cid[cid]
            p = c.find(_P)
            if p is None:
                p = etree.SubElement(c, _P)
            pid = p.get(f"{{{W14NS}}}paraId")
            if not pid:
                pid = pids.new()
                p.set(f"{{{W14NS}}}paraId", pid)
                p.set(f"{{{W14NS}}}textId", pid)
            return pid.upper()

        def ensure_ex(pid: str, parent_pid: str | None, done: bool) -> None:
            e = ex_by_pid.get(pid)
            if e is None:
                e = etree.SubElement(ex_root, f"{{{W15NS}}}commentEx")
                e.set(f"{{{W15NS}}}paraId", pid)
                ex_by_pid[pid] = e
            if parent_pid:
                e.set(f"{{{W15NS}}}paraIdParent", parent_pid)
            e.set(f"{{{W15NS}}}done", "1" if done else "0")
            if pid not in ids_by_pid:
                k = len(ids_by_pid) + 1
                while f"{0x2E000000 + k * 0x0101:08X}" in durable_used:
                    k += 1
                d = etree.SubElement(ids_root, f"{{{W16CIDNS}}}commentId")
                d.set(f"{{{W16CIDNS}}}paraId", pid)
                d.set(f"{{{W16CIDNS}}}durableId", f"{0x2E000000 + k * 0x0101:08X}")
                ids_by_pid.add(pid)
                durable_used.add(f"{0x2E000000 + k * 0x0101:08X}")

        def place_new(o: Observation, paragraphs, label: str) -> tuple[int, str]:
            """Anchor a new comment on the quoted passage; returns (cid, paraId)."""
            nonlocal next_id
            cid = next_id
            next_id += 1
            quote = plain_text(o.quote)
            m = doc.locate(quote)
            if m is None:
                best, ratio = doc.best_paragraph(quote)
                if best is None:
                    raise ValueError(f"{o.internal_id}: the document body has no text to anchor on")
                m = Match(best, 0, len(best.text), "fallback", f"best-matching paragraph, {ratio:.2f} of the quote covered")
                rep.unanchored.append({"id": o.internal_id, "reason": f"quote not found; placed on paragraph "
                                       f"{best.index} ({m.detail}): «{_excerpt(best.text)}»", "paragraph": best.index})
            else:
                rep.anchored.append(o.internal_id)
                if m.kind == "prefix":
                    rep.warnings.append(f"{o.internal_id}: anchored by {m.detail} (paragraph {m.para.index})")
            rep.anchor_kind[o.internal_id] = m.kind
            first, last = doc.anchor_bounds(m)
            first.addprevious(_marker(_RS, cid))
            last.addnext(_reference_run(cid))
            last.addnext(_marker(_RE_, cid))
            pid = pids.new()
            el = _comment_element(cid, paragraphs, pid)
            comments_root.append(el)
            comment_by_cid[str(cid)] = el
            rep.new_comments.append(label)
            return cid, pid

        follow, born = rows_for_round(state, R)
        expected_keys: set[tuple[str, int | None]] = set()
        for o in born:
            key = (o.internal_id, None)
            expected_keys.add(key)
            if key in gco_existing:
                rep.skipped.append(o.internal_id)
                rep.warnings.append(f"{o.internal_id}: root comment already present (comment {gco_existing[key].cid}); kept")
                continue
            cid, pid = place_new(o, root_comment_paragraphs(o), o.internal_id)
            ensure_ex(pid, None, o.value(R) == S.CLOSED)
        for o in follow:
            key = (o.internal_id, R)
            expected_keys.add(key)
            label = f"{o.internal_id} / R{R}-FU"
            if key in gco_existing:
                rep.skipped.append(label)
                rep.warnings.append(f"{label}: round-{R} follow-up already present (comment {gco_existing[key].cid}); kept")
                continue
            root = roots.get(o.internal_id)
            rng = doc.ranges.get(root.cid) if root is not None else None
            done = o.value(R) == S.CLOSED
            if root is None or rng is None or not rng.complete:
                why = ("root comment absent from the document" if root is None else
                       f"root comment {root.cid} has no complete range in document.xml")
                if root is None and o.internal_id in prior_roots:
                    why += " although GCO delivered it last round (removed by the owner)"
                rep.roots_missing.append(o.internal_id)
                rep.warnings.append(f"{label}: {why}; follow-up written as a top-level comment on the quote")
                cid, pid = place_new(o, follow_up_paragraphs(o, R), label)
                ensure_ex(pid, None, done)
                continue
            rep.roots_found.append(o.internal_id)
            cid = next_id
            next_id += 1
            rng.start.addnext(_marker(_RS, cid))
            after = rng.ref_run if rng.ref_run is not None else rng.end
            after.addnext(_reference_run(cid))
            after.addnext(_marker(_RE_, cid))
            pid = pids.new()
            el = _comment_element(cid, follow_up_paragraphs(o, R), pid)
            comments_root.append(el)
            comment_by_cid[str(cid)] = el
            root_pid = para_id_of(root.cid)
            ensure_ex(root_pid, None, done)
            ensure_ex(pid, root_pid, done)
            rep.replies_added.append(label)
            rep.anchor_kind[label] = "reply"
        # keep every other comment that already carries a paraId in the thread parts (Word expects one entry each)
        for cid, c in comment_by_cid.items():
            p = c.find(_P)
            pid = (p.get(f"{{{W14NS}}}paraId") if p is not None else None)
            if pid and pid.upper() not in ex_by_pid:
                ensure_ex(pid.upper(), None, False)
        parts[DOC_PART] = _serialise(doc_root)
        parts[COMMENTS_PART] = _serialise(comments_root)
        parts[COMMENTS_EX_PART] = _serialise(ex_root)
        parts[COMMENTS_IDS_PART] = _serialise(ids_root)
        _register_part(parts, COMMENTS_EX_PART, COMMENTS_EX_CT, COMMENTS_EX_REL)
        _register_part(parts, COMMENTS_IDS_PART, COMMENTS_IDS_CT, COMMENTS_IDS_REL)
        _write_zip(parts, infos, tmp)
        baseline = package_structure_problems(src)
        rep.warnings.extend(f"source already had: {p}" for p in baseline)
        _verify_written(tmp, expected_keys, baseline)
        before, after = _hashes(src), _hashes(tmp)
        rep.parts_preserved = sorted(n for n in before if after.get(n) == before[n])
        rep.parts_changed = sorted(n for n in after if before.get(n) != after[n])
        unexpected = [n for n in rep.parts_changed if n not in TOUCHED_PARTS]
        if unexpected:
            raise RuntimeError(f"parts changed outside the comment set: {unexpected}")
    return rep


def _verify_written(path: Path, expected: set[tuple[str, int | None]], baseline: list[str]) -> None:
    """Reopen the temp file with python-docx and lxml: every expected REF present once, every range closed,
    every thread parent resolving. Structural defects already in the source (``baseline``) are not GCO's;
    any other defect raises, and the destination is then never written."""
    from docx import Document
    Document(str(path))                                    # the package loads
    comments = extract_comments(path)
    gco = [(c.internal_id, c.follow_up_round) for c in comments if c.author == GCO_AUTHOR and c.internal_id]
    missing = sorted(f"{i}{f' / R{f}-FU' if f else ''}" for i, f in expected if (i, f) not in gco)
    if missing:
        raise RuntimeError(f"verification: REF missing after write: {missing}")
    dup = sorted({f"{i}{f' / R{f}-FU' if f else ''}" for i, f in gco if gco.count((i, f)) > 1})
    if dup:
        raise RuntimeError(f"verification: duplicate REF after write: {dup}")
    problems = [p for p in package_structure_problems(path) if p not in baseline]
    if problems:
        raise RuntimeError("verification: " + "; ".join(problems))


# ================================================================================ 2. diff_returned
def _tracked_changes(doc: DocText) -> list[TrackedChange]:
    out = []
    for el in doc.body.iter(_INS, _DEL, _MOVETO, _MOVEFROM):
        parent = el.getparent()
        if parent is not None and parent.tag in (_RPR, _PPR, w("trPr"), w("tcPr"), w("tblPr"), w("sectPr")):
            continue                                        # property-level revision records, no text
        kind = etree.QName(el).localname
        text = "".join(t.text or "" for t in el.iter(_T if kind in ("ins", "moveTo") else w("delText")))
        out.append(TrackedChange(kind, el.get(w("author"), ""), el.get(w("date"), ""), _excerpt(text),
                                 doc.para_index_of(el)))
    return out


def _load_doc(path) -> tuple[DocText, dict[str, bytes]]:
    with zipfile.ZipFile(path) as z:
        parts = {i.filename: z.read(i.filename) for i in z.infolist()}
    return DocText(etree.fromstring(parts[DOC_PART])), parts


def _ref_label(iid: str, fu: int | None) -> str:
    return f"{iid} / R{fu}-FU" if fu else iid


def diff_returned(delivered_docx, returned_docx, state: ReviewState | None = None) -> ReturnDiff:
    """Compare the owner's returned document with the one GCO delivered.

    (a) tracked changes in the returned file; (b) accepted-view paragraph differences (difflib on normalised
    paragraph texts) — those not explained by a tracked change in the returned paragraph are ``silent_edits``;
    (c) GCO comments missing by REF, GCO comment text altered line by line, anchors moved: the comment range
    no longer encloses the quoted text (``state`` given) or its text changed (no ``state``), or the quoted
    passage is nowhere in the document; (d) non-GCO comments the owner added, with the nearest REF.
    Limitation: a range that still encloses the quote but was dragged by the owner to another identical
    occurrence is indistinguishable from an intact anchor; Word records no range history.
    """
    diff = ReturnDiff(str(delivered_docx), str(returned_docx))
    d_doc, _ = _load_doc(delivered_docx)
    r_doc, _ = _load_doc(returned_docx)
    # (a) tracked changes
    d_tc = {(t.kind, t.author, t.excerpt) for t in _tracked_changes(d_doc)}
    for t in _tracked_changes(r_doc):
        t.pre_existing = (t.kind, t.author, t.excerpt) in d_tc
        diff.tracked_changes.append(t)
    # (b) paragraph diff on normalised non-empty paragraphs
    dp = [p for p in d_doc.paras if p.ntext]
    rp = [p for p in r_doc.paras if p.ntext]
    del_texts = [_nkey("".join(t.text or "" for t in el.iter(w("delText")))) for el in r_doc.body.iter(_DEL, _MOVEFROM)]
    sm = difflib.SequenceMatcher(None, [p.ntext for p in dp], [p.ntext for p in rp], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        a, b = dp[i1:i2], rp[j1:j2]
        for k in range(max(len(a), len(b))):
            pa = a[k] if k < len(a) else None
            pb = b[k] if k < len(b) else None
            if pa is not None and pb is not None:
                diff.paragraph_changes.append(ParagraphChange("modified", pa.index, pb.index, _excerpt(pa.text, 120),
                                                              _excerpt(pb.text, 120), pb.has_tracked_change))
            elif pb is not None:
                diff.paragraph_changes.append(ParagraphChange("inserted", None, pb.index, "", _excerpt(pb.text, 120),
                                                              pb.has_tracked_change))
            else:
                covered = any(pa.ntext and pa.ntext in d for d in del_texts)
                diff.paragraph_changes.append(ParagraphChange("deleted", pa.index, None, _excerpt(pa.text, 120), "",
                                                              covered))
    # (c) GCO comments
    d_comments = extract_comments(delivered_docx)
    r_comments = extract_comments(returned_docx)
    d_gco = {(c.internal_id, c.follow_up_round): c for c in d_comments if c.author == GCO_AUTHOR and c.internal_id}
    r_gco = {(c.internal_id, c.follow_up_round): c for c in r_comments if c.author == GCO_AUTHOR and c.internal_id}
    by_id = state.by_id() if state is not None else {}
    for key in d_gco:
        if key not in r_gco:
            diff.missing_gco_comments.append(_ref_label(*key))
    for key, rc in r_gco.items():
        dc = d_gco.get(key)
        if dc is not None:
            a = [S.nfc(x).strip() for x in dc.lines]
            b = [S.nfc(x).strip() for x in rc.lines]
            if a != b:
                k = next((i for i in range(max(len(a), len(b))) if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)), 0)
                diff.altered_gco_comments.append(AlteredComment(key[0], key[1], rc.cid, k, a[k] if k < len(a) else "",
                                                                b[k] if k < len(b) else ""))
        rng = r_doc.ranges.get(rc.cid)
        if rng is None or not rng.complete:
            diff.anchor_issues.append(AnchorIssue("range_missing", key[0], key[1], rc.cid,
                                                  "comment has no complete range in document.xml"))
            continue
        o = by_id.get(key[0])
        if o is not None:
            quote = plain_text(o.quote)
            inside = _passage_in_text(quote, rng.text)
            if not inside:
                elsewhere = r_doc.locate(quote, allow_prefix=False)
                if elsewhere is not None:
                    diff.anchor_issues.append(AnchorIssue("anchor_moved", key[0], key[1], rc.cid,
                                                          f"quote now in paragraph {elsewhere.para.index}, outside the comment range",
                                                          _excerpt(rng.text), _excerpt(elsewhere.para.text)))
                else:
                    diff.anchor_issues.append(AnchorIssue("quote_missing", key[0], key[1], rc.cid,
                                                          "quoted passage no longer found in the document",
                                                          _excerpt(quote), _excerpt(rng.text)))
        elif dc is not None:
            drng = d_doc.ranges.get(dc.cid)
            if drng is not None and drng.complete and _nkey(drng.text) != _nkey(rng.text):
                diff.anchor_issues.append(AnchorIssue("range_text_changed", key[0], key[1], rc.cid,
                                                      "text under the comment range differs from the delivered file",
                                                      _excerpt(drng.text), _excerpt(rng.text)))
    # (d) comments the owner added
    d_keys = {(c.author, tuple(S.nfc(x).strip() for x in c.lines)) for c in d_comments}
    r_by_cid = {c.cid: c for c in r_comments}
    root_paras = {}
    for (iid, fu), c in r_gco.items():
        rng = r_doc.ranges.get(c.cid)
        if fu is None and rng is not None and rng.para_indices:
            root_paras[iid] = rng.para_indices[0]
    for c in r_comments:
        if c.author == GCO_AUTHOR and c.internal_id:
            continue
        if (c.author, tuple(S.nfc(x).strip() for x in c.lines)) in d_keys:
            continue
        rng = r_doc.ranges.get(c.cid)
        pi = None
        if rng is not None:
            if rng.start is not None:
                pi = r_doc.para_index_of(rng.start)
            elif rng.ref_run is not None:
                pi = r_doc.para_index_of(rng.ref_run)
        reply_to = None
        if c.parent_cid and c.parent_cid in r_by_cid and r_by_cid[c.parent_cid].internal_id:
            reply_to = r_by_cid[c.parent_cid].internal_id
        nearest = reply_to
        if nearest is None and pi is not None and root_paras:
            nearest = min(root_paras, key=lambda i: (abs(root_paras[i] - pi), root_paras[i]))
        diff.owner_comments.append(OwnerComment(c.cid, c.author, "\n".join(c.lines).strip(), nearest, pi, reply_to))
    return diff


def _passage_in_text(quote: str, text: str) -> bool:
    parts = _quote_parts(quote)
    if not parts:
        return False
    hay = _nkey(text)
    pos = 0
    for p in parts:
        k = hay.find(_nkey(p), pos)
        if k < 0:
            return False
        pos = k + len(_nkey(p))
    return True


# ================================================================================ 3. closed_text_integrity
def _location_hint(o: Observation, upto: int) -> str | None:
    """The latest 'تغيّر موضع الملاحظة إلى …' line in the GCO feedback of rounds ≤ upto."""
    for r in range(upto, o.birth_round, -1):
        cells = o.cells.get(r)
        if cells is None:
            continue
        for ln in plain_text(cells.feedback).split("\n"):
            m = MOVED_LINE_RE.search(ln)
            if m:
                return m.group("where").strip()
    return None


def _closure_round(o: Observation, upto: int) -> int:
    r = upto
    while r - 1 >= o.birth_round and o.value(r - 1) == S.CLOSED:
        r -= 1
    return r


def closed_text_integrity(state: ReviewState, returned_docx, round_no: int) -> list[ClosedTextFinding]:
    """For every row مغلقة in round ``round_no - 1``: is its passage still as it was closed (16.1)?

    INTACT: the quote is found under (or in the paragraph of) the row's root comment range, or anywhere when
    the document carries no GCO anchor to compare with. MOVED_IDENTICAL: found verbatim, but not in the
    anchored paragraph. CHANGED: not found verbatim; the anchored paragraph (else the best paragraph) still
    covers at least half of the quote, reported with the new text. MISSING: none of the above. A recorded
    move line in the feedback (page/article) is carried as ``location_hint``; it names a place, not text, so
    the passage is still located by its quote. The state is never modified.
    """
    prev = round_no - 1
    doc, _ = _load_doc(returned_docx)
    roots = {c.internal_id: c for c in extract_comments(returned_docx)
             if c.author == GCO_AUTHOR and c.internal_id and c.follow_up_round is None}
    out: list[ClosedTextFinding] = []
    for o in state.ordered():
        if o.value(prev) != S.CLOSED:
            continue
        quote = plain_text(o.quote)
        f = ClosedTextFinding(o.internal_id, o.reader_no, MISSING, _closure_round(o, prev), quote,
                              location_hint=_location_hint(o, prev))
        root = roots.get(o.internal_id)
        rng = doc.ranges.get(root.cid) if root is not None else None
        anchored = [doc.paras[i] for i in rng.para_indices] if rng is not None else []
        f.anchored_paragraphs = [p.index for p in anchored]
        m = doc.locate(quote, anchored, allow_prefix=False) if anchored else None
        if m is not None:
            f.status, f.excerpt, f.paragraph_index = INTACT, _excerpt(m.text, 120), m.para.index
            f.ratio, f.detail = 1.0, f"found in the anchored paragraph ({m.kind} match)"
        else:
            m = doc.locate(quote, allow_prefix=False)
            if m is not None:
                f.paragraph_index, f.excerpt, f.ratio = m.para.index, _excerpt(m.text, 120), 1.0
                if anchored:
                    f.status = MOVED_IDENTICAL
                    f.detail = f"found verbatim in paragraph {m.para.index}, outside the anchored paragraph(s) {f.anchored_paragraphs}"
                    if f.location_hint:
                        f.detail += f"; a move was recorded in the feedback ({f.location_hint})"
                else:
                    f.status, f.detail = INTACT, f"found verbatim ({m.kind}); no GCO anchor in the document to compare with"
            else:
                cand, ratio = doc.best_paragraph(quote, anchored or None)
                if cand is None or ratio < 0.5:
                    cand2, ratio2 = doc.best_paragraph(quote)
                    if cand2 is not None and ratio2 > ratio:
                        cand, ratio = cand2, ratio2
                f.ratio = round(ratio, 3)
                if cand is not None and ratio >= 0.5:
                    f.status, f.excerpt, f.paragraph_index = CHANGED, _excerpt(cand.text, 120), cand.index
                    f.detail = f"{ratio:.0%} of the quote still present in paragraph {cand.index}"
                else:
                    f.status, f.detail = MISSING, "quoted passage not found; no paragraph covers half of it"
        out.append(f)
    return out


# ================================================================================ 4. check_package
def package_structure_problems(docx) -> list[str]:
    """Structural problems of the comment parts of a .docx (no workbook needed)."""
    problems: list[str] = []
    with zipfile.ZipFile(docx) as z:
        names = set(z.namelist())
        parts = {n: z.read(n) for n in (DOC_PART, DOC_RELS, CT_PART, COMMENTS_PART, COMMENTS_EX_PART, COMMENTS_IDS_PART)
                 if n in names}
    if DOC_PART not in parts:
        return ["word/document.xml missing"]
    rels = etree.fromstring(parts[DOC_RELS]) if DOC_RELS in parts else None
    rel_targets = {}
    if rels is not None:
        for r in rels.findall(f"{{{REL_NS}}}Relationship"):
            rel_targets[r.get("Type")] = r.get("Target")
    doc_root = etree.fromstring(parts[DOC_PART])
    starts = [e.get(w("id")) for e in doc_root.iter(_RS)]
    ends = [e.get(w("id")) for e in doc_root.iter(_RE_)]
    refs = [e.get(w("id")) for e in doc_root.iter(_RREF)]
    referenced = set(starts) | set(ends) | set(refs)
    if COMMENTS_REL in rel_targets:
        target = "word/" + rel_targets[COMMENTS_REL].lstrip("/").removeprefix("word/")
        if target not in names:
            problems.append(f"document.xml.rels points to comments part {target} which is missing from the package")
    elif referenced:
        problems.append("document.xml references comments but document.xml.rels has no comments relationship")
    if COMMENTS_PART in parts:
        if COMMENTS_REL not in rel_targets:
            problems.append("word/comments.xml present but not related from document.xml")
        ct = etree.fromstring(parts[CT_PART]) if CT_PART in parts else None
        if ct is not None and not any(o.get("PartName") == f"/{COMMENTS_PART}" for o in ct.findall(f"{{{CT_NS}}}Override")):
            problems.append("[Content_Types].xml has no override for /word/comments.xml")
        croot = etree.fromstring(parts[COMMENTS_PART])
        cids = [c.get(w("id")) for c in croot.findall(w("comment"))]
        if len(cids) != len(set(cids)):
            problems.append(f"duplicate comment ids in comments.xml: {sorted({c for c in cids if cids.count(c) > 1})}")
        cid_set = set(cids)
        for cid in sorted(referenced - cid_set, key=lambda x: (len(x), x)):
            problems.append(f"document.xml references comment id {cid} that is not in comments.xml")
        for cid in sorted(cid_set - set(refs), key=lambda x: (len(x), x)):
            problems.append(f"comment {cid} has no w:commentReference in document.xml")
        for cid in sorted(set(starts) ^ set(ends), key=lambda x: (len(x), x)):
            problems.append(f"comment {cid}: commentRangeStart/End unpaired in document.xml")
        for cid in sorted(set(refs) - set(starts), key=lambda x: (len(x), x)):
            if cid in cid_set:
                problems.append(f"comment {cid} is referenced without a comment range")
        if COMMENTS_EX_PART in parts:
            pids = {(c.find(_P).get(f"{{{W14NS}}}paraId") or "").upper() for c in croot.findall(w("comment")) if c.find(_P) is not None}
            pids.discard("")
            ex = etree.fromstring(parts[COMMENTS_EX_PART])
            for e in ex.findall(f"{{{W15NS}}}commentEx"):
                pid = (e.get(f"{{{W15NS}}}paraId") or "").upper()
                parent = (e.get(f"{{{W15NS}}}paraIdParent") or "").upper()
                if pid not in pids:
                    problems.append(f"commentsExtended entry {pid} matches no comment paragraph")
                if parent and parent not in pids:
                    problems.append(f"commentsExtended parent {parent} (of {pid}) does not resolve to a comment")
    elif referenced:
        problems.append("document.xml references comments but word/comments.xml is missing")
    return problems


def check_package(docx, xlsx, state: ReviewState) -> list[str]:
    """Blocking problems of a Word + Excel package; an empty list means clean.

    Duplicate Internal_IDs across comments (same REF and follow-up round twice), REF in Word without a workbook
    row and workbook rows without their Word comment (``word_sync.reconcile``), REFs unknown to ``state``,
    broken comment relationships, unresolved thread parents, a comments part referenced but missing.
    """
    from .word_sync import reconcile
    problems: list[str] = []
    try:
        comments = extract_comments(docx)
    except Exception as exc:  # noqa: BLE001
        return [f"cannot read comments of {Path(docx).name}: {type(exc).__name__}: {exc}"]
    gco = [c for c in comments if c.author == GCO_AUTHOR and c.internal_id]
    keys = [(c.internal_id, c.follow_up_round) for c in gco]
    for key in sorted({k for k in keys if keys.count(k) > 1}):
        cids = [c.cid for c in gco if (c.internal_id, c.follow_up_round) == key]
        problems.append(f"duplicate REF {_ref_label(*key)} in comments {cids}")
    known = state.by_id()
    for c in gco:
        if c.internal_id not in known:
            problems.append(f"comment {c.cid}: REF {c.internal_id} is not an observation of the review state")
    try:
        rep = reconcile(docx, xlsx)
        problems.extend(f"reconcile: {p}" for p in rep.problems)
        failed = [k for k, v in rep.checks.items() if not v]
        if failed:
            problems.append(f"reconcile checks failed: {failed}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"reconcile failed: {type(exc).__name__}: {exc}")
    problems.extend(package_structure_problems(docx))
    return problems
