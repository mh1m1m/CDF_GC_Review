"""Synthetic review histories for the demonstration workbook and the regression suite.

Everything produced here is test data: the document name says so, the
document is flagged ``is_demo`` (dashboard banner "بيانات تجريبية لأغراض
الاختبار – ليست ملاحظات فعلية للصندوق") and no text refers to a real review.

A history is defined by one trajectory per observation: the official closure
value in each round from its birth round. The generator drives the real
engine round by round: GCO assessments go through ``apply_round``, owner
responses are written into the returned round's requester cells, and every
round is rendered to a workbook and parsed back before the next round is
appended (round-trip through the file, as in production).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from ..config import round_schema as S
from ..model.entities import Document, GText, ReviewState, RoundAssessment, Segment
from ..rounds.round_expansion import NewObservation, RoundInput, apply_round, build_round1

C, CC, RE, O = S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN

# --------------------------------------------------------------------------- observations
# (article, clause, page, quote, comment parts) – comment parts: list of (text, bold)
_TOPICS = [
    ("2", "2-1", 3, "تهدف هذه المذكرة إلى تعزيز التعاون بين الطرفين في المجالات الثقافية ذات الاهتمام المشترك",
     [("نوصي بتحديد مجالات التعاون بصورة تتيح قياس تنفيذها، مثلاً \"دعم المشاريع الثقافية الناشئة\".", False)]),
    ("3", "3-1", 3, "يتولى الطرفان تنفيذ المبادرات المشتركة وفق ما يتفقان عليه",
     [("لا يحدد البند الجهة المختصة باعتماد المبادرات في الصندوق.", False), ("\nالتوصية:", True),
      (" نوصي بربط اعتماد المبادرات بصاحب الصلاحية وفق مصفوفة الصلاحيات المعتمدة.", False)]),
    ("3", "3-3", 4, "يجوز لأي من الطرفين إضافة مبادرات جديدة بإشعار الطرف الآخر",
     [("هل يكفي الإشعار لإضافة مبادرة دون موافقة الصندوق المسبقة؟", False)]),
    ("4", "4-2", 4, "يلتزم الطرفان بتبادل البيانات اللازمة لتنفيذ المبادرات",
     [("مشاركة البيانات غير مقيدة بنطاق أو ضوابط، بما قد يخالف سياسة حماية البيانات.", False), ("\nالتوصية:", True),
      (" تقييد المشاركة بالبيانات اللازمة، بالنص الآتي: (\"تقتصر البيانات المتبادلة على ما يلزم لتنفيذ المبادرة المعتمدة، "
       "وتخضع لسياسة حماية البيانات المعتمدة لدى الصندوق\".)", False)]),
    ("4", "4-4", 5, "يحتفظ كل طرف بالبيانات المستلمة للمدة التي يراها مناسبة",
     [("نوصي بتحديد مدة الاحتفاظ بالبيانات وآلية إتلافها بعد انتهائها.", False)]),
    ("5", "5-1", 5, "يشكل الطرفان فريق عمل مشتركاً لمتابعة التنفيذ",
     [("نوصي بتحديد تشكيل فريق العمل وصلاحياته وآلية رفع تقاريره.", False)]),
    ("5", "5-3", 6, "يرفع فريق العمل تقاريره بصفة دورية",
     [("نأمل تحديد دورية التقارير والجهة التي تُرفع إليها في الصندوق.", False)]),
    ("6", "6-1", 6, "لا تترتب على هذه المذكرة أي التزامات مالية على أي من الطرفين",
     [("نوصي بالنص على أن أي التزام مالي لاحق يخضع لاتفاقية مستقلة تعتمد وفق الصلاحيات المالية.", False)]),
    ("6", "6-2", 7, "يتحمل كل طرف التكاليف المترتبة على مشاركته",
     [("هل التكاليف المشار إليها مشمولة بميزانية معتمدة لدى الإدارة صاحبة الطلب؟", False)]),
    ("7", "7-1", 7, "يلتزم الطرفان بالمحافظة على سرية المعلومات المتبادلة",
     [("نوصي بتعريف المعلومات السرية واستثناءات الإفصاح النظامي.", False)]),
    ("7", "7-3", 8, "تستمر التزامات السرية بعد انتهاء المذكرة",
     [("نوصي بتحديد مدة استمرار التزامات السرية بعد انتهاء المذكرة.", False)]),
    ("8", "8-1", 8, "تكون حقوق الملكية الفكرية للمخرجات المشتركة للطرفين",
     [("ملكية المخرجات المشتركة مطلقة دون تحديد نسب أو حقوق استخدام، بما قد يقيد استخدام الصندوق لها.", False),
      ("\nالتوصية:", True), (" تحديد حقوق الاستخدام، بالنص الآتي: (\"يحق للصندوق استخدام المخرجات المشتركة لأغراضه "
                             "المؤسسية دون مقابل، وتحدد الملكية في الاتفاقية التنفيذية لكل مبادرة\".)", False)]),
    ("8", "8-2", 9, "لا يجوز لأي طرف استخدام شعار الطرف الآخر إلا بموافقته",
     [("نوصي باشتراط الموافقة الكتابية المسبقة من الجهة المختصة في الصندوق.", False)]),
    ("9", "9-1", 9, "يجوز لأي طرف الإعلان عن هذه المذكرة",
     [("نوصي بربط أي إعلان بموافقة إدارة الاتصال المؤسسي في الصندوق.", False)]),
    ("10", "10-1", 10, "تسري هذه المذكرة لمدة سنتين وتتجدد تلقائياً",
     [("التجديد التلقائي دون مراجعة يحرم الصندوق من تقييم جدوى الاستمرار.", False), ("\nالتوصية:", True),
      (" نوصي بربط التجديد بتقييم أداء المذكرة وموافقة صاحب الصلاحية.", False)]),
    ("10", "10-2", 10, "يجوز لأي طرف إنهاء المذكرة بإشعار مدته ثلاثون يوماً",
     [("نوصي ببيان أثر الإنهاء على المبادرات القائمة.", False)]),
    ("11", "11-1", 11, "يتحمل كل طرف مسؤولية الأضرار الناتجة عن أعماله",
     [("هل اطلعت الشؤون القانونية على حدود المسؤولية الواردة في البند؟", False)]),
    ("12", "12-1", 11, "يتعاون الطرفان على حل أي خلاف ودياً",
     [("نوصي بتحديد مدة للحل الودي والجهة المختصة بعد انقضائها.", False)]),
    ("13", "13-1", 12, "تسري على هذه المذكرة الأنظمة المعمول بها",
     [("نوصي بالنص على سريان أنظمة المملكة العربية السعودية.", False)]),
    ("14", "14-1", 12, "يتم تعديل المذكرة باتفاق الطرفين",
     [("لا يشترط البند أن يكون التعديل مكتوباً وموقعاً من صاحب الصلاحية.", False), ("\nالتوصية:", True),
      (" اشتراط التعديل المكتوب، بالنص الآتي: (\"لا يُعتد بأي تعديل على هذه المذكرة ما لم يكن مكتوباً وموقعاً من "
       "المفوضين بالتوقيع لدى الطرفين\".)", False)]),
    ("15", "15-1", 13, "توجه الإشعارات إلى العناوين الواردة في صدر المذكرة",
     [("نوصي بتحديد ممثل لكل طرف ووسيلة الإشعار المعتمدة.", False)]),
    ("2", "2-3", 3, "تشمل المذكرة الجهات التابعة للطرفين",
     [("هل يقصد بالجهات التابعة الشركات المملوكة للصندوق؟", False)]),
    ("3", "3-4", 4, "يقدم الطرف الثاني الدعم الفني للمستفيدين",
     [("نوصي بتحديد معايير اختيار المستفيدين والجهة التي تعتمدها.", False)]),
    ("4", "4-5", 5, "يجوز للطرف الثاني مشاركة البيانات مع شركائه",
     [("مشاركة البيانات مع أطراف ثالثة دون موافقة الصندوق تتعارض مع ضوابط حماية البيانات.", False),
      ("\nالتوصية:", True), (" نوصي باشتراط موافقة الصندوق الكتابية المسبقة.", False)]),
    ("5", "5-4", 6, "يعقد فريق العمل اجتماعاته عند الحاجة",
     [("نوصي بتحديد حد أدنى لعدد الاجتماعات وتوثيق محاضرها.", False)]),
    ("6", "6-3", 7, "يقدم الطرف الثاني حوافز للمستفيدين من برامج الصندوق",
     [("هل الحوافز المذكورة معتمدة ضمن برامج الصندوق؟", False)]),
    ("7", "7-4", 8, "يجوز الإفصاح عن المعلومات للجهات الرقابية",
     [("نوصي بإلزام الطرف المفصح بإشعار الطرف الآخر قبل الإفصاح متى كان ذلك جائزاً نظاماً.", False)]),
    ("8", "8-3", 9, "يحق لكل طرف نشر نتائج المبادرات",
     [("نوصي بربط النشر بموافقة الطرفين ومراجعة المحتوى قبل نشره.", False)]),
    ("9", "9-2", 10, "يشارك الطرفان في الفعاليات المشتركة",
     [("هل الفعاليات المشتركة ضمن خطة الفعاليات المعتمدة للصندوق؟", False)]),
    ("10", "10-3", 10, "لا يؤثر انتهاء المذكرة على الالتزامات القائمة",
     [("نوصي بتحديد الالتزامات التي تستمر بعد انتهاء المذكرة.", False)]),
    ("11", "11-2", 11, "لا يتحمل أي طرف الأضرار غير المباشرة",
     [("يوجد خطأ في ترقيم البند.", False)]),
    ("12", "12-2", 12, "يحال الخلاف إلى الجهة المختصة",
     [("نوصي بتحديد الجهة القضائية المختصة.", False)]),
    ("16", "16-1", 13, "حررت هذه المذكرة من نسختين",
     [("نوصي بالنص على اللغة المعتمدة عند الاختلاف بين النصين.", False)]),
    ("1", "1-1", 2, "يقصد بالمبادرة كل نشاط مشترك",
     [("تعريف المبادرة واسع ويشمل أي نشاط دون اعتماد.", False), ("\nالتوصية:", True),
      (" قصر التعريف على النشاط المعتمد، بالنص الآتي: (\"يقصد بالمبادرة النشاط المشترك الذي يعتمده الطرفان كتابة وفق "
       "صلاحياتهما المعتمدة\".)", False)]),
    ("1", "1-3", 2, "يقصد بفريق العمل الممثلون المعينون من الطرفين",
     [("نوصي ببيان آلية تعيين ممثلي الصندوق في فريق العمل.", False)]),
    ("3", "3-5", 4, "يلتزم الطرف الثاني بتنفيذ المبادرات بأفضل الممارسات",
     [("نوصي بربط التنفيذ بمؤشرات أداء قابلة للقياس.", False)]),
    ("5", "5-5", 6, "يحق لأي طرف تغيير ممثليه في فريق العمل",
     [("نوصي باشتراط الإشعار الكتابي بتغيير الممثلين.", False)]),
    ("14", "14-2", 12, "تعد الملاحق جزءاً لا يتجزأ من المذكرة",
     [("نوصي بتحديد ترتيب الأولوية بين المذكرة وملاحقها عند التعارض.", False)]),
]

_NEW_TOPICS = [
    ("6", "6-4", 7, "يجوز للطرف الثاني تحصيل رسوم من المستفيدين",
     [("أُضيف البند في النسخة المحدثة دون ضوابط للرسوم.", False), ("\nالتوصية:", True),
      (" نوصي بربط أي رسوم بموافقة الصندوق المسبقة.", False)], "أُضيف البند (6-4) في النسخة المحدثة."),
    ("10", "10-4", 11, "يجوز تمديد المذكرة بإشعار من الطرف الثاني",
     [("التمديد بإشعار من طرف واحد يتعارض مع البند (10-1).", False), ("\nالتوصية:", True),
      (" نوصي بحذف البند أو ربط التمديد بموافقة الطرفين.", False)], "أثرها تعديل البند (10-4) في النسخة المحدثة."),
    ("4", "4-6", 5, "ينقل الطرف الثاني البيانات إلى خوادم خارج المملكة عند الحاجة",
     [("هل حصلت الإدارة على رأي الأمن السيبراني بشأن نقل البيانات خارج المملكة؟", False)],
     "أُضيف البند (4-6) في النسخة المحدثة."),
    ("8", "8-4", 9, "يمنح الصندوق الطرف الثاني ترخيصاً دائماً لاستخدام المخرجات",
     [("الترخيص الدائم يتجاوز مدة المذكرة دون سند.", False), ("\nالتوصية:", True),
      (" نوصي بقصر الترخيص على مدة المذكرة.", False)], "أُضيف البند (8-4) في النسخة المحدثة."),
]

# trajectories over rounds 1..5 (None before birth)
DEMO_TRAJ = (
    [[O, C, C, C, C]] * 10 +                     # 1–10 closed in round 2
    [[O, RE, C, C, C]] * 1 +                     # 11
    [[O, C, C, RE, RE]] +                        # 12 closed r2, reopened r4 (TEST E)
    [[O, RE, C, C, C]] * 4 +                     # 13–16
    [[O, CC, CC, C, C]] * 3 +                    # 17–19 conditional then closed
    [[O, C, C, RE, C]] +                         # 20 closed, reopened, reclosed (TEST 20)
    [[O, RE, CC, CC, CC]] * 2 +                  # 21–22 condition not yet met
    [[O, RE, RE, RE, RE]] * 3 +                  # 23–25 stalled
    [[O, O, O, RE, RE]] * 2 +                    # 26–27 stalled
    [[O, C, C, C, RE]] +                         # 28 reopened in r5
    [[O, RE, C, RE, RE]] +                       # 29
    [[O, O, RE, RE, C]] * 3 +                    # 30–32 late closure
    [[O, RE, RE, CC, C]] * 2 +                   # 33–34
    [[O, O, RE, C, C]] * 3 +                     # 35–37
    [[O, CC, RE, C, C]]                          # 38 conditional regressed then closed
)
DEMO_NEW = {3: [[O, RE, C], [O, O, RE]], 4: [[O, C], [O, O]]}
DEMO_DATES = {1: "2026-07-05", 2: "2026-07-26", 3: "2026-08-17", 4: "2026-09-09", 5: "2026-10-01"}
DEMO_VERSIONS = {1: "الإصدار 0.1", 2: "الإصدار 0.2", 3: "الإصدار 0.3", 4: "الإصدار 0.4", 5: "الإصدار 0.5"}
MOVES = {6: 3, 25: 4}            # reader -> round in which the passage moved (location line)
BASIS = {4: "GCO_REASSESSMENT", 9: "ROUTED_RESIDUAL", 16: "RISK_ACCEPTED"}


def demo_document() -> Document:
    return Document(name="مذكرة تفاهم تجريبية مع جهة شريكة افتراضية", code="DMO",
                    owning_department="إدارة الشراكات (افتراضية)", is_demo=True)


def _loc(art, cl, page):
    return f"ص.{page}، المادة ({art}) – البند ({cl})"


def topic_obs(i: int) -> NewObservation:
    art, cl, page, quote, parts = _TOPICS[i % len(_TOPICS)]
    return NewObservation(_loc(art, cl, page), quote + " …", GText([Segment(t, b) for t, b in parts]))


def _clause_of(text: str) -> str:
    import re
    m = re.search(r"البند \(([\d-]+)\)", text)
    return m.group(1) if m else "المعني"


def feedback(prev: str, value: str, r: int, clause: str, *, late: bool, moved_line: str | None,
             birth: int, reader: str, history: list[str]) -> GText:
    segs: list[Segment] = []
    if moved_line:
        segs.append(Segment(moved_line + "\n"))
    if value == C:
        if prev == C:
            raise ValueError("carried-closed rows get no assessment")
        segs.append(Segment(f"في ضوء التعديل الوارد في البند ({clause})، تحقق المطلوب في النص." if prev != RE
                            else f"استُكمل التعديل المطلوب في البند ({clause}) في النسخة المحدثة."))
        return GText(segs)
    if value == CC:
        segs.append(Segment(f"أُدرج النص المقترح في البند ({clause}) بتغييرات متعقبة لم تُقبل بعد."))
        segs.append(Segment("\nشرط الإغلاق:", True))
        segs.append(Segment(" قبول التغييرات المتعقبة مع الإبقاء على تعليقات إدارة الحوكمة."))
        return GText(segs)
    if prev == C:   # reopened
        segs.append(Segment(f"تغيّر في النسخة المحدثة النص الذي أُغلقت عليه الملاحظة في الجولة {S.ordinal(history.index(C) + birth if C in history else 2)}، "
                            f"وحُذف من البند ({clause}) اشتراط موافقة صاحب الصلاحية."))
        segs.append(Segment("\nالمطلوب:", True))
        segs.append(Segment(f" إعادة اشتراط موافقة صاحب الصلاحية في البند ({clause})."))
        return GText(segs)
    if late and value in (RE, O):
        segs.append(Segment(f"نشكر لكم الإفادة، إلا أن البند ({clause}) لا يزال دون تحديد صاحب الصلاحية. والغرض "
                            "ضمان ألا يُلزَم الصندوق بما لم يعتمده صاحب الصلاحية. والخطر: نفاذ التزام لم يُعتمد."))
        segs.append(Segment("\nالتوصية:", True))
        segs.append(Segment(f" طلبنا في الجولات السابقة تحديد صاحب الصلاحية، ولم يتغير النص؛ نوصي بإحلال البند ({clause}) "
                            "بالنص المقترح."))
        segs.append(Segment("\nالنص المقترح:", True))
        segs.append(Segment(f" (\"يخضع تنفيذ هذا البند لموافقة صاحب الصلاحية في الصندوق وفق مصفوفة الصلاحيات "
                            f"المعتمدة\".)", True))
        return GText(segs)
    if value == RE:
        segs.append(Segment(f"أُضيف نص في البند ({clause}) دون تحديد الجهة المختصة."))
        segs.append(Segment("\nالمطلوب:", True))
        segs.append(Segment(" تحديد الجهة المختصة في الصندوق في النص."))
        return GText(segs)
    segs.append(Segment("لم يُعثر على تعديل في النص ولم تُقدَّم إفادة."))
    segs.append(Segment("\nالمطلوب:", True))
    segs.append(Segment(" الإفادة عن الملاحظة وتطبيق التوصية."))
    return GText(segs)


_RESPONSES = {
    C: ("تم تعديل البند ({c}) وفق التوصية.", S.IMPL_DONE),
    CC: ("أُدرج النص المقترح في البند ({c}) وسيُعتمد مع النسخة النهائية.", S.IMPL_DONE),
    RE: ("عُدّل البند ({c}) جزئياً، وجارٍ استكمال الباقي.", S.IMPL_PARTIAL),
    O: ("نرى أن البند ({c}) كافٍ بصيغته الحالية.", S.IMPL_NOT),
}


@dataclass
class History:
    trajectories: dict[str, list]          # iid -> values by round (index 0 = round 1; None before birth)
    states: dict[int, ReviewState] = field(default_factory=dict)       # as delivered in round r
    files: dict[int, Path] = field(default_factory=dict)
    returned: dict[int, ReviewState] = field(default_factory=dict)     # round r as returned by the owner


def simulate_owner(state: ReviewState, r: int, next_values: dict[str, str], rng: random.Random,
                   silence: float = 0.15):
    """Write owner responses into round r's requester cells (what the owner returns before round r+1)."""
    for o in state.observations:
        if o.value(r) in ("", C):
            continue
        nv = next_values.get(o.internal_id)
        if nv is None or rng.random() < silence and nv == O:
            continue                                          # no input: placeholder kept
        text, impl = _RESPONSES.get(nv, _RESPONSES[O])
        clause = _clause_of(str(o.location))
        o.cells[r].response = text.format(c=clause)
        o.cells[r].impl = impl


