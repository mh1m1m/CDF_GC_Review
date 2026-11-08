"""The shape of a new comment under protocol v7.15, and the checks that enforce it.

This module holds the composer and the per-comment checks that chat kit 1.1.6 kept in ``cdfkit.py``, with the parts
the kit still applied in their v7.14 form brought to v7.15:

* 07.4A(a): every new comment carries one reason sentence, a recommendation and a proposed text;
* 07.4A(b): a gap opens "نوصي بـ"; an improvement (Observation_Type IMPROVEMENT, severity LOW) opens "نقترح";
* 07.4A(d) and R3(d): a new comment asks no question; a matter that rests on an unseen document becomes a
  recommendation made conditional on that document not already covering it ("ما لم تتضمنه ...");
* G-SUB-12: Depends_On_Unseen is met by that conditional form (F6 only for reviews under a version before v7.15);
* 07.2 and R3(c): reason <= 35, action <= 30, proposed text <= 60, whole <= 100 with a proposed text, else <= 70;
* 08.2A: the expected closing action, one line of at most 30 words, in the round of birth;
* 08.2B: an improvement opens with the bold label "ملاحظة تحسينية:", not counted in the ceilings;
* P14 (v7.15): flags a new comment with more than one reason sentence or a part above its 07.2 ceiling.

Historical comments (a review under a version before v7.15) keep their own shape: the 00.2 carve-out applies
07.4A to new comments only, so :func:`check_comment` with ``protocol`` below 7.15 runs only the earlier checks.

Inputs are register fields as a dict: ``analysis`` (Analysis_Text, the reason), ``recommendation``,
``proposed_wording``, ``closure_action``, ``observation_type``, ``severity``, ``form`` (F1–F7) and
``depends_on_unseen``. Problems are returned as strings prefixed with the rule, never raised.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from ..model.entities import GText, Segment, plain_text

CLOSURE_LABEL = "الإجراء المتوقع للإغلاق:"
IMPROVEMENT_LABEL = "ملاحظة تحسينية:"
ACTION_LABEL = "التوصية:"
PROPOSED_LABEL = "النص المقترح:"
F7_CONNECTOR = "، بالنص الآتي: "

GAP_OPENER = "نوصي ب"            # "نوصي بـ" with or without the tatweel
IMPROVEMENT_OPENER = "نقترح"
CONDITIONAL_MARKERS = ("ما لم تتضمن", "ما لم يتضمن", "ما لم ينص", "ما لم تنص")
QUESTION_OPENERS = ("هل ", "ما هو ", "ما هي ", "متى ", "كيف ", "لماذا ")

_DIAC = re.compile("[ً-ْٰـ]")
_WORD = re.compile(r"[0-9A-Za-zء-غف-ي٠-٩ٱ-ۓۺ-ۿ]+")
_SENTENCE_END = re.compile(r"[.؟!](\s|$)")


@dataclass(frozen=True)
class Ceilings:
    """07.2 ceilings in Arabic words (07.7)."""
    reason: int = 35
    action: int = 30
    proposed: int = 60
    whole_with_proposed: int = 100
    whole: int = 70
    closing: int = 30
    f7_headline: int = 15
    bullets: int = 4


CEILINGS = Ceilings()


def words(text: str | None) -> int:
    """07.7: words after removing diacritics and tatweel."""
    return len(_WORD.findall(_DIAC.sub("", text or "")))


def _norm(text: str | None) -> str:
    return _DIAC.sub("", " ".join((text or "").split()))


def _sentences(text: str) -> int:
    t = (text or "").strip()
    if not t:
        return 0
    return max(1, len(_SENTENCE_END.findall(t + " ")))


def _version(protocol) -> tuple[int, int]:
    major, _, minor = str(protocol).partition(".")
    return int(major), int(minor or 0)


def is_improvement(o: dict) -> bool:
    return (o.get("observation_type") or "").upper() == "IMPROVEMENT"


# ------------------------------------------------------------------------------------------------ composer
def _lines(text: str):
    segs = []
    for k, line in enumerate((text or "").split("\n")):
        if k:
            segs.append(Segment("\n"))
        if line:
            segs.append(Segment(line))
    return segs


def compose_comment(o: dict) -> GText:
    """The comment body from the register fields, in the order of 07.4A and 08.2A/08.2B: improvement label, reason,
    "التوصية:" and the recommendation, "النص المقترح:" and the text in quotation marks, then the expected closing
    action. F7 keeps its inline clause (07.4); F6 (reviews before v7.15 only) carries no label."""
    form = (o.get("form") or "").upper()
    analysis = (o.get("analysis") or "").strip()
    rec = (o.get("recommendation") or "").strip()
    wording = (o.get("proposed_wording") or "").strip()
    segs: list[Segment] = []
    if is_improvement(o):
        segs += [Segment(IMPROVEMENT_LABEL, True), Segment(" ")]
    if analysis:
        segs += _lines(analysis)
    if form == "F6":
        body = _lines(rec)
    elif form == "F7":
        body = [Segment(ACTION_LABEL, True), Segment(" " + rec.rstrip("،:. ") + F7_CONNECTOR + "("),
                Segment('"' + wording.strip('"“” ').rstrip(".") + '".', True), Segment(")")]
        wording = ""
    else:
        label = o.get("label")
        if label is None:
            label = bool(analysis) or form == "F5"
        body = ([Segment(ACTION_LABEL, True), Segment(" ")] if label else []) + _lines(rec)
    if segs and body:
        segs.append(Segment("\n"))
    segs += body
    if wording and form not in ("F5", "F7"):
        segs += [Segment("\n"), Segment(PROPOSED_LABEL, True), Segment(" "),
                 Segment('"' + wording.strip('"“” ').rstrip(".") + '"', True)]
    closing = (o.get("closure_action") or "").strip()
    if closing:
        segs += [Segment("\n"), Segment(CLOSURE_LABEL, True), Segment(" " + closing)]
    return GText([s for s in segs if s.text])


# ------------------------------------------------------------------------------------------------ checks
def _ceiling_problems(o: dict, c: Ceilings = CEILINGS) -> list[str]:
    form = (o.get("form") or "").upper()
    a, r, wd = words(o.get("analysis")), words(o.get("recommendation")), words(o.get("proposed_wording"))
    p = []
    if a > c.reason:
        p.append(f"07.2 reason {a} words > {c.reason}")
    if form == "F7":
        if r > c.f7_headline:
            p.append(f"07.4 F7 headline {r} words > {c.f7_headline}")
    elif r > c.action:
        p.append(f"07.2 action {r} words > {c.action}")
    if wd > c.proposed:
        p.append(f"07.2 proposed text {wd} words > {c.proposed}")
    whole = a + r + wd                                # labels, 08.2B label and the 08.2A line are not counted
    limit = c.whole_with_proposed if wd or form == "F7" else c.whole
    if whole > limit:
        p.append(f"07.2 whole comment {whole} words > {limit}")
    bullets = [ln for ln in (o.get("recommendation") or "").split("\n") if ln.strip().startswith("•")]
    if len(bullets) > c.bullets:
        p.append(f"07.2 {len(bullets)} bullets > {c.bullets}")
    return p


def _asks_question(text: str) -> bool:
    t = _norm(text)
    return "؟" in t or "?" in t or any(t.startswith(q) for q in QUESTION_OPENERS)


def _conditional(text: str) -> bool:
    t = _norm(text)
    return any(m in t for m in CONDITIONAL_MARKERS)


def check_comment(o: dict, *, protocol: str = "7.15", round_of_birth: bool = True,
                  ceilings: Ceilings = CEILINGS) -> list[str]:
    """Problems of one observation's comment under ``protocol``. An empty list means the shape is met."""
    p = _ceiling_problems(o, ceilings)
    reason = (o.get("analysis") or "").strip()
    rec = (o.get("recommendation") or "").strip()
    if _sentences(reason) > 1:
        p.append("07.1 reason is more than one sentence")
    if not rec:
        p.append("07.1 recommendation empty")
    if _version(protocol) < (7, 15):
        if o.get("depends_on_unseen") and (o.get("form") or "").upper() != "F6":
            p.append("G-SUB-12 depends_on_unseen set: an F6 question under a version before v7.15")
        return p
    # 07.4A (new comments; 00.2 carve-out)
    if not reason:
        p.append("07.4A(a) reason sentence missing")
    if not (o.get("proposed_wording") or "").strip():
        p.append("07.4A(a) proposed text missing")
    opener = _norm(rec)
    if is_improvement(o):
        if not opener.startswith(IMPROVEMENT_OPENER):
            p.append("07.4A(b) an improvement opens with \"نقترح\"")
        if (o.get("severity") or "LOW").upper() != "LOW":
            p.append("07.4A(b) an improvement carries severity LOW")
    elif not opener.startswith(GAP_OPENER):
        p.append("07.4A(b) a gap opens with \"نوصي بـ\"")
    if (o.get("form") or "").upper() == "F6" or _asks_question(rec) or _asks_question(reason):
        p.append("07.4A(d) a new comment asks no question: turn it into a recommendation")
    if o.get("depends_on_unseen") and not _conditional(rec):
        p.append("G-SUB-12 depends_on_unseen set: make the recommendation conditional (\"ما لم تتضمنه ...\")")
    closing = (o.get("closure_action") or "").strip()
    if round_of_birth and not closing:
        p.append("08.2A expected closing action missing")
    elif words(closing) > ceilings.closing:
        p.append(f"08.2A closing action {words(closing)} words > {ceilings.closing}")
    if is_improvement(o) and not plain_text(compose_comment(o)).startswith(IMPROVEMENT_LABEL):
        p.append("08.2B improvement label missing")
    return p


