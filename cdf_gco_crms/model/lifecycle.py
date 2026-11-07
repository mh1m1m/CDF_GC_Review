"""Closure semantics and derived indicators (protocol 10.4A.7, 17.8, Annex D.10).

Pure functions of the official values. These are the *independent* Python
definitions against which the Excel formulas are verified; they never write a
closure value (17.8).
"""
from __future__ import annotations

from ..config import round_schema as S


def is_closed(v: str) -> bool:
    return v == S.CLOSED


def exists(birth: int, r: int) -> bool:
    return r >= birth


def prev_value(values: dict[int, str], birth: int, r: int) -> str:
    """Value of round r-1, '' when r is round 1 or the round of birth."""
    if r <= 1 or r <= birth:
        return ""
    return values.get(r - 1, "")


def closed_event(values: dict[int, str], birth: int, r: int) -> bool:
    p = prev_value(values, birth, r)
    return values.get(r) == S.CLOSED and p != "" and p != S.CLOSED


def reopen_event(values: dict[int, str], birth: int, r: int) -> bool:
    p = prev_value(values, birth, r)
    v = values.get(r, "")
    return p == S.CLOSED and v not in ("", S.CLOSED)


def ever_closed_before(values: dict[int, str], birth: int, r: int) -> bool:
    return any(values.get(k) == S.CLOSED for k in range(birth, r))


def reopened_state(values: dict[int, str], birth: int, r: int) -> bool:
    v = values.get(r, "")
    return v not in ("", S.CLOSED) and ever_closed_before(values, birth, r)


def stalled(values: dict[int, str], birth: int, r: int) -> bool:
    """SC-50 with the birth-round exclusion of 10.4A.7."""
    if r - 1 <= birth:
        return False
    return values.get(r) in S.NON_CLOSED_TIER0 and values.get(r - 1) in S.NON_CLOSED_TIER0


def change_label(values: dict[int, str], birth: int, r: int) -> str:
    v = values.get(r, "")
    if v == "":
        return ""
    if r == birth:
        return S.CHANGE_NEW
    p = prev_value(values, birth, r)
    if p == S.CLOSED:
        return S.CHANGE_STAYED_CLOSED if v == S.CLOSED else S.CHANGE_REOPENED
    if v == S.CLOSED:
        return S.CHANGE_CLOSED
    if p == v:
        return S.CHANGE_NO_PROGRESS
    if v == S.CLOSED_COND:
        return S.CHANGE_COND            # p in tier 0
    if p == S.CLOSED_COND:
        return S.CHANGE_COND_REGRESS    # v in tier 0
    return S.CHANGE_SHIFT               # both tier 0, different


def prev_display(values: dict[int, str], birth: int, r: int) -> str:
    if r == 1 or r == birth:
        return S.PREV_NA
    return values.get(r - 1, "")


def priority(values: dict[int, str], birth: int, r: int) -> int | None:
    """Workflow order of the action queue (D.10); None for closed or non-existing rows."""
    v = values.get(r, "")
    if v in ("", S.CLOSED):
        return None
    if reopened_state(values, birth, r):
        return 1
    if stalled(values, birth, r):
        return 2
    if v == S.CLOSED_COND:
        return 3
    if v == S.REQUIRES_EDIT:
        return 4
    return 5


def reason(values: dict[int, str], birth: int, r: int) -> str:
    p = priority(values, birth, r)
    if p is None:
        return ""
    if p == 1:
        return S.REASON_REOPENED
    if p == 2:
        return S.REASON_STALLED
    if p == 3:
        return S.REASON_COND
    if p == 4:
        return S.REASON_EDIT
    return S.REASON_AWAIT_FIRST if r == birth else S.REASON_OPEN


def latest_closure_round(values: dict[int, str], birth: int, r: int) -> int | None:
    """Round in which the current closure streak began (10.2: latest closure)."""
    if values.get(r) != S.CLOSED:
        return None
    k = r
    while k - 1 >= birth and values.get(k - 1) == S.CLOSED:
        k -= 1
    return k


def readiness(counts: dict[str, int], total: int, invalid: int) -> str:
    if total == 0:
        return S.READY_EMPTY
    if invalid > 0:
        return S.READY_NO_DATA
    if counts.get(S.OPEN, 0) + counts.get(S.REQUIRES_EDIT, 0) > 0:
        return S.READY_ACTION
    if counts.get(S.CLOSED_COND, 0) > 0:
        return S.READY_COND
    return S.READY_ALL_CLOSED
