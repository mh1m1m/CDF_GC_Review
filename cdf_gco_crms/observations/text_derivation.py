"""Mechanical extracts of GCO text for the dashboard (10.4A.9).

Nothing here rewrites, paraphrases or summarises with a model: a summary is the
first sentence of column E, an action is the text after a fixed label of the
GCO feedback, a current location is the latest location line of 08.3. The full
text stays in the data sheet.
"""
from __future__ import annotations

import re

from ..config import round_schema as S
from ..config.workbook_settings import ACTION_MAX, SUMMARY_MAX

LABELS = ("التوصية:", "النص المقترح:", "المطلوب:", "شرط الإغلاق:")
_SENT_SPLIT = re.compile(r"(?<=[.؟?!])\s+|\n+")
_LOCATION_LINE = re.compile(r"^الجولة\s+(?P<ord>\S+):\s*تغيّر موضع الملاحظة إلى\s+(?P<loc>.+?)\s*\.?\s*$")


def cut(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[:limit]
    sp = head.rfind(" ")
    if sp > limit * 0.5:
        head = head[:sp]
    return head.rstrip("،؛:,; ") + "…"


def _strip_labels(s: str) -> str:
    s = s.strip()
    changed = True
    while changed:
        changed = False
        for lab in LABELS:
            if s.startswith(lab):
                s = s[len(lab):].strip()
                changed = True
    return s


def summary(comment_text: str, limit: int = SUMMARY_MAX) -> str:
    for part in _SENT_SPLIT.split(comment_text or ""):
        p = _strip_labels(part)
        if p:
            return cut(p, limit)
    return ""


def display_title(title: str | None, title_status: str, reader_no) -> str:
    """Title shown on the dashboard (10.4A.16).

    An APPROVED/ISSUED title is shown as recorded. Anything else falls back to
    the neutral label "الملاحظة #NN" (reader number): no engine extract of the
    observation text is ever shown where a GCO-approved title belongs.
    """
    if title_status in S.TITLE_SHOWN_STATES and title and title.strip():
        return " ".join(title.split())
    return S.title_fallback(reader_no)


ACTION_OPENERS = ("نوصي", "نأمل", "نرجو", "نقترح", "نؤكد", "يُستبدل", "يُحذف", "تُضاف", "إحلال", "إضافة",
                  "حذف", "تحديد", "قصر", "تقييد", "اشتراط", "ربط", "استكمال", "تعديل")
_CLAUSE_SPLIT = re.compile(r"(?<=[.؟?!؛])\s+|\n+|؛\s*")


def _after_label(text: str, label: str) -> str | None:
    idx = text.find(label)
    if idx < 0:
        return None
    rest = text[idx + len(label):].strip()
    if not rest:
        return None
    if label != "التوصية:":
        return rest.split("\n")[0].strip()
    head = rest.split("النص المقترح:")[0]
    parts = [p.strip() for p in _CLAUSE_SPLIT.split(head) if p and p.strip()]
    for p in parts:                     # 08.3A: the history sentence may precede the action
        if p.startswith(ACTION_OPENERS):
            return p
    return parts[0] if parts else None


def required_action(value: str, feedback_text: str, r: int, birth: int, limit: int = ACTION_MAX) -> str:
    if value == "":
        return ""
    if value == S.CLOSED:
        return S.ACTION_NONE
    if r == birth:
        return S.ACTION_FIRST
    fb = feedback_text or ""
    got = _after_label(fb, "المطلوب:")
    if got:
        return cut(got, limit)
    got = _after_label(fb, "شرط الإغلاق:")
    if got:
        return cut("استيفاء شرط الإغلاق: " + got, limit)
    got = _after_label(fb, "التوصية:")
    if got:
        return cut(got, limit)
    return S.ACTION_GENERIC


def location_line(feedback_text: str) -> str | None:
    for line in (feedback_text or "").split("\n"):
        m = _LOCATION_LINE.match(line.strip())
        if m:
            return m.group("loc").strip()
    return None


def current_location(original: str, feedbacks: dict[int, str], birth: int, r: int) -> str:
    """Latest location line (08.3) up to round r, else the issued location (column C)."""
    for k in range(r, birth, -1):
        loc = location_line(feedbacks.get(k, ""))
        if loc:
            return loc
    return original
