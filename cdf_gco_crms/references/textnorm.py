"""Text normalisation for extracted Arabic reference text.

``pdftotext`` renders lam-alef ligatures of the two PowerPoint-exported
reference PDFs with the glyph order reversed ("اإلدارية" for "الإدارية",
"االمتثال" for "الامتثال", "األعمال" for "الأعمال"). The repair below reverses
the unambiguous cases (definite article before an alef-initial word, lam before
a lam-alef ligature, Unicode presentation forms) and a short curated list of
governance vocabulary whose ligature sits inside the word. Every other string
operation here serves matching only.

Extraction, repair and matching prove only that a passage occurs in a source
file; they establish neither the legal applicability of the passage nor the
approval status of the document that carries it.
"""
from __future__ import annotations

import re
import unicodedata

# Unicode presentation forms of the lam-alef ligatures (FEF5–FEFC) and their
# logical sequences. NFC leaves them alone, so they are mapped explicitly.
_PRESENTATION = {
    "ﻵ": "لآ", "ﻶ": "لآ",
    "ﻷ": "لأ", "ﻸ": "لأ",
    "ﻹ": "لإ", "ﻺ": "لإ",
    "ﻻ": "لا", "ﻼ": "لا",
}

# Order matters: a lam before a reversed ligature ("لال" = "للا") is repaired
# before the article rule, because the article rule can itself produce "لال"
# ("االلتزام" -> "الالتزام"), which must then stay as it is.
_LAM_RULES = (("لال", "للا"), ("لإل", "للإ"), ("لأل", "للأ"), ("لآل", "للآ"))
_ARTICLE_RULES = (("اال", "الا"), ("اإل", "الإ"), ("األ", "الأ"), ("اآل", "الآ"))

# Curated word-internal repairs (governance vocabulary of the two sources).
# Each key is the broken rendering, each value the intended word part.
_WORD_RULES = (
    ("خالل", "خلال"),        # خلال، الإخلال
    ("صالحي", "صلاحي"),      # الصلاحيات، صلاحية
    ("عالقات", "علاقات"),    # العلاقات العامة
    ("عالقة", "علاقة"),
    ("إعالم", "إعلام"),      # وسائل الإعلام، إعلامي
    ("إعالن", "إعلان"),
    ("عالوة", "علاوة"),      # العلاوة السنوية
    ("عالوات", "علاوات"),
    ("بالغات", "بلاغات"),    # إطار عمل البلاغات
    ("أخالق", "أخلاق"),
    ("استقالل", "استقلال"),
    ("عمالء", "عملاء"),
    ("مالحظ", "ملاحظ"),      # الملاحظات
    ("سالمة", "سلامة"),
    ("إطالع", "إطلاع"),
    ("إطالق", "إطلاق"),
    ("إغالق", "إغلاق"),
    ("تعديالت", "تعديلات"),
    ("سجالت", "سجلات"),
    ("معامالت", "معاملات"),
    ("تعامالت", "تعاملات"),
    ("تسهيالت", "تسهيلات"),
    ("تحليالت", "تحليلات"),
    ("مؤهالت", "مؤهلات"),
    ("الئحة", "لائحة"),      # اللائحة (after the lam rule: "الالئحة" -> "اللائحة")
    ("الالزم", "اللازم"),
    ("االت", "الات"),        # مجالات، اتصالات، حالات
)

_BIDI_MARKS = re.compile("[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_SPACES = re.compile(r"\s+")


def strip_marks(text: str) -> str:
    """Remove bidi control characters and zero-width marks that pdftotext emits."""
    return _BIDI_MARKS.sub("", text)


def repair_ligatures(text: str) -> str:
    """Repair reversed lam-alef ligatures produced by pdftotext (heuristic, see module doc)."""
    out = "".join(_PRESENTATION.get(c, c) for c in text)
    for broken, fixed in _LAM_RULES:
        out = out.replace(broken, fixed)
    for broken, fixed in _ARTICLE_RULES:
        out = out.replace(broken, fixed)
    for broken, fixed in _WORD_RULES:
        out = out.replace(broken, fixed)
    return out


_MIRRORED_A = re.compile(r"\(\s*\)([A-Za-z0-9/]+)")   # "( )KYC" -> "(KYC)"
_MIRRORED_B = re.compile(r"\)\(([A-Za-z0-9/]+)")       # ")(n"   -> "(n)"
_COMMA = re.compile(r"\s*،\s*")


def nfc(text: str) -> str:
    """NFC normalisation, bidi marks removed, whitespace collapsed, ligatures repaired.

    Also restores Latin tokens whose parentheses pdftotext mirrored ("( )KYC",
    ")(n") and the spacing of the Arabic comma.
    """
    t = strip_marks(text)
    t = repair_ligatures(t)
    t = unicodedata.normalize("NFC", t)
    t = _MIRRORED_A.sub(r"(\1)", t)
    t = _MIRRORED_B.sub(r"(\1)", t)
    t = _COMMA.sub("، ", t)
    return _SPACES.sub(" ", t).strip()


def match_key(text: str) -> str:
    """Loose key for fuzzy comparison: NFC text, hamza forms folded, no diacritics or spaces.

    Used for matching only; it never replaces the canonical reader-facing name.
    """
    t = nfc(text)
    t = _TASHKEEL.sub("", t)
    t = t.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"}))
    t = re.sub(r"[^\w]", "", t)
    return t.casefold()


def lam_alef_insensitive(text: str) -> str:
    """Key that ignores every lam and alef: tolerates ligature breaks the repair missed.

    Only meaningful for passages of several words; used as a secondary match.
    """
    return re.sub("[اأإآٱل]", "", match_key(text))
