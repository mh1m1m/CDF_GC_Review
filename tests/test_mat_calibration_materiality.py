"""Materiality review flags are conservative and do not assert legal conclusions."""
from cdf_gco_crms.calibration.materiality import material_review_flags, requires_heightened_review


def test_fallback_flags_unknown_removed_observation():
    assert "CONTROL_FAILURE" in material_review_flags("Unrecognized synthetic case", absent=True)


def test_aml_and_audit_rights_are_flagged():
    a=material_review_flags("نوصي باستثناء متطلبات مكافحة غسل الأموال")
    assert "AML" in a
    b=material_review_flags("حق الاطلاع للمراجعين")
    assert "AUDIT_RIGHTS" in b


def test_authority_and_false_withdrawal_preservation():
    assert "DELEGATED_AUTHORITY" in material_review_flags("التحقق من المفوضين بالتوقيع")
    assert requires_heightened_review({"observed_change":"REMOVED_FROM_VERSION","material_categories":[]})
    assert not requires_heightened_review({"observed_change":"KEEP_UNCHANGED","material_categories":[]})


def test_flags_match_arabic_spelling_variants_and_inflections():
    """«المزوّرة» is a forgery marker, «مسؤولاً» a liability marker, «حسن النية» a control-failure marker."""
    flags = material_review_flags("الاعتماد على حسن النية ينقل مخاطر الخطابات المزوّرة، ويكون الطرف مسؤولاً عن الخسارة")
    assert {"CONTROL_FAILURE", "CONTRACTUAL_LIABILITY"} <= set(flags)
    assert "FINANCIAL_EXPOSURE" in material_review_flags("يتحمّل الصندوق فرق السعر وحده")
    assert material_review_flags("عنوان المادة جاء في آخر الفقرة") == []