def r3_shape_ok(o: dict, *, protocol: str = "7.15") -> bool:
    """R3(c) and (d) of 20.3 under v7.15: each part and the whole within 07.2, and no question."""
    if _ceiling_problems(o):
        return False
    if _version(protocol) >= (7, 15):
        return not ((o.get("form") or "").upper() == "F6" or _asks_question(o.get("recommendation") or ""))
    return True


def p14_findings(observations: list[dict], *, protocol: str = "7.15") -> dict:
    """P14 of 19. v7.15: the new comments with more than one reason sentence or a part above its ceiling.
    Before v7.15: reason sentences in more than 50 % of comments, or a median whole length above 40 words."""
    if _version(protocol) >= (7, 15):
        flagged = [o.get("id") or i + 1 for i, o in enumerate(observations)
                   if _sentences(o.get("analysis") or "") > 1 or _ceiling_problems(o)]
        return {"check": "P14", "flagged": flagged, "ok": not flagged}
    n = max(1, len(observations))
    reasons = sum(1 for o in observations if (o.get("analysis") or "").strip())
    lengths = [words(plain_text(compose_comment(o))) for o in observations] or [0]
    med = statistics.median(lengths)
    return {"check": "P14", "reasons": reasons, "median": med, "ok": reasons / n <= 0.5 and med <= 40}
