"""Cell guidance dictionary (UX directive §06; protocol 10.4A.14).

One central dictionary, keyed by field role, round, audience, editability,
closure state and document family, generates every guidance surface:

  layer 1  Excel Note on header and dashboard cells (desktop hover),
  layer 2  data-validation input message on editable cells (on selection),
  layer 3  visible labels on the dashboard (no hover needed),
  layer 4  the help area of the dashboard.

Integrity rules (§06.5): no guidance text creates an approval authority,
presents a management claim as verified, implies that a requester value
closes an observation, or reveals severity or integrity data. The literal
messages fixed by protocol 10.3 for the requester status dropdown are kept
verbatim (D6).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from ..config import round_schema as S

AUD_REQUESTER = "requester"
AUD_EXECUTIVE = "executive"
AUD_GCO = "gco"

EDIT_GCO_ONLY = "gco_only"
EDIT_REQUESTER = "requester"
EDIT_VIEW = "view_only"
EDIT_SELECTOR = "selector"

STATE_ANY = "any"
STATE_OPEN = "not_closed"
STATE_CLOSED = "closed"

DOC_AGREEMENT = "agreement"   # DOC-01…08 and DOC-031…040, 122
DOC_OTHER = "other"

NOTE_AUTHOR = "إدارة الحوكمة والامتثال المؤسسي"
EXAMPLE_TAG = "مثال توضيحي (ليس إفادة فعلية):"


@dataclass(frozen=True)
class GuidanceEntry:
    key: str
    field_role: str
    audience: str
    editability: str
    closure_state: str
    note: str            # Excel Note (layer 1); {ordinal} and {where} are filled per round
    input_title: str     # DV title (≤ 32 characters) – '' when the field is not editable
    input_prompt: str    # DV prompt (≤ 255 characters)
    visible: str         # short visible cue (layer 3)


def _where(doc_family: str) -> str:
    return "المادة أو البند أو الصفحة" if doc_family == DOC_AGREEMENT else "القسم أو الفقرة أو الصفحة"


_STATUS_LINES = (
    f"{S.CLOSED}: لا يلزم إجراء.\n"
    f"{S.CLOSED_COND}: يلزم استيفاء الشرط المذكور في سطر \"شرط الإغلاق:\".\n"
    f"{S.REQUIRES_EDIT}: يلزم استكمال التعديل المذكور في سطر \"المطلوب:\".\n"
    f"{S.OPEN}: لم تُقدَّم إفادة أو تعديل يمكن التحقق منه."
)

ENTRIES: tuple[GuidanceEntry, ...] = (
    GuidanceEntry("reader_no", "reader_no", AUD_REQUESTER, EDIT_VIEW, STATE_ANY,
                  "رقم الملاحظة، وهو نفسه في تعليقات ملف Word وفي لوحة المتابعة، ولا يتغير بين الجولات.",
                  "", "", "رقم ثابت"),
    GuidanceEntry("location", "location", AUD_REQUESTER, EDIT_VIEW, STATE_ANY,
                  "موضع الملاحظة في الوثيقة كما صدرت في جولتها الأولى. إذا تغيّر الموضع لاحقاً، "
                  "يبيّنه سطر \"تغيّر موضع الملاحظة\" في مرئيات الحوكمة للجولة المعنية.",
                  "", "", "موضع الإصدار"),
    GuidanceEntry("quote", "quote", AUD_REQUESTER, EDIT_VIEW, STATE_ANY,
                  "النص محل الملاحظة كما ورد في الوثيقة عند إصدار الملاحظة، ويُحفظ دون تعديل.",
                  "", "", "النص كما ورد"),
    GuidanceEntry("comment", "comment", AUD_REQUESTER, EDIT_VIEW, STATE_ANY,
                  "الملاحظة كما صدرت من إدارة الحوكمة والامتثال المؤسسي بصياغتها المعتمدة، "
                  "وتُحفظ دون تعديل لأغراض التتبع التاريخي.",
                  "", "", "الملاحظة الأصلية"),
    GuidanceEntry("closure", S.ROLE_CLOSURE, AUD_REQUESTER, EDIT_GCO_ONLY, STATE_ANY,
                  "حالة الإغلاق – الجولة {ordinal}\nتقييم إدارة الحوكمة والامتثال المؤسسي لهذه الجولة، "
                  "وليس حقلاً لإفادة الإدارة صاحبة الطلب.\n" + _STATUS_LINES,
                  "تقييم إدارة الحوكمة",
                  "حقل تقييم تحدده إدارة الحوكمة والامتثال المؤسسي، ولا تعدّله الإدارة صاحبة الطلب. "
                  "تُكتب الإفادة في عمود \"الإفادة او التحديث الحاصل\" للجولة الحالية.",
                  "تقييم الحوكمة – للعرض"),
    GuidanceEntry("closure_r1", S.ROLE_CLOSURE, AUD_REQUESTER, EDIT_GCO_ONLY, STATE_ANY,
                  "حالة الإغلاق – الجولة الأولى\nفي الجولة الأولى تعني \"مفتوحة\" أن الملاحظة بانتظار الإفادة "
                  "الأولى فقط، ولا تعني قصوراً.\n" + _STATUS_LINES,
                  "تقييم إدارة الحوكمة",
                  "حقل تقييم تحدده إدارة الحوكمة والامتثال المؤسسي، ولا تعدّله الإدارة صاحبة الطلب.",
                  "بانتظار الإفادة الأولى"),
    GuidanceEntry("feedback", S.ROLE_FEEDBACK, AUD_REQUESTER, EDIT_GCO_ONLY, STATE_ANY,
                  "مرئيات الحوكمة على التحديث – الجولة {ordinal}\nتقييم إدارة الحوكمة والامتثال المؤسسي للتعديلات "
                  "أو الإفادات الواردة بعد الجولة السابقة: ما تغيّر في النص وما بقي، وما يلزم في سطر \"المطلوب:\" "
                  "أو \"شرط الإغلاق:\". للعرض فقط.",
                  "مرئيات إدارة الحوكمة",
                  "مرئيات إدارة الحوكمة والامتثال المؤسسي لهذه الجولة، للعرض فقط.",
                  "مرئيات الحوكمة – للعرض"),
    GuidanceEntry("response_current", S.ROLE_RESPONSE, AUD_REQUESTER, EDIT_REQUESTER, STATE_OPEN,
                  "الإفادة او التحديث الحاصل – الجولة {ordinal}\nتعبّئها الإدارة صاحبة الطلب للملاحظات غير المغلقة: "
                  "يرجى بيان الإجراء المتخذ وموضع التعديل في الوثيقة ({where})، أو مبرر عدم التطبيق.\n"
                  + EXAMPLE_TAG + " \"عُدّل البند (5-2) بإضافة اشتراط موافقة صاحب الصلاحية قبل إطلاق أي مبادرة.\"",
                  "الإفادة – الجولة الحالية",
                  "يرجى بيان الإجراء المتخذ وموضع التعديل في الوثيقة ({where})، أو مبرر عدم التطبيق. "
                  "تُكتب الإفادة مباشرة في الخلية فيختفي النص الإرشادي.",
                  "مطلوب من الإدارة صاحبة الطلب"),
    GuidanceEntry("response_closed", S.ROLE_RESPONSE, AUD_REQUESTER, EDIT_REQUESTER, STATE_CLOSED,
                  "", "ملاحظة مغلقة",
                  "الملاحظة مغلقة ولا يلزم إجراء. إذا كان لدى الإدارة اعتراض على الإغلاق، يُكتب في هذه الخلية "
                  "وتُعاد دراسته في الجولة التالية.",
                  "لا يلزم إجراء"),
    GuidanceEntry("response_history", S.ROLE_RESPONSE, AUD_REQUESTER, EDIT_VIEW, STATE_ANY,
                  "الإفادة او التحديث الحاصل – الجولة {ordinal}\nإفادة الإدارة صاحبة الطلب في هذه الجولة، "
                  "محفوظة كما وردت ضمن السجل التراكمي.",
                  "", "", "إفادة سابقة محفوظة"),
    GuidanceEntry("impl_current", S.ROLE_IMPL, AUD_REQUESTER, EDIT_REQUESTER, STATE_ANY,
                  "حالة تطبيق الملاحظات – الجولة {ordinal}\nيرجى اختيار حالة التطبيق من القائمة. تمثل القيمة إفادة الإدارة "
                  "صاحبة الطلب ولا تُغلق الملاحظة بذاتها؛ تقرر إدارة الحوكمة والامتثال حالة الإغلاق بعد التحقق "
                  "من النص. القيمة \"" + S.IMPL_PRIOR_CLOSED + "\" تكتبها إدارة الحوكمة وحدها.",
                  S.DV_IMPL_PROMPT_TITLE, S.DV_IMPL_PROMPT,            # literal 10.3 messages (D6)
                  "اختيار من القائمة"),
    GuidanceEntry("impl_history", S.ROLE_IMPL, AUD_REQUESTER, EDIT_VIEW, STATE_ANY,
                  "حالة تطبيق الملاحظات – الجولة {ordinal}\nحالة التطبيق كما أفادت بها الإدارة صاحبة الطلب في هذه "
                  "الجولة، محفوظة ضمن السجل التراكمي. وهي إفادة لا تُغلق الملاحظة بذاتها.",
                  S.DV_IMPL_PROMPT_TITLE, S.DV_IMPL_PROMPT, "إفادة سابقة محفوظة"),
    # ------------------------------------------------------------- dashboard
    GuidanceEntry("dash_round", "selector_round", AUD_EXECUTIVE, EDIT_SELECTOR, STATE_ANY,
                  "يرجى اختيار الجولة المطلوب عرض موقف المراجعة فيها. تتغير البطاقات والجداول والرسوم لتعكس تلك "
                  "الجولة، ولا يتغير شيء في ورقة الملاحظات.",
                  "الجولة المعروضة",
                  "يرجى اختيار جولة من القائمة لعرض موقف المراجعة فيها. الاختيار للعرض فقط ولا يغيّر أي بيانات.",
                  "اختيار للعرض فقط"),
    GuidanceEntry("dash_compare", "selector_compare", AUD_EXECUTIVE, EDIT_SELECTOR, STATE_ANY,
                  "يرجى اختيار جولة للمقارنة مع الجولة المعروضة؛ تعرض مصفوفة الانتقال عدد الملاحظات حسب حالتها في الجولتين.",
                  "جولة المقارنة",
                  "يرجى اختيار جولة للمقارنة. المقارنة للعرض فقط ولا تغيّر أي تقييم.",
                  "مقارنة للعرض فقط"),
    GuidanceEntry("dash_scope", "selector_scope", AUD_EXECUTIVE, EDIT_SELECTOR, STATE_ANY,
                  "يرجى اختيار الملاحظات التي يعرضها جدول الملاحظات في الجولة المعروضة.",
                  "نطاق جدول الملاحظات",
                  "يرجى اختيار نطاق العرض من القائمة. التصفية للعرض فقط.",
                  "تصفية للعرض فقط"),
    GuidanceEntry("dash_obs", "selector_obs", AUD_EXECUTIVE, EDIT_SELECTOR, STATE_ANY,
                  "يرجى اختيار رقم ملاحظة لعرض تفاصيلها ومسارها عبر الجولات.",
                  "الملاحظة المختارة",
                  "يرجى اختيار رقم الملاحظة من القائمة لعرض تفاصيلها.",
                  "اختيار للعرض فقط"),
    GuidanceEntry("kpi_rate", "kpi_rate", AUD_EXECUTIVE, EDIT_VIEW, STATE_ANY,
                  "نسبة الملاحظات المغلقة إلى إجمالي الملاحظات الصادرة حتى الجولة المعروضة. لا تُحسب "
                  "\"مغلقة بشرط\" ضمن المغلقة، ولا تعني النسبة اعتماد الوثيقة أو مستوى امتثالها.",
                  "", "", "مؤشر عرض"),
    GuidanceEntry("kpi_change", "change_label", AUD_EXECUTIVE, EDIT_VIEW, STATE_ANY,
                  "وصف مشتق لانتقال حالة الملاحظة بين الجولة السابقة والجولة المعروضة، للعرض فقط، "
                  "وليس حالة إغلاق.", "", "", "مؤشر مشتق"),
    GuidanceEntry("readiness", "readiness", AUD_EXECUTIVE, EDIT_VIEW, STATE_ANY,
                  "حالة تشغيلية مستنتجة من حالات الإغلاق في الجولة المعروضة. لا تعني اعتماد الوثيقة ولا قرار إغلاق.",
                  "", "", "حالة تشغيلية"),
)

BY_KEY = {e.key: e for e in ENTRIES}


def entry(key: str) -> GuidanceEntry:
    return BY_KEY[key]


def header_note(role: str, r: int, current_round: int, doc_family: str = DOC_AGREEMENT) -> str:
    """Layer-1 note for a round-block header, generated for the right round."""
    if role == S.ROLE_CLOSURE:
        key = "closure_r1" if r == 1 else "closure"
    elif role == S.ROLE_FEEDBACK:
        key = "feedback"
    elif role == S.ROLE_RESPONSE:
        key = "response_current" if r == current_round else "response_history"
    else:
        key = "impl_current" if r == current_round else "impl_history"
    return BY_KEY[key].note.format(ordinal=S.ordinal(r), where=_where(doc_family))


def fixed_note(key: str) -> str:
    return BY_KEY[key].note


def input_message(key: str, doc_family: str = DOC_AGREEMENT) -> tuple[str, str]:
    e = BY_KEY[key]
    title = e.input_title
    prompt = e.input_prompt.format(where=_where(doc_family))
    if len(title) > 32 or len(prompt) > 255:
        raise ValueError(f"input message too long for {key}")
    return title, prompt


def validate_integrity() -> list[str]:
    """§06.5 checks on the dictionary itself."""
    problems = []
    banned = ("تُغلق الملاحظة تلقائياً", "يعتمد", "خطورة", "حرجة", "سلامة الردود", "«", "»")
    arrows = [chr(c) for c in list(range(0x2190, 0x2200)) + list(range(0x27F0, 0x2800))]
    for e in ENTRIES:
        for field_name in ("note", "input_prompt", "visible", "input_title"):
            text = getattr(e, field_name)
            for b in banned:
                if b in text:
                    problems.append(f"{e.key}.{field_name}: contains {b!r}")
            if any(a in text for a in arrows):
                problems.append(f"{e.key}.{field_name}: contains an arrow character")
        if e.editability == EDIT_REQUESTER and e.field_role == S.ROLE_IMPL:
            if "لا تُغلق الملاحظة بذاتها" not in e.note:
                problems.append(f"{e.key}: must state that the requester value does not close the observation")
    return problems


def export_register(rounds: int = 3) -> list[dict]:
    """Machine-readable register: every entry, expanded for rounds 1..rounds where round-specific."""
    rows = []
    for e in ENTRIES:
        base = asdict(e)
        if "{ordinal}" in e.note:
            for r in range(1, rounds + 1):
                row = dict(base)
                row["round"] = r
                row["note"] = e.note.format(ordinal=S.ordinal(r), where=_where(DOC_AGREEMENT))
                row["input_prompt"] = e.input_prompt.format(where=_where(DOC_AGREEMENT))
                rows.append(row)
        else:
            row = dict(base)
            row["round"] = None
            row["input_prompt"] = e.input_prompt.format(where=_where(DOC_AGREEMENT))
            rows.append(row)
    return rows


def export_json(path: str, rounds: int = 3):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": "CDF-GCO-CRMS/guidance-dictionary/7.11",
                   "keys": ["field_role", "round", "audience", "editability", "closure_state", "document_family"],
                   "entries": export_register(rounds)}, f, ensure_ascii=False, indent=2)
