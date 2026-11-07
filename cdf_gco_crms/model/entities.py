"""Canonical review-state model (directive §6).

The model is what the engine reads from and writes to the data sheet. It keeps
every assessment of every round (append-only history); nothing in it is ever
recomputed from the dashboard. Reader_No is a display value; Internal_ID is the
key (11.1–11.3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont

from ..config import design_tokens as T
from ..config import round_schema as S

INTERNAL_ID_RE = re.compile(r"^GCO-(?P<doc>[A-Z]{2,4})-R(?P<round>\d+)-(?P<seq>\d{3})$")

FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")   # OWASP CSV/formula-injection leaders


def is_formula_like(v) -> bool:
    """True when a text would be stored by openpyxl as a formula (leading '=') or parsed as one by a
    spreadsheet after a copy-paste ('+', '-', '@' leaders). Such text is always written as an inline
    string (G-SUB-7, 15A.6)."""
    return isinstance(v, str) and v[:1] in FORMULA_LEADERS and v.strip() not in ("", "-")


def text_cell_value(text: str, size: float = 10):
    """A plain text as a cell value that can never become a formula."""
    if is_formula_like(text):
        return CellRichText([TextBlock(InlineFont(rFont=T.FONT, sz=size), text)])
    return text


# --------------------------------------------------------------------------- text
@dataclass(frozen=True)
class Segment:
    text: str
    bold: bool = False


class GText:
    """GCO-authored text with bold labels (10.3 E, 10.9 rich-text integrity)."""

    __slots__ = ("segments",)

    def __init__(self, segments: Iterable[Segment | tuple[str, bool] | str]):
        segs: list[Segment] = []
        for s in segments:
            if isinstance(s, Segment):
                segs.append(s)
            elif isinstance(s, tuple):
                segs.append(Segment(s[0], bool(s[1])))
            else:
                segs.append(Segment(str(s), False))
        self.segments = _normalise_runs(segs)

    @classmethod
    def plain(cls, text: str) -> "GText":
        return cls([Segment(text, False)])

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.segments)

    def to_cell_value(self, size: float = 10):
        if all(not s.bold for s in self.segments):
            return text_cell_value(self.text, size)
        blocks: list[Any] = []
        for s in self.segments:
            font = InlineFont(rFont=T.FONT, sz=size, b=s.bold or None)
            blocks.append(TextBlock(font, s.text))
        return CellRichText(blocks)

    @classmethod
    def from_cell_value(cls, value) -> "GText | None":
        if value is None:
            return None
        if isinstance(value, CellRichText):
            segs = []
            for part in value:
                if isinstance(part, TextBlock):
                    segs.append(Segment(part.text, bool(part.font.b)))
                else:
                    segs.append(Segment(str(part), False))
            return cls(segs)
        return cls.plain(str(value))

    def __eq__(self, other):
        return isinstance(other, GText) and self.segments == other.segments

    def __repr__(self):
        return f"GText({self.text[:40]!r}…)"


def _normalise_runs(segs: list[Segment]) -> list[Segment]:
    """Apply 10.9: no whitespace-only run; a line break belongs to the run that follows."""
    out: list[Segment] = []
    for s in segs:
        if s.text == "":
            continue
        out.append(s)
    # move trailing line breaks of a run to the start of the next run
    i = 0
    while i < len(out) - 1:
        cur = out[i]
        stripped = cur.text.rstrip("\n")
        moved = cur.text[len(stripped):]
        if moved and stripped:
            out[i] = Segment(stripped, cur.bold)
            out[i + 1] = Segment(moved + out[i + 1].text, out[i + 1].bold)
        i += 1
    # merge whitespace-only runs into neighbours
    merged: list[Segment] = []
    for s in out:
        if s.text.strip() == "" and merged:
            merged[-1] = Segment(merged[-1].text + s.text, merged[-1].bold)
        elif merged and merged[-1].text.strip() == "":
            merged[-1] = Segment(merged[-1].text + s.text, s.bold)
        else:
            merged.append(s)
    # adjacent runs with equal weight collapse
    final: list[Segment] = []
    for s in merged:
        if final and final[-1].bold == s.bold:
            final[-1] = Segment(final[-1].text + s.text, s.bold)
        else:
            final.append(s)
    return final


def plain_text(value) -> str:
    """Plain text of any cell value (str, number, CellRichText, GText, None)."""
    if value is None:
        return ""
    if isinstance(value, GText):
        return value.text
    if isinstance(value, CellRichText):
        return "".join(p.text if isinstance(p, TextBlock) else str(p) for p in value)
    return str(value)


# ------------------------------------------------------------------------ entities
@dataclass
class Document:
    name: str
    code: str
    cover_version: str | None = None
    owning_department: str | None = None
    language: str = "ar"
    is_demo: bool = False

    def __post_init__(self):
        if not re.fullmatch(r"[A-Z]{2,4}", self.code):
            raise ValueError(f"document code must be 2-4 Latin capitals (02.5): {self.code!r}")
        if len(self.name) > 60:
            raise ValueError("document short name exceeds 60 characters (02.4)")


@dataclass
class ReviewRound:
    number: int
    date: str | None = None            # ISO date as recorded in the round input; never invented
    document_version: str | None = None

    @property
    def ordinal(self) -> str:
        return S.ordinal(self.number)


@dataclass
class DocumentVersion:
    label: str
    sha256: str | None = None


@dataclass
class RoundCells:
    """The four cells of one observation in one round block, as stored."""
    closure: Any = None
    feedback: Any = None      # None in round 1 (no feedback column)
    response: Any = None
    impl: Any = None


@dataclass(frozen=True)
class TitleEvidence:
    """Who approved a title, when and under which recorded decision (19A.9: never a bare boolean)."""
    reviewer: str
    date: str
    decision_ref: str
    verification: str = "RECORDED"      # RECORDED | VERIFIED (countersigned) – never implies institutional approval

    @property
    def complete(self) -> bool:
        return all(isinstance(x, str) and x.strip() for x in (self.reviewer, self.date, self.decision_ref)) \
            and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.date.strip()))


@dataclass
class Observation:
    internal_id: str
    reader_no: str
    birth_round: int
    location: Any
    quote: Any
    comment: Any                 # GText or raw cell value
    cells: dict[int, RoundCells] = field(default_factory=dict)
    closure_basis: dict[int, str] = field(default_factory=dict)  # round -> code (internal; words only on dashboard)
    # title workflow (10.4A.16): the dashboard shows ``title`` only when a named human approved it
    title: str | None = None
    title_status: str = S.TITLE_NONE
    title_evidence: "TitleEvidence | None" = None

    def __post_init__(self):
        if not INTERNAL_ID_RE.match(self.internal_id):
            raise ValueError(f"Internal_ID does not follow GCO-[DOC]-R[n]-[###]: {self.internal_id!r}")
        if self.title_status not in S.TITLE_STATES:
            raise ValueError(f"{self.internal_id}: unknown title status {self.title_status!r}")
        if self.title_status in S.TITLE_SHOWN_STATES:
            if not (self.title and self.title.strip()):
                raise ValueError(f"{self.internal_id}: an approved title cannot be empty")
            if self.title_evidence is None or not self.title_evidence.complete:
                raise ValueError(f"{self.internal_id}: an approved title needs reviewer, date and decision reference "
                                 "(19A.9 human decision proof)")
        if self.title is not None and len(self.title) > S.TITLE_MAX:
            raise ValueError(f"{self.internal_id}: title exceeds {S.TITLE_MAX} characters")

    @property
    def title_is_approved(self) -> bool:
        return self.title_status in S.TITLE_SHOWN_STATES

    def value(self, r: int) -> str:
        """Official closure value of round r ('' when the observation did not exist)."""
        if r < self.birth_round or r not in self.cells:
            return ""
        return plain_text(self.cells[r].closure).strip()

    @property
    def reader_int(self) -> int:
        return int(self.reader_no)


@dataclass
class RoundAssessment:
    internal_id: str
    round: int
    status: str
    feedback: GText | str | None = None
    closure_basis: str | None = None   # VERIFIED_TEXT | GCO_REASSESSMENT | ROUTED_RESIDUAL | RISK_ACCEPTED

    def __post_init__(self):
        if self.status not in S.CLOSURE_VALUES:
            raise ValueError(f"{self.internal_id}: closure value {self.status!r} is not one of 17.4")
        if self.closure_basis and self.closure_basis not in S.CLOSURE_BASIS_WORDS:
            raise ValueError(f"{self.internal_id}: unknown closure path {self.closure_basis!r}")


@dataclass
class ManagementResponse:
    internal_id: str
    round: int
    response: Any = None
    impl_status: str | None = None


@dataclass
class ClosureDecision:
    internal_id: str
    round: int
    path: str
    decision_id: str | None = None


@dataclass
class EvidenceReference:
    kind: str
    location: str
    sha256: str | None = None


@dataclass
class IntegrityEvent:
    """Internal only (15A). Never written to the requester workbook (G-SHARE-3)."""
    kind: str
    internal_id: str | None
    detail: str


@dataclass
class DashboardViewState:
    selected_round: int
    scope: str = S.SCOPE_ACTION
    selected_reader: str | None = None
    compare_round: int | None = None


@dataclass
class ReviewState:
    document: Document
    rounds: list[ReviewRound]
    observations: list[Observation]

    @property
    def current_round(self) -> int:
        return max(r.number for r in self.rounds) if self.rounds else 0

    def round(self, n: int) -> ReviewRound:
        for r in self.rounds:
            if r.number == n:
                return r
        raise KeyError(n)

    def by_id(self) -> dict[str, Observation]:
        return {o.internal_id: o for o in self.observations}

    def ordered(self) -> list[Observation]:
        return sorted(self.observations, key=lambda o: o.reader_int)
