"""Workbook-level settings: sheet names, metadata (09.4), dashboard grid (D.10)."""
from __future__ import annotations

from .round_schema import SEP, ordinal

DASHBOARD_SHEET = "لوحة المتابعة التنفيذية"
HELPER_SHEET = "بيانات اللوحة"
LEGACY_PRINT_VIEW_SHEET = "عرض الطباعة"

AUTHOR = "Mohammed Alsaleh"
COMPANY = "صندوق التنمية الثقافي"
APPLICATION = "Microsoft Excel"
PROHIBITED_PROPERTY_VALUES = ("openpyxl", "python-docx", "libreoffice", "microsoft office user", "pyuno")

FUND_NAME = "صندوق التنمية الثقافي"
GCO_NAME = "إدارة الحوكمة والامتثال المؤسسي"
DASHBOARD_TITLE = "لوحة المتابعة التنفيذية للملاحظات"
STEM_SUFFIX = "مرئيات إدارة الحوكمة والامتثال المؤسسي"

# dashboard grid: margin A, twelve equal columns B..M, margin N (D.10)
GRID_FIRST_COL = 2
GRID_COLS = 12
GRID_WIDTH = 13
MARGIN_WIDTH = 2
LAPTOP_WIDTH_BUDGET = 175  # character-width units at 100 % zoom (G-DASH-18)

# defined names used by data validation lists
NAME_ROUNDS = "crms_rounds"
NAME_SCOPES = "crms_scopes"
NAME_READERS = "crms_readers"

SUMMARY_MAX = 75
ACTION_MAX = 75
CALC_ROW_MARGIN = 300  # extra rows of the data sheet covered by lookups (owner-added rows)


def workbook_title(doc_name: str, current_round: int) -> str:
    """Feedback workbook Title property (09.4)."""
    return f"ملاحظات {doc_name}{SEP}حتى الجولة {ordinal(current_round)}"


def file_stem(doc_name: str, current_round: int) -> str:
    """Reader-facing stem (09.1): hyphen-minus separators, Arabic ordinal."""
    bad = '\\/:*?"<>|'
    clean = "".join(ch for ch in doc_name if ch not in bad).strip()
    stem = f"{clean} - {STEM_SUFFIX} - الجولة {ordinal(current_round)}"
    if len(stem) > 120:
        raise ValueError("stem longer than 120 characters (09.1)")
    return stem
