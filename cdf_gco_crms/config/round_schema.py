"""Canonical schema of the cumulative data sheet (protocol Art. 10.2, 10.3, 10.8, Annex D).

Every literal string here is reader-facing and must match the protocol byte for
byte after Unicode NFC normalisation (D6). Nothing in this module refers to a
column letter beyond the fixed block A–H: round blocks are located by header
text (10.3, block discovery).
"""
from __future__ import annotations

import re
import unicodedata

EN_DASH = "–"
SEP = f" {EN_DASH} "

# --- official closure values (17.4, D.2) ------------------------------------
CLOSED = "مغلقة"
CLOSED_COND = "مغلقة بشرط"
REQUIRES_EDIT = "يتطلب تعديل"
OPEN = "مفتوحة"
CLOSURE_VALUES = (CLOSED, CLOSED_COND, REQUIRES_EDIT, OPEN)
NON_CLOSED_TIER0 = (OPEN, REQUIRES_EDIT)

NOT_RAISED = "لم تكن الملاحظة مطروحة في هذه الجولة"  # 10.2

# --- requester implementation status dropdown (10.3, D.3) -------------------
IMPL_DONE = "تم التطبيق"
IMPL_ALT = "تم التطبيق بصيغة بديلة"
IMPL_PARTIAL = "تم التطبيق جزئياً"
IMPL_NOT = "لم يتم التطبيق"
IMPL_NA = "لا ينطبق مع بيان المبرر"
IMPL_PRIOR_CLOSED = f"مغلقة{SEP}تم إغلاق الملاحظة في جولة سابقة"  # GCO-written only
IMPL_VALUES = (IMPL_DONE, IMPL_ALT, IMPL_PARTIAL, IMPL_NOT, IMPL_NA, IMPL_PRIOR_CLOSED)
OWNER_IMPL_VALUES = IMPL_VALUES[:5]

# --- placeholders (10.8, D.8) -----------------------------------------------
PH_TEXT = ("يرجى بيان الإجراء المتخذ وموضع التعديل في الوثيقة (الصفحة أو المادة)، "
           "أو المبرر في حال عدم التطبيق.")
PH_STATUS = "اختر حالة التطبيق من القائمة"
CLOSED_GUIDE_PREFIX = "لا يلزم إجراء. أُغلقت في الجولة"


def closed_guidance(ordinal: str) -> str:
    return f"{CLOSED_GUIDE_PREFIX} {ordinal}"


def carried_closed_feedback(ordinal: str) -> str:
    """GCO feedback of a row carried as closed from an earlier round (10.2)."""
    return f"أُغلقت في الجولة {ordinal}"


NEW_OBS_FEEDBACK_PREFIX = "ملاحظة جديدة أُثيرت في هذه الجولة:"

# --- data validation messages (10.3) ----------------------------------------
DV_IMPL_PROMPT_TITLE = "للإدارة صاحبة الطلب"
DV_IMPL_PROMPT = "اختر حالة تطبيق الملاحظة، ووضّح الإفادة أو موضع التعديل في العمود السابق."
DV_IMPL_ERROR_TITLE = "حالة تطبيق الملاحظات"
DV_IMPL_ERROR = "يرجى اختيار الحالة من القائمة."

# --- headers (10.3, 10.8) ----------------------------------------------------
H_A = "الملاحظة #"
H_B = "ID"
H_C = "موضع الملاحظة، الصفحة، القسم، البند"
H_D = "النص كما ورد في الوثيقة"
H_E = f"التعليق والتوصية{SEP}الصياغة المحدثة"
FIXED_HEADERS = (H_A, H_B, H_C, H_D, H_E)

ROLE_CLOSURE = "closure"
ROLE_FEEDBACK = "feedback"
ROLE_RESPONSE = "response"
ROLE_IMPL = "impl"

