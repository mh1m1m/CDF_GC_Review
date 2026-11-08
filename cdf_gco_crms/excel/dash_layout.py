"""Row plan of the one-sheet dashboard (spec 5; v7.15 draft of 10.4A.5).

The plan depends only on the number of observations N, the number of rounds R and the number of action-list rows
allocated (the current round's rows not مغلقة, at least one). It is computed before the calculation block is
written, because the block's formulas name the selector cells, the action-list rows and the card rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from openpyxl.utils import get_column_letter

from ..config import workbook_settings as W

GRID0 = W.GRID_FIRST_COL            # column B = grid position g1 (the right edge in RTL)
NGRID = W.GRID_COLS                 # 12
CARD_ROWS = 16                      # rows of one observation card
CARD_STRIDE = CARD_ROWS + 1         # plus one spacer row
# card row offsets and heights (pt)
CARD = {"cap": (0, 6), "head": (1, 30), "loc_l": (2, 14), "loc_v": (3, 22), "tag": (4, 18), "obs": (5, 16),
        "obs2": (6, 16), "obs3": (7, 16), "fb": (8, 16), "fb2": (9, 16), "act": (10, 26), "resp": (11, 30),
        "close": (12, 18), "strip_l": (13, 14), "strip_v": (14, 22), "links": (15, 20), "gap": (16, 12)}
CARD_HEIGHT = sum(h for _, h in CARD.values())
HELP_ROWS = 8


def gc(i: int) -> int:
    """Worksheet column of grid index i (0 = g1 = column B)."""
    return GRID0 + i


def L(c: int) -> str:
    return get_column_letter(c)


@dataclass
class Layout:
    N: int
    R: int
    QN: int                                         # action-list rows allocated
    rows: dict[str, int] = field(default_factory=dict)
    heights: dict[int, float] = field(default_factory=dict)
    bands: dict[str, int] = field(default_factory=dict)
    q0: int = 0
    t0: int = 0
    TN: int = 0
    card0: int = 0
    last_row: int = 0

    # selector value cells (merged ranges; the anchor holds the value and the validation)
    @property
    def sel_round(self) -> str:
        return f"${L(gc(0))}${self.rows['sel_v']}"

    @property
    def sel_compare(self) -> str:
        return f"${L(gc(2))}${self.rows['sel_v']}"

    @property
    def sel_scope(self) -> str:
        return f"${L(gc(4))}${self.rows['sel_v']}"

    @property
    def sel_obs(self) -> str:
        return f"${L(gc(7))}${self.rows['sel_v']}"

    @property
    def selector_spans(self) -> list[tuple[int, int]]:
        """(first grid index, last grid index) of the four selector value merges."""
        return [(0, 1), (2, 3), (4, 6), (7, 8)]

    def card_row(self, k: int) -> int:
        return self.card0 + (k - 1) * CARD_STRIDE

    def list_row(self, pos) -> int:
        """Back-link row for an action-list position (the zone D band when not listed or beyond the allocation)."""
        if pos == "" or pos is None or pos > self.QN:
            return self.bands["queue"]
        return self.q0 + pos - 1


def plan(N: int, R: int, QN: int) -> Layout:
    lay = Layout(N, R, max(QN, 1))
    r = 0

    def add(name: str, h: float, n: int = 1) -> int:
        nonlocal r
        first = r + 1
        for i in range(n):
            r += 1
            lay.heights[r] = h
        if name:
            lay.rows[name] = first
        return first

    # zone A
    add("top", 6); add("hline", 18); add("title", 34); add("doc", 22); add("band_bottom", 6)
    add("", 8); add("fact_l", 20); add("fact_v", 30); add("band", 18); add("nav", 22)
    add("sel_l", 15); add("sel_v", 24); add("", 10)
    # zone B
    add("kpi_cap", 5); add("kpi_l", 22); add("kpi_v", 46); add("kpi_f", 26); add("", 12)
    # zone C
    lay.bands["closure"] = add("closure", 26); add("", 6)
    add("narr1", 18); add("narr2", 18); add("", 8)
    add("deck_top", 3); add("panel_title", 24)
    add("g_u1", 30); add("g_u2", 32); add("g_u3", 30)          # upper half: the arcs
    add("g_l1", 40); add("g_l2", 22); add("g_l3", 30)          # lower half: values and captions
    add("deck_bottom", 3); add("", 8)
    add("dist_title", 22); add("dist_bar", 18, 3); add("dist_legend", 22); add("dist_pad", 6); add("", 12)
    # zone D
    lay.bands["queue"] = add("queue", 26); add("q_note", 26); add("q_head", 22)
    lay.q0 = add("q_rows", 32, lay.QN)
    add("q_over", 20); add("", 12)
    # zone E
    lay.bands["rounds"] = add("rounds", 26); add("", 6)
    add("chart_title", 22); add("chart", 16, 12); add("", 8)
    add("m_title", 22); add("m_head", 22); add("m_rows", 22, 5); add("m_note", 15, 2); add("", 12)
    # zone F
    lay.TN = max(N, 1)
    lay.bands["table"] = add("table", 26); add("t_head", 30)
    lay.t0 = add("t_rows", 30, lay.TN); add("", 12)
    # zone G
    lay.bands["help"] = add("help", 26)
    add("help_rows", 30, HELP_ROWS); add("", 12)
    # zone H
    lay.bands["cards"] = add("cards", 26); add("", 6)
    if N:
        lay.card0 = r + 1
        for k in range(1, N + 1):
            for name, (off, h) in CARD.items():
                r += 1
                lay.heights[r] = h
    else:
        lay.card0 = add("cards_empty", 22)
    # footer
    add("foot_note", 16); add("footer", 22)
    lay.last_row = r
    return lay
