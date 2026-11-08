"""Independent Python calculation of every dashboard figure (10.4A.7, D.10, G-DASH-04/05/16).

This module never reads the dashboard or its formulas. It computes, from the
review state alone, what each helper and dashboard cell must show for a given
view (selected round, scope, selected observation, comparison round). The
build writes these values as the cached results of the default view, and the
verifier compares a spreadsheet engine's recalculation against them for every
view tested.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from ..config import round_schema as S
from ..model import lifecycle as L
from ..model.entities import ReviewState, plain_text
from ..observations import text_derivation as TD

STATUS4 = (S.CLOSED, S.CLOSED_COND, S.REQUIRES_EDIT, S.OPEN)
DETAIL_CUT = 300


def fixed1(x: float) -> str:
    """Excel FIXED(x,1) without thousands separator for |x| < 1000."""
    return str(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fixed0(x: float) -> str:
    """Excel FIXED(x,0) for 0 <= x < 1000."""
    return str(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


MINUS = "−"                 # minus sign of the delta chips (spec 4.3), not a dash
NO_CHANGE = "دون تغيير"
POINTS = "نقطة"
KPI_KEYS = ("issued", "closed", "cond", "req", "open", "rate")
KPI_FAVOUR = {"issued": 0, "closed": 1, "cond": 0, "req": -1, "open": -1, "rate": 1}
NO_PREVIOUS = "لا توجد جولة سابقة"
PREVIOUS = "في الجولة السابقة: "
NEEDLE = 1.4                     # width of the needle slice (spec 7.1)
CARD_TAG = "ملخص آلي غير معتمد"
FULL_TEXT = "النص الكامل في ورقة الملاحظات"
CARD_CUT = 300                   # observation, feedback and action on a card (10.4A.11)


def list_title(a: "ObsA") -> str:
    """Title in the action list and the table: the approved title, else the tagged mechanical summary (10.4A.16)."""
    if a.title_status in S.TITLE_SHOWN_STATES and a.title.strip():
        return a.title_disp
    return f"{CARD_TAG}: {a.summary}" if a.summary else a.title_disp


def card_comment(text: str) -> str:
    """The observation as issued, cut at 300 characters on a word boundary, pointing to the full text when cut."""
    t = TD.cut(text, CARD_CUT)
    return t + f" ({FULL_TEXT})" if t.endswith("…") else t


@dataclass
class LongRow:
    k: int
    r: int
    exists: int
    value: str
    prev: str
    closed: int
    closed_event: int
    ecb: int
    ever: int
    reopen_event: int
    reopen_state: int
    stalled: int
    change: str
    priority: int | str
    reason: str
    action: str
    feedback: str
    cur_loc: str
    basis: str
    resp: str
    resp_filled: int
    lfr: int
    impl: str
    impl_filled: int
    lfi: int
    lcr: int | str
    invalid: int


@dataclass
class ObsA:
    k: int
    iid: str
    reader: str
    birth: int
    row: int
    location: str
    comment: str
    summary: str
    title: str = ""              # recorded title text ('' when none)
    title_status: str = S.TITLE_NONE
    title_disp: str = ""         # what the dashboard shows: approved title or the neutral "الملاحظة #NN" fallback
    title_by: str = ""
    title_on: str = ""
    title_ref: str = ""
    long: dict[int, LongRow] = field(default_factory=dict)

    @property
    def reader_label(self) -> str:
        return f"#{self.reader}"


@dataclass
class TrendRow:
    r: int
    issued: int
    new: int
    closed: int
    cond: int
    req: int
    open: int
    invalid: int
    rate: float | str
    closed_event: int
    reopen_event: int
    stalled: int
    reopen_state: int
    ever: int
    impl: float | str = ""        # implementation rate (closed + conditional) / issued; derived, display only (17.8)


class Analytics:
    def __init__(self, state: ReviewState, rows: dict[str, int], *, round_cols: dict[int, dict[str, int]],
                 data_sheet: str):
        self.state = state
        self.R = state.current_round
        self.data_sheet = data_sheet
        self.round_cols = round_cols
        self.obs: list[ObsA] = []
        for k, o in enumerate(state.ordered(), start=1):
            a = ObsA(k=k, iid=o.internal_id, reader=o.reader_no, birth=o.birth_round,
                     row=rows[o.internal_id], location=plain_text(o.location),
                     comment=plain_text(o.comment), summary=TD.summary(plain_text(o.comment)))
            a.title = o.title or ""
            a.title_status = o.title_status
            a.title_disp = TD.display_title(o.title, o.title_status, o.reader_no)
            if o.title_evidence is not None:
                a.title_by, a.title_on, a.title_ref = o.title_evidence.reviewer, o.title_evidence.date, o.title_evidence.decision_ref
            self._fill_long(a, o)
            self.obs.append(a)
        self.trend = {r: self._trend(r) for r in range(1, self.R + 1)}

    # ---------------------------------------------------------------- long table
    def _fill_long(self, a: ObsA, o):
        R = self.R
        values = {r: (plain_text(o.cells[r].closure) if r >= o.birth_round and r in o.cells else "")
                  for r in range(1, R + 1)}
        fbs = {r: (plain_text(o.cells[r].feedback) if r >= 2 and r >= o.birth_round and r in o.cells else "")
               for r in range(1, R + 1)}
        lfr = lfi = 0
        lcr_prev: int | str = ""
        ecb = 0
        for r in range(1, R + 1):
            ex = 1 if r >= o.birth_round else 0
            v = values[r] if ex else ""
            prev = "" if (r == 1 or r <= o.birth_round) else values[r - 1]
            closed = 1 if v == S.CLOSED else 0
            closed_event = 1 if (v == S.CLOSED and prev not in ("", S.CLOSED)) else 0
            if r <= o.birth_round:
                ecb = 0
            else:
                ecb = 1 if (ecb == 1 or values[r - 1] == S.CLOSED) else 0
            ever = 1 if (ecb or closed) else 0
            reopen_event = 1 if (prev == S.CLOSED and v not in ("", S.CLOSED)) else 0
            reopen_state = 1 if (v not in ("", S.CLOSED) and ecb == 1) else 0
            stalled = 1 if (r - 1 > o.birth_round and v in S.NON_CLOSED_TIER0 and prev in S.NON_CLOSED_TIER0) else 0
            vals_for_lc = {k: values[k] for k in range(o.birth_round, R + 1)}
            change = L.change_label(vals_for_lc, o.birth_round, r) if ex else ""
            pr = L.priority(vals_for_lc, o.birth_round, r) if ex else None
            reason = L.reason(vals_for_lc, o.birth_round, r) if ex else ""
            action = (TD.required_action(v, fbs[r], r, o.birth_round,
                                         summary=getattr(o, "action_summary", None) if r == R else None)
                      if ex else "")
            cur_loc = TD.current_location(plain_text(o.location), fbs, o.birth_round, r) if ex else ""
            basis = S.CLOSURE_BASIS_WORDS.get(o.closure_basis.get(r, ""), "") if ex else ""
            resp = plain_text(o.cells[r].response) if (ex and r in o.cells) else ""
            impl = plain_text(o.cells[r].impl) if (ex and r in o.cells) else ""
            resp_filled = 1 if (ex and resp != "" and resp != S.PH_TEXT
                                and not resp.startswith(S.CLOSED_GUIDE_PREFIX)) else 0
            impl_filled = 1 if (ex and impl in S.OWNER_IMPL_VALUES) else 0
            lfr = r if resp_filled else (lfr if r > 1 else 0)
            lfi = r if impl_filled else (lfi if r > 1 else 0)
            if v == S.CLOSED:
                lcr = lcr_prev if (r > 1 and prev == S.CLOSED) else r
            else:
                lcr = ""
            lcr_prev = lcr
            invalid = 1 if (ex and v not in STATUS4) else 0
            a.long[r] = LongRow(a.k, r, ex, v, prev, closed, closed_event, ecb, ever, reopen_event,
                                reopen_state, stalled, change, pr if pr is not None else "", reason, action,
                                fbs[r] if ex else "", cur_loc, basis, resp, resp_filled, lfr, impl,
                                impl_filled, lfi, lcr, invalid)

    def _trend(self, r: int) -> TrendRow:
        rows = [a.long[r] for a in self.obs]
        issued = sum(x.exists for x in rows)
        cnt = {s: sum(1 for x in rows if x.exists and x.value == s) for s in STATUS4}
        return TrendRow(
            r=r, issued=issued, new=sum(1 for a in self.obs if a.birth == r),
            closed=cnt[S.CLOSED], cond=cnt[S.CLOSED_COND], req=cnt[S.REQUIRES_EDIT], open=cnt[S.OPEN],
            invalid=sum(x.invalid for x in rows),
            rate=(cnt[S.CLOSED] / issued) if issued else "",
            closed_event=sum(x.closed_event for x in rows), reopen_event=sum(x.reopen_event for x in rows),
            stalled=sum(x.stalled for x in rows), reopen_state=sum(x.reopen_state for x in rows),
            ever=sum(x.ever for x in rows),
            impl=((cnt[S.CLOSED] + cnt[S.CLOSED_COND]) / issued) if issued else "")

    # ---------------------------------------------------------------- per view
    def view(self, S_: int | None = None, scope: str = S.SCOPE_ALL, reader_label: str | None = None,
             C: int | None = None) -> "View":
        return View(self, S_ or self.R, scope, reader_label, C)

    def default_reader_label(self) -> str:
        v = self.view()
        return v.queue[0].reader_label if v.queue else (self.obs[0].reader_label if self.obs else "")


class View:
    def __init__(self, an: Analytics, S_: int, scope: str, reader_label: str | None, C: int | None):
        self.an = an
        self.S = S_
        self.R = an.R
        self.scope = scope
        self.C = C if C is not None else max(1, S_ - 1)
        self.t = an.trend.get(S_)
        obs = an.obs
        # per-observation state
        self.exists = {a.k: a.long[S_].exists for a in obs}
        self.v = {a.k: a.long[S_].value for a in obs}
        self.vC = {a.k: a.long[self.C].value for a in obs}
        self.prev_disp = {}
        for a in obs:
            if not a.long[S_].exists:
                self.prev_disp[a.k] = ""
            elif S_ == 1 or S_ == a.birth:
                self.prev_disp[a.k] = S.PREV_NA
            else:
                self.prev_disp[a.k] = a.long[S_ - 1].value
        self.include = {a.k: self._include(a) for a in obs}
        rank = 0
        self.rank: dict[int, int | str] = {}
        for a in obs:
            if self.include[a.k]:
                rank += 1
                self.rank[a.k] = rank
            else:
                self.rank[a.k] = ""
        self.table = [a for a in obs if self.include[a.k]]
        keyed = [(a.long[S_].priority * 10000 + a.k, a) for a in obs
                 if a.long[S_].priority != ""]
        keyed.sort(key=lambda t: t[0])
        self.qkey = {a.k: (a.long[S_].priority * 10000 + a.k if a.long[S_].priority != "" else "") for a in obs}
        self.queue = [a for _, a in keyed]
        labels = [a.reader_label for a in obs]
        if reader_label in labels:
            self.sel = obs[labels.index(reader_label)]
            self.reader_label = reader_label
        else:
            self.sel = obs[0] if obs else None
            self.reader_label = reader_label
        self.k = self.sel.k if self.sel else 1

    def _include(self, a: ObsA) -> int:
        x = a.long[self.S]
        if not x.exists:
            return 0
        sc = self.scope
        if sc == S.SCOPE_ALL:
            return 1
        if sc == S.SCOPE_ACTION:
            return 1 if x.value != S.CLOSED else 0
        if sc == S.SCOPE_STALLED:
            return x.stalled
        if sc == S.SCOPE_REOPENED:
            return x.reopen_state
        if sc == S.SCOPE_NEW:
            return 1 if a.birth == self.S else 0
        return 1 if x.value == sc else 0

    # ------------------------------------------------------------- dashboard text
    def label(self, r: int | None = None) -> str:
        return S.round_label(r or self.S)

    def historical_band(self) -> str:
        if self.S == self.R:
            return ""
        return (f"تعرض اللوحة {S.round_label(self.S)} (جولة سابقة)، "
                f"والجولة الحالية هي {S.round_label(self.R)}.")

    def narrative1(self) -> str:
        t = self.t
        if t.issued == 0:
            return "لا توجد ملاحظات مسجلة حتى الآن."
        if self.S == 1:
            return (f"حتى {self.label()}: عدد الملاحظات الصادرة {t.issued}، "
                    "وجميعها بانتظار الإفادة الأولى من الإدارة صاحبة الطلب.")
        return (f"حتى {self.label()}: مغلقة {t.closed} من أصل {t.issued} ({fixed1(t.rate * 100)}%)؛ "
                f"يتطلب تعديل {t.req}؛ مغلقة بشرط {t.cond}؛ مفتوحة {t.open}.")

    def narrative2(self) -> str:
        t = self.t
        if self.S == 1 or t.issued == 0:
            return ""
        return (f"خلال {self.label()}: أُغلقت {t.closed_event}، وأُعيد فتح {t.reopen_event}، "
                f"وأُضيفت {t.new}، ومتعثرة {t.stalled}.")

    def readiness(self) -> str:
        t = self.t
        counts = {S.CLOSED: t.closed, S.CLOSED_COND: t.cond, S.REQUIRES_EDIT: t.req, S.OPEN: t.open}
        return L.readiness(counts, t.issued, t.invalid)

    def readiness_note(self) -> str:
        return S.READY_NOTE if self.readiness() == S.READY_ALL_CLOSED else ""

    def readiness_tile(self) -> str:
        r = self.readiness()
        return f"{r} {S.READY_NOTE}" if r == S.READY_ALL_CLOSED else r

    # ------------------------------------------------------------- KPI deltas and chips (spec 4.3, zone B)
    def kpi(self, key: str) -> dict:
        cur = getattr(self.t, key)
        if self.S == 1:
            return {"cur": cur, "prev": "", "delta": "", "chip": "", "dir": 0, "prevtxt": NO_PREVIOUS}
        prev = getattr(self.an.trend[self.S - 1], key)
        if key == "rate":
            if prev == "" or cur == "":
                delta, chip = "", ""
            else:
                delta = (cur - prev) * 100
                f = fixed1(abs(delta))
                chip = NO_CHANGE if f == "0.0" else f"{'+' if delta > 0 else MINUS}{f} {POINTS}"
            prevtxt = "" if prev == "" else f"{PREVIOUS}{fixed1(prev * 100)}%"
        else:
            delta = cur - prev
            chip = NO_CHANGE if delta == 0 else f"{'+' if delta > 0 else MINUS}{abs(delta)}"
            prevtxt = f"{PREVIOUS}{prev}"
        if delta == "" or chip == NO_CHANGE:
            d = 0
        else:
            d = (1 if delta > 0 else -1) * KPI_FAVOUR[key]
        return {"cur": cur, "prev": prev, "delta": delta, "chip": chip, "dir": d, "prevtxt": prevtxt}

    # ------------------------------------------------------------- gauges (spec 7.1, 7.2)
    def gauge(self) -> dict:
        t = self.t
        impl = (t.closed + t.cond) / t.issued if t.issued else 0
        rate = t.closed / t.issued if t.issued else 0
        sus = t.closed / t.ever if t.ever else 0

        def needle(v):
            return [100 * v, NEEDLE, 200 - 100 * v - NEEDLE]

        def arc(v):
            return [100 * v, 100 - 100 * v, 100]
        return {"impl": impl, "rate": rate, "sus": sus,
                "comp_arc": [t.closed, t.cond, t.req, t.open, t.issued], "comp_needle": needle(impl),
                "rate_arc": arc(rate), "rate_needle": needle(rate), "sus_arc": arc(sus), "sus_needle": needle(sus)}

    def legend(self) -> list[str]:
        t = self.t
        out = []
        for value, n in ((S.CLOSED, t.closed), (S.CLOSED_COND, t.cond), (S.REQUIRES_EDIT, t.req), (S.OPEN, t.open)):
            out.append(f"{value} {n}" if not t.issued else f"{value} {n} ({fixed0(100 * n / t.issued)}%)")
        return out

    # ------------------------------------------------------------- action list position (zone D back links)
    def queue_pos(self, k: int):
        qk = self.qkey[k]
        if qk == "":
            return ""
        return sum(1 for x in self.qkey.values() if x != "" and x <= qk)

    def prev_count(self, attr: str):
        if self.S == 1:
            return ""
        return getattr(self.an.trend[self.S - 1], attr)

    def completeness(self) -> tuple[int, int]:
        """(filled, needed) for the *current* round R (Innovation 36)."""
        needed = filled = 0
        for a in self.an.obs:
            x = a.long[self.R]
            if x.exists and x.value != S.CLOSED:
                needed += 1
                filled += x.resp_filled
        return filled, needed

    def matrix(self) -> dict[tuple[int, int], int]:
        """(code at C, code at S) -> count; code 0 = not raised, 1..4 = STATUS4, 9 = invalid."""
        out: dict[tuple[int, int], int] = {}
        for a in self.an.obs:
            cs = self._code(self.v[a.k])
            cc = self._code(self.vC[a.k])
            out[(cc, cs)] = out.get((cc, cs), 0) + 1
        return out

    @staticmethod
    def _code(v: str) -> int:
        if v == "":
            return 0
        return STATUS4.index(v) + 1 if v in STATUS4 else 9

    # ---------------------------------------------------------------- detail panel
    def detail(self) -> dict[str, str]:
        a = self.sel
        if a is None:
            return {}
        x = a.long[self.S]
        R = self.R
        if not x.exists:
            return {"head": f"{a.reader_label}{S.SEP}{S.NOT_RAISED}", "loc": "", "cur_loc": "", "comment": "",
                    "feedback": "", "action": "", "resp": "", "impl": "", "closure": ""}
        fb = "لا توجد مرئيات متابعة في الجولة الأولى." if self.S == 1 else TD.cut(x.feedback, DETAIL_CUT)
        resp = S.NO_RESPONSE if x.lfr == 0 else f"{a.long[x.lfr].resp} ({S.round_label(x.lfr)})"
        impl = S.NO_RESPONSE if x.lfi == 0 else f"{a.long[x.lfi].impl} ({S.round_label(x.lfi)})"
        if x.lcr == "":
            closure = "غير مغلقة في الجولة المعروضة"
        else:
            basis = a.long[x.lcr].basis or S.NOT_RECORDED
            closure = f"أُغلقت في {S.round_label(x.lcr)}{S.SEP}أساس الإغلاق: {basis}"
        return {"head": f"{a.reader_label}{S.SEP}{x.value}", "loc": a.location, "cur_loc": x.cur_loc,
                "comment": TD.cut(a.comment, DETAIL_CUT), "feedback": fb, "action": x.action, "resp": resp, "impl": impl,
                "closure": closure}

    def card(self, a: ObsA) -> dict:
        """Fields of observation a's card in the selected round (spec 5, zone H)."""
        x = a.long[self.S]
        if not x.exists:
            return {"ex": 0, "pill": S.NOT_RAISED, "change": ""}
        d = {"ex": 1, "pill": x.value, "change": x.change, "loc": a.location, "cur_loc": x.cur_loc,
             "comment": card_comment(a.comment), "summary": a.summary,
             "feedback": "لا توجد مرئيات متابعة في الجولة الأولى." if self.S == 1 else TD.cut(x.feedback, CARD_CUT),
             "action": x.action}
        d["resp"] = S.NO_RESPONSE if x.lfr == 0 else f"{a.long[x.lfr].resp} ({S.round_label(x.lfr)})"
        d["impl"] = S.NO_RESPONSE if x.lfi == 0 else f"{a.long[x.lfi].impl} ({S.round_label(x.lfi)})"
        if x.lcr == "":
            d["closure"] = "غير مغلقة في الجولة المعروضة"
        else:
            basis = a.long[x.lcr].basis or S.NOT_RECORDED
            d["closure"] = f"أُغلقت في {S.round_label(x.lcr)}{S.SEP}أساس الإغلاق: {basis}"
        return d

    def strip(self, a: ObsA, j: int) -> tuple[str, str]:
        """(round label, pill) of the card's timeline strip for round j (rounds after S blank)."""
        if not a.long[self.S].exists or j > self.S:
            return "", ""
        if j < a.birth:
            return S.round_label(j), "لم تكن مطروحة"
        return S.round_label(j), a.long[j].value

    def strip_start(self) -> int:
        return max(1, self.S - 10)

    def timeline(self, r: int) -> tuple[str, str, str, str]:
        """(status, change, owner impl claim, GCO feedback summary) for round r of the selected observation."""
        a = self.sel
        if a is None or r > self.S:
            return "", "", "", ""
        if r < a.birth:
            return S.NOT_RAISED, "", "", ""
        x = a.long[r]
        impl = x.impl if x.impl_filled else ""
        fb = TD.cut(x.feedback, 70) if r >= 2 else ""
        return x.value, x.change, impl, fb