ROLE_NAMES = {
    ROLE_CLOSURE: "حالة الإغلاق",
    ROLE_FEEDBACK: "مرئيات الحوكمة على التحديث",
    ROLE_RESPONSE: "الإفادة او التحديث الحاصل",
    ROLE_IMPL: "حالة تطبيق الملاحظات",
}
ROLE_GUIDANCE = {
    ROLE_RESPONSE: "(مطلوب تعبئته من الإدارة صاحبة الطلب للملاحظات غير المغلقة)",
    ROLE_IMPL: "(مطلوب اختياره من القائمة للملاحظات غير المغلقة)",
}
ROUND1_ROLES = (ROLE_CLOSURE, ROLE_RESPONSE, ROLE_IMPL)
ROUNDN_ROLES = (ROLE_CLOSURE, ROLE_FEEDBACK, ROLE_RESPONSE, ROLE_IMPL)
REQUESTER_ROLES = (ROLE_RESPONSE, ROLE_IMPL)
GCO_ROLES = (ROLE_CLOSURE, ROLE_FEEDBACK)

ROLE_WIDTH = {ROLE_CLOSURE: 14, ROLE_FEEDBACK: 52, ROLE_RESPONSE: 36, ROLE_IMPL: 20}
FIXED_WIDTHS = {1: 12, 2: 24, 3: 30, 4: 52, 5: 82}

# --- ordinals (D.1) ------------------------------------------------------------
_ORDINALS = ["الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة",
             "السادسة", "السابعة", "الثامنة", "التاسعة", "العاشرة"]


def ordinal(n: int) -> str:
    if n < 1:
        raise ValueError(f"round must be >= 1, got {n}")
    return _ORDINALS[n - 1] if n <= 10 else str(n)


def ordinal_to_round(text: str) -> int | None:
    t = nfc(text).strip()
    if t in _ORDINALS:
        return _ORDINALS.index(t) + 1
    if t.isdigit() and int(t) >= 11:
        return int(t)
    return None


def round_label(n: int) -> str:
    return f"الجولة {ordinal(n)}"


def data_sheet_name(n: int) -> str:
    """Sheet name per 10.4: round 1 'ملاحظات الجولة الأولى', round n 'الملاحظات حتى الجولة [ordinal]'."""
    name = "ملاحظات الجولة الأولى" if n == 1 else f"الملاحظات حتى الجولة {ordinal(n)}"
    if len(name) > 31 or re.search(r"[:\\/?*\[\]]", name):
        raise ValueError(f"invalid sheet name {name!r}")
    return name


def header_text(role: str, n: int, *, with_guidance: bool = True) -> str:
    first = f"{ROLE_NAMES[role]}{SEP}الجولة {ordinal(n)}"
    if with_guidance and role in ROLE_GUIDANCE:
        return f"{first}\n{ROLE_GUIDANCE[role]}"
    return first


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# --- block discovery -----------------------------------------------------------
_ROLE_BY_NAME = {v: k for k, v in ROLE_NAMES.items()}
_HEADER_RE = re.compile(r"^(?P<role>.+?)\s*(?P<dash>[–\-])\s*الجولة\s+(?P<ord>\S+)\s*$")


def parse_round_header(text) -> tuple[str, int, bool] | None:
    """Return (role, round, legacy_dash) for a round-block header, else None.

    Only the first line of the header counts (the second line of a requester
    header is guidance). A hyphen-minus instead of the en dash is accepted as a
    legacy variant and flagged (10.3).
    """
    if text is None:
        return None
    first = nfc(str(text)).split("\n", 1)[0].strip()
    m = _HEADER_RE.match(first)
    if not m:
        return None
    role = _ROLE_BY_NAME.get(m.group("role").strip())
    rnd = ordinal_to_round(m.group("ord"))
    if role is None or rnd is None:
        return None
    return role, rnd, m.group("dash") != EN_DASH