def run_history(document: Document, base: list[NewObservation], traj: list[list[str]],
                new_by_round: dict[int, list[tuple[NewObservation, list[str]]]] | None = None, *,
                rounds: int, dates: dict | None = None, versions: dict | None = None,
                outdir: Path | None = None, roundtrip: bool = True, seed: int = 7,
                moves: dict | None = None, basis: dict | None = None, build_rounds: set | None = None,
                silence: float = 0.15) -> History:
    """Drive the engine round by round. ``traj`` has one list per base observation (index 0 = round 1)."""
    from ..excel.workbook_builder import build_workbook
    from ..ingestion.workbook_reader import parse_workbook
    rng = random.Random(seed)
    dates = dates or {}
    versions = versions or {}
    moves = moves or {}
    basis = basis or {}
    new_by_round = new_by_round or {}
    st = build_round1(document, base, date=dates.get(1), document_version=versions.get(1))
    tmap = {o.internal_id: list(t) for o, t in zip(st.ordered(), traj)}
    hist = History(trajectories=tmap)

    def save(state, r):
        hist.states[r] = state
        if outdir is not None and (build_rounds is None or r in build_rounds or r == rounds):
            from ..config.workbook_settings import file_stem
            p = Path(outdir) / f"{file_stem(document.name, r)}.xlsx"
            build_workbook(state, p)
            hist.files[r] = p
            if roundtrip:
                parsed = parse_workbook(p).state
                parsed.document = state.document
                parsed.rounds = state.rounds
                for po in parsed.observations:
                    po.closure_basis = dict(state.by_id()[po.internal_id].closure_basis)
                return parsed
        return state

    st = save(st, 1)
    for r in range(2, rounds + 1):
        nxt = {iid: t[r - 1] for iid, t in tmap.items() if len(t) >= r and t[r - 1] is not None}
        simulate_owner(st, r - 1, nxt, rng, silence)
        import copy as _copy
        hist.returned[r - 1] = _copy.deepcopy(st)
        assessments = []
        for o in st.ordered():
            t = tmap[o.internal_id]
            prev, val = t[r - 2], t[r - 1]
            if prev == C and val == C:
                continue                                          # carried closed
            hist_vals = [x for x in t[:r - 1] if x is not None]
            moved = moves.get(o.reader_int)
            line = None
            if moved is not None and moved <= r and val != C:
                line = f"الجولة {S.ordinal(moved)}: تغيّر موضع الملاحظة إلى ص.≈{8 + o.reader_int % 5}، المادة (7) – البند (7-{o.reader_int % 4 + 1})"
            fb = feedback(prev, val, r, _clause_of(str(o.location)), late=(r >= 3 and o.reader_int % 3 == 0),
                          moved_line=line, birth=o.birth_round, reader=o.reader_no, history=hist_vals)
            b = basis.get(o.reader_int) if val == C else None
            assessments.append(RoundAssessment(o.internal_id, r, val, fb, b or ("VERIFIED_TEXT" if val == C else None)))
        new_specs = new_by_round.get(r, [])
        rin = RoundInput(r, dates.get(r), versions.get(r), assessments, [n for n, _ in new_specs])
        st, rep = apply_round(st, rin)
        for iid, (_, t) in zip(rep.new_ids, new_specs):
            tmap[iid] = [None] * (r - 1) + list(t)
        st = save(st, r)
    return hist


