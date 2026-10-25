"""Conservative *review flags*, not legal materiality determinations.

Never use keyword matches to establish a regulatory violation or to delete a
comment. Flags can only increase scrutiny of a withdrawal proposal.
"""
from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile("[\u064b-\u0652\u0670\u0640]")


def _fold(text: str) -> str:
    """Diacritic-, hamza-, ta-marbuta- and case-insensitive form: «المزوّرة» meets «مزور», «مسؤولاً» meets «مسؤول»."""
    t = _DIACRITICS.sub("", unicodedata.normalize("NFKC", text or ""))
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ؤ", "و").replace("ئ", "ي").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", t).casefold()


TRIGGERS: dict[str, tuple[str, ...]] = {
    "AML": ("غسل الأموال", "غسل الاموال", "تمويل الإرهاب", "تمويل الارهاب",
            "money laundering", "anti-money laundering", "aml", "kyc", "مكافحة غسل"),
    "FINANCIAL_CRIME": ("احتيال", "جرائم مالية", "fraud", "financial crime", "مكافحة الاحتيال"),
    "REGULATORY": ("الجهة الرقابية", "الجهات الرقابية", "الالتزامات النظامية",
                   "الجهات التنظيمية", "regulatory", "regulator", "رقابي", "الامتثال"),
    "DATA_PROTECTION": ("البيانات الشخصية", "حماية البيانات", "خصوصية", "personal data", "privacy"),
    "DELEGATED_AUTHORITY": ("مصفوفة الصلاحيات", "صاحب الصلاحية", "المفوضين",
                            "المخولين", "التفويض", "delegated authority", "signatory"),
    "SEGREGATION_OF_DUTIES": ("فصل المهام", "فصل الصلاحيات", "segregation of duties",
                              "maker checker", "maker-checker"),
    "FINANCIAL_EXPOSURE": ("تعرض مالي", "خسارة مالية", "الرسوم", "سقف مالي", "فرق السعر", "فروق اسعار",
                           "financial exposure", "liquidity risk"),
    "AUDIT_RIGHTS": ("حق الاطلاع", "مراجعيه", "المراجعين", "التدقيق",
                      "audit rights", "audit access", "books and records"),
    "CONTROL_FAILURE": ("فشل الضوابط", "ضعف الرقابة", "التحقق من صحة", "تزوير", "مزور", "حسن النية",
                         "fraudulent instruction", "control failure"),
    "CONTRACTUAL_LIABILITY": ("مسؤولية", "مسؤول", "التعويض", "أضرار", "غرامة", "يسأل عنه", "إعفاء",
                              "إخلالا جوهريا", "إخلال جوهري", "liability", "indemnification"),
}


def material_review_flags(text: str | None, anchor: str | None = None, *, absent: bool = False) -> list[str]:
    haystack = _fold(f"{text or ''} {anchor or ''}")
    flags = {category for category, phrases in TRIGGERS.items() if any(_fold(p) in haystack for p in phrases)}
    # Fail-safe for an absent observation whose subject cannot be classified:
    # do not call it immaterial merely because the keyword dictionary missed it.
    if absent and not flags:
        flags.add("CONTROL_FAILURE")
    return sorted(flags)


def requires_heightened_review(observation: dict) -> bool:
    return bool(observation.get("material_categories")) or observation.get("observed_change") == "REMOVED_FROM_VERSION"
