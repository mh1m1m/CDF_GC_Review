"""Formula reconciliation (G-DASH-04, -05, -16; TEST 10).

For each view (selected round, scope, observation, comparison round) the
workbook is built *without cached values*, recalculated by LibreOffice, and
every registered formula cell is compared with the value the independent
Python model expects for that view. Because no cached value was present, a
match proves that the spreadsheet engine computed the value.
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from ..excel.formula_registry import equal, norm
from ..excel.workbook_builder import build_workbook
from ..model.entities import DashboardViewState, ReviewState
from . import lo_engine

ERRORS = ("#VALUE!", "#DIV/0!", "#REF!", "#NAME?", "#NULL!", "#NUM!", "#N/A")


@dataclass
class ViewCheck:
    view: str
    formulas: int
    compared: int
    mismatches: list[tuple[str, object, object]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    engine: str = ""
    ok: bool = False
    message: str = ""


def check_view(state: ReviewState, vs: DashboardViewState, workdir: Path) -> ViewCheck:
    workdir.mkdir(parents=True, exist_ok=True)
    tag = f"S{vs.selected_round}_C{vs.compare_round or 0}_{abs(hash((vs.scope, vs.selected_reader))) % 10**6}"
    path = workdir / f"verify_{tag}.xlsx"
    res = build_workbook(state, path, view_state=vs, write_cache=False, logo_path=False)
    expected = res.registry.expected(res.view)
    lo = lo_engine.recalc(path)
    label = (f"S={vs.selected_round}, C={res.view.C}, scope={vs.scope}, "
             f"obs={res.view.reader_label}")
    vc = ViewCheck(label, len(expected), 0, engine=lo.version)
    if not lo.ok:
        vc.message = lo.message
        return vc
    wb = load_workbook(path, data_only=True)
    for (sheet, coord), exp in expected.items():
        actual = wb[sheet][coord].value
        vc.compared += 1
        if isinstance(actual, str) and actual in ERRORS and exp != actual:
            vc.errors.append(f"{sheet}!{coord}={actual}")
        if not equal(exp, actual):
            vc.mismatches.append((f"{sheet}!{coord}", norm(exp), norm(actual)))
    # any error value anywhere on dashboard/helper
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value in ERRORS and f"{ws.title}!{c.coordinate}" not in vc.errors:
                    if (ws.title, c.coordinate) in expected and expected[(ws.title, c.coordinate)] == c.value:
                        continue
                    vc.errors.append(f"{ws.title}!{c.coordinate}={c.value}")
    wb.close()
    vc.ok = not vc.mismatches and not vc.errors
    vc.message = "match" if vc.ok else f"{len(vc.mismatches)} mismatches, {len(vc.errors)} error values"
    return vc


def standard_views(state: ReviewState, an=None) -> list[DashboardViewState]:
    """Views exercised for every verified workbook: every round, every scope at the current round,
    first/last/late-born/reopened observations, a non-adjacent comparison."""
    from ..config import round_schema as S
    R = state.current_round
    obs = state.ordered()
    labels = [f"#{o.reader_no}" for o in obs]
    views = [DashboardViewState(r, S.SCOPE_ALL, labels[0] if labels else None, max(1, r - 1)) for r in range(1, R + 1)]
    for sc in S.SCOPES:
        views.append(DashboardViewState(R, sc, labels[-1] if labels else None, 1))
    late = [o for o in obs if o.birth_round > 1]
    if late and R >= 2:
        views.append(DashboardViewState(late[0].birth_round - 1, S.SCOPE_ALL, f"#{late[0].reader_no}", 1))
        views.append(DashboardViewState(R, S.SCOPE_ACTION, f"#{late[-1].reader_no}", late[-1].birth_round))
    return views
