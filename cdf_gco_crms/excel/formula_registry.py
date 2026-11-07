"""Registry of formula cells and their independently calculated expected values.

Every formula the builder writes is registered with the value it must take:
a constant (state-independent cells) or a function of the analytics view.
The registry drives (a) the cached values written into the file for the
default view and (b) the comparison with a spreadsheet engine's results for
every view tested (G-DASH-04, -05, -16).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

NA = "#N/A"


@dataclass
class Entry:
    sheet: str
    coord: str
    formula: str
    expected: Any            # constant or callable(view) -> value


class Registry:
    def __init__(self):
        self.entries: dict[tuple[str, str], Entry] = {}

    def put(self, ws, coord: str, formula: str, expected, **style):
        if not formula.startswith("="):
            formula = "=" + formula
        cell = ws[coord]
        cell.value = formula
        for k, v in style.items():
            setattr(cell, k, v)
        self.entries[(ws.title, coord)] = Entry(ws.title, coord, formula, expected)
        return cell

    def expected(self, view) -> dict[tuple[str, str], Any]:
        out = {}
        for key, e in self.entries.items():
            out[key] = e.expected(view) if callable(e.expected) else e.expected
        return out

    def formulas(self) -> dict[tuple[str, str], str]:
        return {k: e.formula for k, e in self.entries.items()}


def norm(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def equal(expected, actual, tol: float = 1e-9) -> bool:
    e, a = norm(expected), norm(actual)
    if isinstance(e, (int, float)) and isinstance(a, (int, float)):
        return math.isclose(float(e), float(a), rel_tol=tol, abs_tol=tol)
    if isinstance(e, (int, float)) and isinstance(a, str):
        try:
            return math.isclose(float(e), float(a), rel_tol=tol, abs_tol=tol)
        except ValueError:
            return False
    return str(e) == str(a)
