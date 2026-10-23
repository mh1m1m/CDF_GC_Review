"""Reads a requester workbook (v7.10 or v7.11) into the review-state model.

Version-aware: a v7.10 workbook has the print-view sheet "عرض الطباعة" and no
dashboard; a v7.11 workbook has the dashboard and the hidden helper sheet,
whose document block and long table restore the metadata (round dates,
cover version, owning department, closure basis) that the data sheet does not
carry. Rows are keyed by Internal_ID (column B), never by position.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from ..config import round_schema as S
from ..config import workbook_settings as W
from ..model.entities import (INTERNAL_ID_RE, Document, GText, Observation, ReviewRound,
                              ReviewState, RoundCells, TitleEvidence, plain_text)
from ..rounds.round_parser import RoundSchema, SchemaError, discover
from .safe_open import IngestError, require_safe

TITLE_RE = re.compile(r"^ملاحظات\s+(?P<name>.+?)\s+–\s+حتى الجولة\s+\S+\s*$")


@dataclass
class ParsedWorkbook:
    path: Path
    wb: object
    data_ws: object
    schema: RoundSchema
    state: ReviewState
    kind: str                                   # v7.10 | v7.11
    extra_sheets: list[str] = field(default_factory=list)
    unkeyed_rows: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows: dict[str, int] = field(default_factory=dict)


def find_data_sheet(wb):
    for ws in wb.worksheets:
        if ws.title in (W.DASHBOARD_SHEET, W.HELPER_SHEET, W.LEGACY_PRINT_VIEW_SHEET):
            continue
        a1 = ws.cell(row=1, column=1).value
        b1 = ws.cell(row=1, column=2).value
        if a1 is not None and S.nfc(str(a1)).strip() == S.H_A and str(b1).strip() == S.H_B:
            return ws
    raise SchemaError("NO_DATA_SHEET", "no sheet with the fixed headers of 10.3 was found")


def read_helper(wb) -> dict:
    """Return helper tables by header name: {'meta': {...}, 'rounds': {r: {...}}, 'basis': {(id, r): words}}."""
    out = {"meta": {}, "rounds": {}, "basis": {}, "titles": {}}
    if W.HELPER_SHEET not in wb.sheetnames:
        return out
    ws = wb[W.HELPER_SHEET]
    cols = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=c).value
        if isinstance(v, str) and "." in v:
            cols[v] = c
    def column(name):
        c = cols.get(name)
        if c is None:
            return []
        vals = []
        for r in range(2, ws.max_row + 1):
            vals.append(ws.cell(row=r, column=c).value)
        return vals
    keys, values = column("meta.key"), column("meta.value")
    for k, v in zip(keys, values):
        if k:
            out["meta"][str(k)] = v
    for no, date, ver in zip(column("round.no"), column("round.date"), column("round.version")):
        if isinstance(no, (int, float)):
            out["rounds"][int(no)] = {"date": None if date in (None, "", S.NOT_RECORDED) else str(date),
                                      "version": None if ver in (None, "", S.NOT_RECORDED) else str(ver)}
    words_to_code = {v: k for k, v in S.CLOSURE_BASIS_WORDS.items()}
    for iid, rnd, words in zip(column("long.id"), column("long.round"), column("long.basis_static")):
        if iid and words in words_to_code and isinstance(rnd, (int, float)):
            out["basis"][(str(iid), int(rnd))] = words_to_code[words]
    for iid, title, status, by, on, ref in zip(column("obs.id"), column("obs.title"), column("obs.title_status"),
                                               column("obs.title_by"), column("obs.title_on"), column("obs.title_ref")):
        if iid and status in S.TITLE_STATES and status != S.TITLE_NONE:
            out["titles"][str(iid)] = {"title": None if title in (None, "") else str(title), "status": status,
                                       "reviewer": None if by in (None, "") else str(by),
                                       "date": None if on in (None, "") else str(on)[:10],
                                       "decision_ref": None if ref in (None, "") else str(ref)}
    return out


def _doc_from(wb, helper_meta: dict, ids: list[str], overrides: dict) -> Document:
    name = overrides.get("name") or helper_meta.get("doc_name")
    if not name:
        title = wb.properties.title or ""
        m = TITLE_RE.match(S.nfc(title))
        if m:
            name = m.group("name")
    if not name:
        raise SchemaError("NO_DOCUMENT_NAME", "document name not found; pass it explicitly (02.4)")
    codes = {INTERNAL_ID_RE.match(i).group("doc") for i in ids if INTERNAL_ID_RE.match(i)}
    code = overrides.get("code") or (codes.pop() if len(codes) == 1 else None)
    if not code:
        raise SchemaError("NO_DOCUMENT_CODE", "document code not derivable from Internal_IDs")
    def pick(key):
        v = overrides.get(key)
        if v is None:
            v = helper_meta.get({"cover_version": "cover_version",
                                 "owning_department": "owning_department"}[key])
        return None if v in (None, "", S.NOT_RECORDED) else str(v)
    is_demo = overrides.get("is_demo")
    if is_demo is None:
        is_demo = str(helper_meta.get("is_demo", "")).lower() in ("1", "true", "yes")
    return Document(name=str(name), code=str(code), cover_version=pick("cover_version"),
                    owning_department=pick("owning_department"), is_demo=bool(is_demo))


def parse_workbook(path, *, overrides: dict | None = None, round_meta: dict | None = None) -> ParsedWorkbook:
    overrides = overrides or {}
    path = Path(path)
    try:
        require_safe(path, "xlsx")                         # fail closed before any part is parsed (15A.6)
    except IngestError as e:
        raise SchemaError("UNSAFE_INPUT", str(e)) from e
    wb = load_workbook(path, rich_text=True)
    ws = find_data_sheet(wb)
    schema = discover(ws)
    helper = read_helper(wb)
    kind = "v7.11" if W.DASHBOARD_SHEET in wb.sheetnames else "v7.10"
    extra = [s for s in wb.sheetnames if s not in (ws.title, W.DASHBOARD_SHEET, W.HELPER_SHEET,
                                                     W.LEGACY_PRINT_VIEW_SHEET)]
    obs: list[Observation] = []
    unkeyed: list[int] = []
    warnings = list(schema.warnings)
    seen: set[str] = set()
    rows: dict[str, int] = {}
    formula_cells: list[str] = []
    for row in range(2, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=row, column=c)
            if cell.data_type == "f" or (isinstance(cell.value, str) and cell.value.startswith("=")):
                formula_cells.append(cell.coordinate)
                cell.value = plain_text(cell.value)      # kept literally as text, never evaluated (15A.6)
        iid = ws.cell(row=row, column=2).value
        rest = [ws.cell(row=row, column=c).value for c in (1, 3, 4, 5)]
        if iid is None or str(iid).strip() == "":
            if any(v not in (None, "") for v in rest):
                unkeyed.append(row)
            continue
        iid = str(iid).strip()
        if iid in seen:
            raise SchemaError("DUPLICATE_ID", f"Internal_ID {iid} appears twice")
        seen.add(iid)
        rows[iid] = row
        cells: dict[int, RoundCells] = {}
        birth = None
        for r in schema.rounds:
            b = schema.blocks[r]
            closure = ws.cell(row=row, column=b[S.ROLE_CLOSURE]).value
            rc = RoundCells(
                closure=closure,
                feedback=ws.cell(row=row, column=b[S.ROLE_FEEDBACK]).value if S.ROLE_FEEDBACK in b else None,
                response=ws.cell(row=row, column=b[S.ROLE_RESPONSE]).value,
                impl=ws.cell(row=row, column=b[S.ROLE_IMPL]).value,
            )
            cells[r] = rc
            if birth is None and plain_text(closure).strip() not in ("", S.NOT_RAISED):
                birth = r
        if birth is None:
            raise SchemaError("NO_BIRTH_ROUND", f"{iid}: no round carries a closure value")
        m = INTERNAL_ID_RE.match(iid)
        if m and int(m.group("round")) != birth:
            warnings.append(f"{iid}: Internal_ID round R{m.group('round')} differs from the first "
                            f"assessed round {birth}")
        reader = ws.cell(row=row, column=1).value
        reader = f"{int(reader):02d}" if isinstance(reader, (int, float)) else str(reader).strip()
        o = Observation(internal_id=iid, reader_no=reader, birth_round=birth,
                        location=ws.cell(row=row, column=3).value,
                        quote=ws.cell(row=row, column=4).value,
                        comment=GText.from_cell_value(ws.cell(row=row, column=5).value) or "",
                        cells=cells)
        for (bid, br), code in helper["basis"].items():
            if bid == iid:
                o.closure_basis[br] = code
        t = helper["titles"].get(iid)
        if t:
            ev = TitleEvidence(t["reviewer"] or "", t["date"] or "", t["decision_ref"] or "")
            if t["status"] in S.TITLE_SHOWN_STATES and not (ev.complete and t["title"]):
                warnings.append(f"{iid}: title marked {t['status']} without complete approval evidence; "
                                "demoted to PROPOSED (19A.9)")
                o.title, o.title_status, o.title_evidence = t["title"], S.TITLE_PROPOSED, None
            else:
                o.title, o.title_status = t["title"], t["status"]
                o.title_evidence = ev if ev.complete else None
                o.__post_init__()
        obs.append(o)

    if formula_cells:
        warnings.append(f"FORMULA_IN_DATA: {len(formula_cells)} data cell(s) carried a formula and were read as literal "
                        f"text ({', '.join(formula_cells[:8])}{'…' if len(formula_cells) > 8 else ''})")
    rounds = []
    for r in schema.rounds:
        meta = (round_meta or {}).get(r) or helper["rounds"].get(r) or {}
        rounds.append(ReviewRound(r, meta.get("date"), meta.get("version")))
    doc = _doc_from(wb, helper["meta"], [o.internal_id for o in obs], overrides)
    state = ReviewState(document=doc, rounds=rounds, observations=obs)
    return ParsedWorkbook(path=path, wb=wb, data_ws=ws, schema=schema, state=state, kind=kind,
                          extra_sheets=extra, unkeyed_rows=unkeyed, warnings=warnings, rows=rows)
