"""Round 1 build and round-n append on the review-state model (10.2, 10.3, 11.2, 11.3).

Append is idempotent (10.3): requesting a round that already exists changes
nothing when the stored block equals the request and is a build error
otherwise. Every observation open at the start of round n needs an
assessment; a row already closed is carried forward with the prior-closure
value, unless an assessment reopens it (16.1).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from ..config import round_schema as S
from ..model import lifecycle as L
from ..model.entities import (Document, GText, Observation, ReviewRound, ReviewState,
                              RoundAssessment, RoundCells, TitleEvidence, plain_text)
from .round_parser import SchemaError


@dataclass
class NewObservation:
    location: str
    quote: str
    comment: GText | str
    reason: str | None = None          # required for observations born after round 1 (10.2)
    title: str | None = None           # proposed title (10.4A.16); never shown as approved without a decision


@dataclass
class RoundInput:
    round: int
    date: str | None = None
    document_version: str | None = None
    assessments: list[RoundAssessment] = field(default_factory=list)
    new_observations: list[NewObservation] = field(default_factory=list)


@dataclass
class AppendReport:
    round: int
    action: str                         # APPENDED | NO_OP
    carried_closed: list[str] = field(default_factory=list)
    assessed: list[str] = field(default_factory=list)
    reopened: list[str] = field(default_factory=list)
    new_ids: list[str] = field(default_factory=list)


def _as_gtext(v) -> GText:
    return v if isinstance(v, GText) else GText.plain(str(v))


def reader_no(n: int) -> str:
    return f"{n:02d}"


def build_round1(document: Document, observations: list[NewObservation], *,
                 date: str | None = None, document_version: str | None = None) -> ReviewState:
    obs: list[Observation] = []
    for i, n in enumerate(observations, start=1):
        o = Observation(internal_id=f"GCO-{document.code}-R1-{i:03d}", reader_no=reader_no(i),
                        birth_round=1, location=n.location, quote=n.quote,
                        comment=_as_gtext(n.comment))
        o.cells[1] = RoundCells(closure=S.OPEN, feedback=None, response=S.PH_TEXT, impl=S.PH_STATUS)
        if n.title and n.title.strip():
            o.title, o.title_status = " ".join(n.title.split()), S.TITLE_PROPOSED
        obs.append(o)
    if document_version:
        document.cover_version = document_version
    return ReviewState(document=document,
                       rounds=[ReviewRound(1, date, document_version or document.cover_version)],
                       observations=obs)


def _values(o: Observation, upto: int) -> dict[int, str]:
    return {r: o.value(r) for r in range(o.birth_round, upto + 1)}


def _same_block(o: Observation, r: int, a: RoundAssessment) -> bool:
    c = o.cells.get(r)
    if c is None:
        return False
    return (plain_text(c.closure).strip() == a.status
            and plain_text(c.feedback).strip() == plain_text(a.feedback).strip())


def apply_round(state: ReviewState, rin: RoundInput) -> tuple[ReviewState, AppendReport]:
    n = rin.round
    R = state.current_round
    by_id = state.by_id()
    for a in rin.assessments:
        if a.internal_id not in by_id:
            raise SchemaError("UNKNOWN_ID", f"assessment for unknown Internal_ID {a.internal_id}")
        if a.round != n:
            raise SchemaError("ROUND_MISMATCH", f"{a.internal_id}: assessment round {a.round} != {n}")

    if n <= R:                                   # idempotency (10.3)
        for a in rin.assessments:
            if not _same_block(by_id[a.internal_id], n, a):
                raise SchemaError("ROUND_EXISTS_DIFFERENT",
                                  f"round {n} already exists and differs for {a.internal_id}")
        return state, AppendReport(round=n, action="NO_OP")
    if n != R + 1:
        raise SchemaError("ROUND_GAP", f"round {n} requested but the workbook ends at round {R}")

    new = copy.deepcopy(state)
    rep = AppendReport(round=n, action="APPENDED")
    amap = {a.internal_id: a for a in rin.assessments}
    if len(amap) != len(rin.assessments):
        raise SchemaError("DUPLICATE_ASSESSMENT", "an Internal_ID is assessed twice")

    for o in new.ordered():
        prev = o.value(R)
        a = amap.get(o.internal_id)
        if a is None:
            if prev != S.CLOSED:
                raise SchemaError("MISSING_ASSESSMENT",
                                  f"{o.internal_id} (#{o.reader_no}) is {prev!r} at the start of round {n} "
                                  "and has no assessment")
            vals = _values(o, R)
            lcr = L.latest_closure_round(vals, o.birth_round, R)
            ordn = S.ordinal(lcr)
            o.cells[n] = RoundCells(closure=S.CLOSED, feedback=S.carried_closed_feedback(ordn),
                                    response=S.closed_guidance(ordn), impl=S.IMPL_PRIOR_CLOSED)
            rep.carried_closed.append(o.internal_id)
            continue
        rep.assessed.append(o.internal_id)
        fb = _as_gtext(a.feedback) if a.feedback is not None else None
        if fb is None:
            raise SchemaError("MISSING_FEEDBACK", f"{o.internal_id}: round {n} assessment has no feedback")
        if a.status == S.CLOSED:
            if prev == S.CLOSED:
                lcr = L.latest_closure_round(_values(o, R), o.birth_round, R)
            else:
                lcr = n
            ordn = S.ordinal(lcr)
            o.cells[n] = RoundCells(closure=S.CLOSED, feedback=fb, response=S.closed_guidance(ordn),
                                    impl=S.IMPL_PRIOR_CLOSED)
            if a.closure_basis:
                o.closure_basis[n] = a.closure_basis
        else:
            if prev == S.CLOSED:
                rep.reopened.append(o.internal_id)
            o.cells[n] = RoundCells(closure=a.status, feedback=fb, response=S.PH_TEXT, impl=S.PH_STATUS)

    next_reader = max((o.reader_int for o in new.observations), default=0)
    seq = sum(1 for o in new.observations if o.internal_id.split("-")[2] == f"R{n}")
    for nobs in rin.new_observations:
        if not nobs.reason:
            raise SchemaError("MISSING_REASON", "an observation raised after round 1 needs its reason (10.2)")
        next_reader += 1
        seq += 1
        o = Observation(internal_id=f"GCO-{new.document.code}-R{n}-{seq:03d}",
                        reader_no=reader_no(next_reader), birth_round=n,
                        location=nobs.location, quote=nobs.quote, comment=_as_gtext(nobs.comment))
        for r in range(1, n):
            o.cells[r] = RoundCells(closure=S.NOT_RAISED)
        o.cells[n] = RoundCells(closure=S.OPEN,
                                feedback=GText.plain(f"{S.NEW_OBS_FEEDBACK_PREFIX} {nobs.reason}"),
                                response=S.PH_TEXT, impl=S.PH_STATUS)
        if nobs.title and nobs.title.strip():
            o.title, o.title_status = " ".join(nobs.title.split()), S.TITLE_PROPOSED
        new.observations.append(o)
        rep.new_ids.append(o.internal_id)

    new.rounds.append(ReviewRound(n, rin.date, rin.document_version))
    if rin.document_version:
        new.document.cover_version = rin.document_version
    return new, rep


# ----------------------------------------------------------------- titles (10.4A.16, 19A.9)
@dataclass
class TitleDecision:
    """One recorded human decision on a title. A boolean is not a decision."""
    internal_id: str
    decision: str                         # APPROVE | REJECT | WITHDRAW
    reviewer: str
    date: str
    decision_ref: str
    title: str | None = None              # the approved wording (defaults to the proposed title)


@dataclass
class TitleReport:
    approved: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    withdrawn: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)   # decisions that could not be applied, with the reason


def finalize_titles(state: ReviewState, decisions: list[TitleDecision]) -> tuple[ReviewState, TitleReport]:
    """Apply recorded reviewer decisions to the proposed titles.

    Rules: an ISSUED title is immutable (only WITHDRAW with a decision reference
    changes it); an APPROVE needs reviewer, ISO date and a decision reference;
    a legacy observation without a proposal cannot be approved retroactively
    unless the decision supplies the wording itself (12: no artificial
    retroactive approval – the evidence is the recorded decision).
    """
    new = copy.deepcopy(state)
    by_id = new.by_id()
    rep = TitleReport()
    for d in decisions:
        o = by_id.get(d.internal_id)
        if o is None:
            rep.refused.append(f"{d.internal_id}: unknown Internal_ID"); continue
        ev = TitleEvidence(d.reviewer or "", d.date or "", d.decision_ref or "")
        if not ev.complete:
            rep.refused.append(f"{d.internal_id}: decision without reviewer, ISO date or decision reference (19A.9)"); continue
        kind = (d.decision or "").upper()
        if o.title_status == S.TITLE_ISSUED and kind != "WITHDRAW":
            rep.refused.append(f"{d.internal_id}: issued title is immutable; only WITHDRAW is accepted"); continue
        if kind == "APPROVE":
            wording = " ".join((d.title or o.title or "").split())
            if not wording:
                rep.refused.append(f"{d.internal_id}: nothing to approve (no proposed title and no wording)"); continue
            if len(wording) > S.TITLE_MAX:
                rep.refused.append(f"{d.internal_id}: title exceeds {S.TITLE_MAX} characters"); continue
            o.title, o.title_status, o.title_evidence = wording, S.TITLE_APPROVED, ev
            rep.approved.append(o.internal_id)
        elif kind == "REJECT":
            o.title_status, o.title_evidence = S.TITLE_DRAFT, None
            rep.rejected.append(o.internal_id)
        elif kind == "WITHDRAW":
            o.title, o.title_status, o.title_evidence = None, S.TITLE_NONE, None
            rep.withdrawn.append(o.internal_id)
        else:
            rep.refused.append(f"{d.internal_id}: unknown decision {d.decision!r}")
    for o in new.observations:
        o.__post_init__()
    return new, rep


def mark_titles_issued(state: ReviewState) -> int:
    """At issue of a workbook every APPROVED title becomes ISSUED (immutable). Returns the count."""
    n = 0
    for o in state.observations:
        if o.title_status == S.TITLE_APPROVED:
            o.title_status = S.TITLE_ISSUED
            n += 1
    return n
