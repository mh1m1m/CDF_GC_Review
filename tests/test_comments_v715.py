"""v7.15 comment shape (07.1, 07.2, 07.4A, 08.2A, 08.2B, G-SUB-12, P14, R3(c)(d)): one negative test per rule."""
from cdf_gco_crms.comments import (CLOSURE_LABEL, IMPROVEMENT_LABEL, check_comment, compose_comment, p14_findings,
                                   r3_shape_ok)
from cdf_gco_crms.model.entities import plain_text

GOOD = {
    "form": "F2",
    "analysis": "لا يحدد البند مدة لإشعار الطرف الآخر، مما قد يؤخر معالجة الإخلال.",
    "recommendation": "نوصي بتحديد مدة للإشعار في البند.",
    "proposed_wording": "يلتزم الطرف المخل بمعالجة الإخلال خلال خمسة عشر يوم عمل من تاريخ إشعاره كتابياً.",
    "closure_action": "إدراج المدة في البند وإعادة المسودة.",
    "observation_type": "GAP",
    "severity": "MEDIUM",
}


def with_(**kw):
    o = dict(GOOD)
    o.update(kw)
    return o


def rules(o, **kw):
    return {p.split(" ")[0] for p in check_comment(o, **kw)}


def test_a_well_formed_new_comment_passes():
    assert check_comment(GOOD) == []
    text = plain_text(compose_comment(GOOD))
    assert "التوصية:" in text and "النص المقترح:" in text and text.rstrip().split("\n")[-1].startswith(CLOSURE_LABEL)


def test_07_1_one_reason_sentence():
    assert "07.1" in rules(with_(analysis="لا يحدد البند مدة. وهذا يؤخر المعالجة."))


def test_07_4a_a_reason_and_proposed_text_required():
    assert "07.4A(a)" in rules(with_(analysis=""))
    assert "07.4A(a)" in rules(with_(proposed_wording=""))


def test_07_4a_b_openers():
    assert "07.4A(b)" in rules(with_(recommendation="يُستحسن تحديد مدة للإشعار."))
    imp = with_(observation_type="IMPROVEMENT", severity="LOW", recommendation="نقترح إضافة مدة للإشعار.")
    assert check_comment(imp) == []
    assert "07.4A(b)" in rules(with_(observation_type="IMPROVEMENT", severity="LOW"))       # gap opener on an improvement
    assert "07.4A(b)" in rules(dict(imp, severity="HIGH"))


def test_07_4a_d_no_question():
    assert "07.4A(d)" in rules(with_(recommendation="هل حدد الصندوق مدة للإشعار؟"))
    assert "07.4A(d)" in rules(with_(form="F6"))
    assert not r3_shape_ok(with_(recommendation="هل حدد الصندوق مدة للإشعار؟"))


def test_g_sub_12_conditional_form():
    unseen = with_(depends_on_unseen=True)
    assert "G-SUB-12" in rules(unseen)
    ok = with_(depends_on_unseen=True, recommendation="نوصي بتحديد مدة للإشعار، ما لم تتضمنه اتفاقية الخدمة.")
    assert check_comment(ok) == []


def test_00_2_carve_out_keeps_earlier_comments_valid():
    f6 = with_(form="F6", recommendation="هل حدد الصندوق مدة للإشعار؟", analysis="", proposed_wording="",
               closure_action="", depends_on_unseen=True)
    assert check_comment(f6, protocol="7.14") == []
    assert "G-SUB-12" in rules(dict(f6, form="F2"), protocol="7.14")


def test_07_2_ceilings():
    long = " ".join(["كلمة"] * 36)
    assert "07.2" in rules(with_(analysis=long + "."))
    assert "07.2" in rules(with_(recommendation="نوصي ب" + " كلمة" * 30))
    assert "07.2" in rules(with_(proposed_wording=" ".join(["كلمة"] * 61)))
    whole = with_(analysis=" ".join(["كلمة"] * 34) + ".", recommendation="نوصي ب" + " كلمة" * 28,
                  proposed_wording=" ".join(["كلمة"] * 40))
    assert any("whole comment" in p for p in check_comment(whole))                  # 34 + 29 + 40 > 100
    assert r3_shape_ok(GOOD) and not r3_shape_ok(whole)


def test_08_2a_closing_action():
    assert "08.2A" in rules(with_(closure_action=""))
    assert "08.2A" not in rules(with_(closure_action=""), round_of_birth=False)
    assert "08.2A" in rules(with_(closure_action=" ".join(["كلمة"] * 31)))


def test_08_2b_label_first_and_not_counted():
    imp = with_(observation_type="IMPROVEMENT", severity="LOW", recommendation="نقترح إضافة مدة للإشعار.")
    assert plain_text(compose_comment(imp)).startswith(IMPROVEMENT_LABEL)
    near = dict(imp, analysis=" ".join(["كلمة"] * 35) + ".")        # at the ceiling; the label adds no words
    assert not any(p.startswith("07.2 reason") for p in check_comment(near))


def test_p14_v715_flags_by_comment():
    bad = with_(id="2", analysis="جملة أولى. جملة ثانية.")
    res = p14_findings([dict(GOOD, id="1"), bad])
    assert res["flagged"] == ["2"] and not res["ok"]
    assert p14_findings([GOOD])["ok"]
    old = p14_findings([GOOD, GOOD], protocol="7.14")              # earlier rule: reasons in > 50 % of comments
    assert old["reasons"] == 2 and not old["ok"]