def demo_history(outdir: Path | None = None, *, rounds: int = 5, build_rounds: set | None = None) -> History:
    base = [topic_obs(i) for i in range(len(DEMO_TRAJ))]
    new = {}
    k = 0
    for r, trajs in DEMO_NEW.items():
        specs = []
        for t in trajs:
            art, cl, page, quote, parts, reason = _NEW_TOPICS[k]
            k += 1
            specs.append((NewObservation(_loc(art, cl, page), quote + " …", GText([Segment(a, b) for a, b in parts]),
                                         reason=reason), t))
        new[r] = specs
    return run_history(demo_document(), base, [list(t) for t in DEMO_TRAJ], new, rounds=rounds,
                       dates=DEMO_DATES, versions=DEMO_VERSIONS, outdir=outdir, moves=MOVES, basis=BASIS,
                       build_rounds=build_rounds)


def fixture_document(code: str = "TST") -> Document:
    return Document(name="وثيقة اختبار آلي", code=code, owning_department="إدارة افتراضية", is_demo=True)


def random_trajectories(n: int, rounds: int, rng: random.Random) -> list[list[str]]:
    out = []
    for _ in range(n):
        t = [O]
        for r in range(2, rounds + 1):
            p = t[-1]
            x = rng.random()
            if p == C:
                t.append(C if x < 0.9 else RE)
            elif p == CC:
                t.append(C if x < 0.5 else (CC if x < 0.85 else RE))
            else:
                t.append(C if x < 0.35 else CC if x < 0.5 else RE if x < 0.8 else O)
        out.append(t)
    return out
