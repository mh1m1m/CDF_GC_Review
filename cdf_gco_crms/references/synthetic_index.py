"""Public-safe SYNTHETIC reference index (v7.12 public-repository fixture).

The real reference layer parses two institutional PDFs that are not part of
the public repository. This module builds a :class:`ReferenceIndex` of the
same shape from an entirely fictional organisational structure and an
entirely fictional authority matrix, so that every test and every workflow
command can run from a fresh public clone.

Rules
  * Nothing here reproduces a passage, a name, a page or a hash of any CDF
    document. Sector and unit names are generic function names; tasks and
    matrix items are generic governance wording written for this fixture.
  * Every source status carries ``approval_status = SYNTHETIC_NOT_APPROVED``
    and ``hash_status = SYNTHETIC``; the file names start with ``SYNTHETIC-``.
    No consumer can mistake the fixture for the institutional sources.
  * The fixture is opt-in for the command line (``--synthetic-reference``)
    and the default only for tests when the real sources are absent
    (:func:`load_reference_index`). A review run against the synthetic index
    is recorded as ``reference_mode = SYNTHETIC`` and never authorises an
    institutional issue (see ``cdf_gco_crms.release.authorization_gate``).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .authority_matrix import (
    CONF_HIGH, ROLE_APPROVE, ROLE_NOTIFY, ROLE_PREPARE, ROLE_RECOMMEND, ROLE_REVIEW, Item, MatrixIndex, MatrixPage,
)
from .index import (
    APPLICABILITY, DEFAULT_MATRIX_PDF, DEFAULT_ORG_PDF, DEFAULT_ORG_TEXT, ReferenceIndex, SourceStatus,
)
from .org_structure import OrgIndex, Sector, Unit

SYNTHETIC_LABEL = "SYNTHETIC_REFERENCE_FIXTURE"
SYNTHETIC_APPROVAL = "SYNTHETIC_NOT_APPROVED"
SYNTHETIC_EVIDENCE = "SYNTHETIC_FIXTURE: fictional content written for the public repository; no institutional source"
HASH_SYNTHETIC = "SYNTHETIC"
ORG_FILE = "SYNTHETIC-org-structure.fixture"
MATRIX_FILE = "SYNTHETIC-authority-matrix.fixture"
MODE_REAL = "INSTITUTIONAL_SOURCES"
MODE_SYNTHETIC = "SYNTHETIC"

# Generic bodies of the fictional matrix (the canonical body names of the parser are reused so that the
# role/chain queries behave exactly as on a parsed matrix).
B_BOARD = "مجلس الإدارة"
B_EXEC = "اللجنة التنفيذية"
B_AUDIT = "لجنة المراجعة والمخاطر والامتثال"
B_CEO = "الرئيس التنفيذي"
B_IA = "رئيس المراجعة الداخلية"

# ----------------------------------------------------------------- fictional organisation
# Sector → units → tasks. The governance unit's tasks share the vocabulary of the synthetic review fixtures
# (agreements, delegations, data protection, confidentiality, reporting); the other sectors' tasks are kept
# lexically apart so that the fixture is deterministic for the mandate-overlap rules.
_SECTORS: tuple[tuple[str, int, tuple[tuple[str, int, tuple[str, ...]], ...]], ...] = (
    ("قطاع الحوكمة والشؤون القانونية", 2, (
        ("الحوكمة والامتثال", 3, (
            "مراجعة مذكرات التفاهم والاتفاقيات قبل اعتمادها والتأكد من اتساقها مع السياسات المعتمدة",
            "التحقق من ربط اعتماد المبادرات والالتزامات بصاحب الصلاحية وفق مصفوفة الصلاحيات المعتمدة",
            "مراجعة ضوابط مشاركة البيانات وسرية المعلومات ومدد الاحتفاظ بها في الاتفاقيات",
            "متابعة تشكيل فرق العمل المشتركة ودورية رفع تقاريرها إلى الجهة المختصة",
            "مراجعة بنود الملكية الفكرية وحقوق الاستخدام واستخدام الشعار في الاتفاقيات",
            "إعداد تقارير الامتثال الدورية ومتابعة إقفال الملاحظات",
        )),
        ("الشؤون القانونية", 4, (
            "صياغة العقود النموذجية ومراجعة الصياغة النظامية للوثائق التعاقدية",
            "تمثيل المنشأة أمام الجهات القضائية ومتابعة الدعاوى",
            "إبداء الرأي النظامي في المسائل المحالة من الوحدات",
        )),
    )),
    ("قطاع الخدمات المساندة", 5, (
        ("الموارد البشرية", 6, (
            "التوظيف والتعيين وإدارة ملفات الموظفين",
            "تخطيط التدريب وتقييم الأداء الوظيفي",
            "إدارة الرواتب والبدلات والإجازات",
        )),
        ("تقنية المعلومات", 7, (
            "تشغيل الأنظمة والشبكات والبنية التحتية الرقمية",
            "الدعم الفني للمستخدمين وإدارة الأجهزة",
            "النسخ الاحتياطي واستمرارية الأنظمة",
        )),
        ("المالية والميزانية", 8, (
            "إعداد الميزانية التقديرية والحسابات الختامية",
            "صرف المستحقات وتسجيل القيود المحاسبية",
            "إدارة الخزينة والتحصيل",
        )),
    )),
    ("قطاع البرامج", 9, (
        ("تخطيط البرامج", 10, (
            "تصميم البرامج وتحديد مؤشرات قياسها",
            "جدولة الأنشطة وتخصيص الموارد التشغيلية",
        )),
        ("الفعاليات", 11, (
            "تنظيم الفعاليات والمعارض وإدارة الموقع",
            "التنسيق اللوجستي مع مقدمي الخدمات",
        )),
    )),
)

# ----------------------------------------------------------------- fictional authority matrix
_CATEGORIES = {1: "الحوكمة والسياسات", 2: "الاتفاقيات والشراكات", 3: "الشؤون المالية"}
_ITEMS: tuple[tuple[str, int, str, int, dict[str, str]], ...] = (
    ("1.1", 1, "اعتماد السياسات والأدلة الداخلية", 2,
     {B_CEO: ROLE_PREPARE, B_AUDIT: ROLE_REVIEW, B_EXEC: ROLE_RECOMMEND, B_BOARD: ROLE_APPROVE}),
    ("1.2", 1, "اعتماد خطة المراجعة الداخلية السنوية", 2,
     {B_IA: ROLE_PREPARE, B_AUDIT: ROLE_APPROVE, B_BOARD: ROLE_NOTIFY}),
    ("2.1", 2, "اعتماد مذكرات التفاهم واتفاقيات التعاون", 3,
     {B_CEO: ROLE_PREPARE, B_EXEC: ROLE_RECOMMEND, B_BOARD: ROLE_APPROVE}),
    ("2.2", 2, "اعتماد المبادرات المشتركة ضمن اتفاقية قائمة", 3,
     {B_CEO: ROLE_APPROVE, B_EXEC: ROLE_NOTIFY}),
    ("3.1", 3, "اعتماد الالتزامات المالية خارج الميزانية المعتمدة", 4,
     {B_CEO: ROLE_PREPARE, B_EXEC: ROLE_RECOMMEND, B_BOARD: ROLE_APPROVE}),
    ("3.2", 3, "اعتماد الصرف ضمن الميزانية المعتمدة", 4,
     {B_CEO: ROLE_APPROVE}),
)


def synthetic_org() -> OrgIndex:
    """The fictional organisational structure as an :class:`OrgIndex` (deterministic)."""
    idx = OrgIndex(ORG_FILE, 12, title=f"{SYNTHETIC_LABEL}: الهيكل التنظيمي الافتراضي")
    pages = []
    for sector_name, spage, units in _SECTORS:
        idx.sectors.append(Sector(sector_name, spage, tuple(u[0] for u in units)))
        pages.append(spage)
        for unit_name, upage, tasks in units:
            idx.units.append(Unit(unit_name, sector_name, upage, tuple(tasks), heading=f"المهام ({unit_name})"))
            pages.append(upage)
    idx.pages_parsed = tuple(sorted(set(pages)))
    return idx


def synthetic_matrix() -> MatrixIndex:
    """The fictional authority matrix as a :class:`MatrixIndex` (deterministic)."""
    idx = MatrixIndex(MATRIX_FILE, 5, title=f"{SYNTHETIC_LABEL}: مصفوفة الصلاحيات الافتراضية",
                      approval_text="", approval_page=None)
    idx.categories = dict(_CATEGORIES)
    by_page: dict[int, list[str]] = {}
    for number, cat_no, title, page, roles in _ITEMS:
        idx.items.append(Item(number, _CATEGORIES[cat_no], title, page, dict(roles), {}, {},
                              group=_CATEGORIES[cat_no], category_number=cat_no, confidence=CONF_HIGH))
        by_page.setdefault(page, []).append(number)
    bodies = (B_BOARD, B_EXEC, B_AUDIT, B_CEO, B_IA)
    idx.pages = [MatrixPage(p, bodies, (), (), tuple(nums)) for p, nums in sorted(by_page.items())]
    return idx


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def synthetic_reference_index() -> ReferenceIndex:
    """A complete :class:`ReferenceIndex` over the fictional sources, labelled SYNTHETIC everywhere."""
    org = synthetic_org()
    mat = synthetic_matrix()
    sources = {
        "org_structure": SourceStatus("org_structure", ORG_FILE, ORG_FILE, None, _digest(org.to_dict()),
                                      HASH_SYNTHETIC, SYNTHETIC_APPROVAL, SYNTHETIC_EVIDENCE, APPLICABILITY,
                                      org.pages_total),
        "authority_matrix": SourceStatus("authority_matrix", MATRIX_FILE, MATRIX_FILE, None, _digest(mat.to_dict()),
                                         HASH_SYNTHETIC, SYNTHETIC_APPROVAL, SYNTHETIC_EVIDENCE, APPLICABILITY,
                                         mat.pages_total),
    }
    return ReferenceIndex(org, mat, sources, mode=MODE_SYNTHETIC)


def is_synthetic(index: ReferenceIndex | None) -> bool:
    """True when ``index`` is the fixture (by its mode or by any SYNTHETIC source status)."""
    if index is None:
        return False
    if getattr(index, "mode", "") == MODE_SYNTHETIC:
        return True
    return any(s.hash_status == HASH_SYNTHETIC or s.approval_status == SYNTHETIC_APPROVAL
               for s in (index.sources or {}).values())


def real_sources_available(org_text: Path = DEFAULT_ORG_TEXT, matrix_pdf: Path = DEFAULT_MATRIX_PDF,
                           org_pdf: Path = DEFAULT_ORG_PDF) -> bool:
    return Path(org_text).is_file() and Path(matrix_pdf).is_file() and Path(org_pdf).is_file()


def load_reference_index(*, synthetic: str = "never") -> ReferenceIndex:
    """Load the institutional index or the fixture, by explicit policy.

    ``synthetic``:
      ``"never"``      – institutional sources only; raises ``FileNotFoundError`` when they are absent
                         (the command-line default: production never falls back silently);
      ``"if-missing"`` – institutional sources when present, else the fixture (the test default);
      ``"always"``     – the fixture, even when the sources are present.
    """
    if synthetic not in ("never", "if-missing", "always"):
        raise ValueError(f"unknown synthetic policy {synthetic!r}")
    if synthetic == "always":
        return synthetic_reference_index()
    if real_sources_available():
        return ReferenceIndex.load()
    if synthetic == "if-missing":
        return synthetic_reference_index()
    raise FileNotFoundError("institutional reference sources are not on disk (sources/reference); "
                            "pass --synthetic-reference to use the public fixture (never for an institutional issue)")
