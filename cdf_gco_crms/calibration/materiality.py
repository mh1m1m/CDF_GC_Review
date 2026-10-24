"""Conservative *review flags*, not legal materiality determinations.

Never use keyword matches to establish a regulatory violation or to delete a
comment. Flags can only increase scrutiny of a withdrawal proposal.
"""
from __future__ import annotations

import re

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
    "FINANCIAL_EXPOSURE": ("تعرض مالي", "خسارة مالية", "الرسوم", "سقف مالي",
                           "financial exposure", "liquidity risk"),
    "AUDIT_RIGHTS": ("حق الاطلاع", "مراجعيه", "المراجعين", "التدقيق",
                      "audit rights", "audit access", "books and records"),
    "CONTROL_FAILURE": ("فشل الضوابط", "ضعف الرقابة", "التحقق من صحة",
                         "تزوير", "fraudulent instruction", "control failure"),
    "CONTRACTUAL_LIABILITY": ("مسؤولية", "التعويض", "أضرار", "غرامة",
                              "liability", "indemnification"),
}


def material_review_flags(text: str | None, anchor: str | None = None, *, absent: bool = False) -> list[str]:
    haystack = f"{text or ''} {anchor or ''}".casefold()
    flags = {category for category, phrases in TRIGGERS.items() if any(p.casefold() in haystack for p in phrases)}
    # Fail-safe for an absent observation whose subject cannot be classified:
    # do not call it immaterial merely because the keyword dictionary missed it.
    if absent and not flags:
        flags.add("CONTROL_FAILURE")
    return sorted(flags)


def requires_heightened_review(observation: dict) -> bool:
    return bool(observation.get("material_categories")) or observation.get("observed_change") == "REMOVED_FROM_VERSION"