# --- workflow order / derived labels (D.10) ----------------------------------
# ------------------------------------------------------------- titles (10.4A.16, v7.12)
TITLE_NONE = "NONE"            # no title recorded (legacy observation of an earlier version)
TITLE_DRAFT = "DRAFT"          # written by the engine or a reviewer, not yet proposed
TITLE_PROPOSED = "PROPOSED"    # proposed to the GCO reviewer, awaiting a recorded human decision
TITLE_APPROVED = "APPROVED"    # approved by a named GCO reviewer on a recorded date with a decision reference
TITLE_ISSUED = "ISSUED"        # approved title carried in an issued workbook; immutable afterwards
TITLE_STATES = (TITLE_NONE, TITLE_DRAFT, TITLE_PROPOSED, TITLE_APPROVED, TITLE_ISSUED)
TITLE_SHOWN_STATES = (TITLE_APPROVED, TITLE_ISSUED)
TITLE_FALLBACK_TAG = "الملاحظة #"   # neutral reference, never an unapproved automatic summary
TITLE_MAX = 90

CHANGE_NEW = "ملاحظة جديدة"
CHANGE_STAYED_CLOSED = "بقيت مغلقة"
CHANGE_REOPENED = "أُعيد فتحها"
CHANGE_CLOSED = "أُغلقت خلال الجولة"
CHANGE_COND = "تحسن مشروط"
CHANGE_COND_REGRESS = "تراجعت عن الإغلاق المشروط"
CHANGE_NO_PROGRESS = "بقيت دون تقدم"
CHANGE_SHIFT = "تغيّرت الحالة دون إغلاق"
CHANGE_LABELS = (CHANGE_NEW, CHANGE_STAYED_CLOSED, CHANGE_REOPENED, CHANGE_CLOSED,
                 CHANGE_COND, CHANGE_COND_REGRESS, CHANGE_NO_PROGRESS, CHANGE_SHIFT)

PREV_NA = "لا ينطبق"

REASON_REOPENED = "أُعيد فتحها بعد إغلاق سابق"
REASON_STALLED = "متعثرة لجولتين متتاليتين"
REASON_COND = "مغلقة بشرط لم يُستوفَ شرطها"
REASON_EDIT = "يتطلب تعديل"
REASON_AWAIT_FIRST = "بانتظار الإفادة الأولى"
REASON_OPEN = "مفتوحة دون إفادة كافية"

ACTION_NONE = "لا يلزم إجراء"
ACTION_FIRST = "الإفادة عن الملاحظة وتطبيق التوصية"
ACTION_GENERIC = "استكمال المعالجة وفق مرئيات الحوكمة"

READY_EMPTY = "لا توجد ملاحظات مسجلة"
READY_EMPTY_DETAIL = "لا توجد ملاحظات مسجلة حتى الآن."
READY_NO_DATA = "لا تتوفر بيانات كافية لتحديد الحالة"
READY_ACTION = "توجد ملاحظات تتطلب معالجة"
READY_COND = "توجد شروط إغلاق غير مستوفاة"
READY_ALL_CLOSED = "جميع الملاحظات مغلقة من منظور المراجعة"
READY_NOTE = "ولا يُعد ذلك اعتماداً للوثيقة"

NOT_RECORDED = "غير مسجل"
NO_RESPONSE = "لم تُقدَّم إفادة بعد"

CLOSURE_BASIS_WORDS = {
    "VERIFIED_TEXT": "بالنص المعدل",
    "GCO_REASSESSMENT": "بإعادة تقييم الحوكمة",
    "ROUTED_RESIDUAL": "من جانب الحوكمة والامتثال مع إحالة",
    "RISK_ACCEPTED": "بقرار من صاحب الصلاحية",
}

SCOPE_ALL = "جميع الملاحظات"
SCOPE_ACTION = "الملاحظات التي تتطلب إجراء"
SCOPE_STALLED = "المتعثرة"
SCOPE_REOPENED = "المعاد فتحها"
SCOPE_NEW = "الجديدة في الجولة"
SCOPES = (SCOPE_ALL, SCOPE_ACTION, CLOSED, CLOSED_COND, REQUIRES_EDIT, OPEN,
          SCOPE_STALLED, SCOPE_REOPENED, SCOPE_NEW)

DEMO_BANNER = f"بيانات تجريبية لأغراض الاختبار{SEP}ليست ملاحظات فعلية للصندوق"

# label fragments that must never be counted as owner input (10.4A.7)
NOT_INPUT_TEXTS = (PH_TEXT, PH_STATUS, NOT_RAISED, IMPL_PRIOR_CLOSED)
