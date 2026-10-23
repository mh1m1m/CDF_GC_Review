"""Parser of the CDF organisational-structure deck ("الهيكل التنظيمي والمهام والمسؤوليات الإدارية").

Input is the ``pdftotext -layout`` text of the 92-page PowerPoint export (pages
separated by form feed). The deck alternates one "التقسيم التنظيمي الموصى به"
page per sector (sector name and its sub-units) with "المهام والمسؤوليات
المقترحة (i/n)" pages, one per unit, carrying a bullet list of tasks on the
right and, on the left, the side boxes "التواصل مع داخل الصندوق" /
"التواصل مع خارج الصندوق". The layout text keeps the horizontal position of
every segment, so side-box entries are told apart from task text by the column
at which a segment ends (side boxes end before column 60, task text runs past
column 120); no column letter or fixed offset of any particular page is assumed.

Every record keeps the page it was read from. Extraction proves only that a
passage occurs on that page of the deck: it establishes neither the legal
applicability of the content nor the approval of the deck, which the source
register records as PROPOSED_NOT_APPROVED.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .textnorm import match_key, nfc, strip_marks

H_DIVISION = "التقسيم التنظيمي الموصى به"
H_TASKS = "المهام والمسؤوليات المقترحة"
H_MAIN = "المهام والمسؤوليات الأساسية"
H_INTERNAL = "التواصل مع داخل الصندوق"
H_EXTERNAL = "التواصل مع خارج الصندوق"
BULLET = "•"

# A segment whose last character sits before this column belongs to the left
# side box; task text (right-aligned) always ends far to the right of it.
SIDE_BOX_END_COL = 60

_SEG_RE = re.compile(r"\S+(?: {1,2}\S+)*")
_PAGE_NO_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class Sector:
    """A sector as named on its "التقسيم التنظيمي الموصى به" page.

    ``parent`` is set when the page shows the sector under another one (a
    sub-sector); ``units`` are the names drawn on that page, in reading order.
    Occurrence on ``page`` is all that is proven; approval is not.
    """
    name: str
    page: int
    units: tuple[str, ...] = ()
    parent: str | None = None


@dataclass(frozen=True)
class Unit:
    """A unit with the tasks listed on its "المهام والمسؤوليات المقترحة" page.

    Units named on a division page but without a tasks page of their own are
    kept with an empty ``tasks`` tuple and the division page as ``page``.
    Occurrence on ``page`` is all that is proven; approval is not.
    """
    name: str
    sector: str
    page: int
    tasks: tuple[str, ...] = ()
    internal_contacts: tuple[str, ...] = ()
    external_contacts: tuple[str, ...] = ()
    heading: str | None = None


@dataclass(frozen=True)
class Mandate:
    """Tasks of a unit with their page of occurrence (no approval meaning)."""
    unit: str
    sector: str
    page: int
    tasks: tuple[str, ...]


@dataclass
class OrgIndex:
    """Index over the parsed deck. Names are NFC and ligature-repaired.

    The controlled list returned by :meth:`departments` is a list of names
    that occur in the deck, nothing more: the deck is a proposal
    (PROPOSED_NOT_APPROVED) and the list carries no approval meaning.
    """
    source: str
    pages_total: int
    sectors: list[Sector] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    pages_parsed: tuple[int, ...] = ()
    title: str = ""

    # ---------------------------------------------------------------- queries
    def departments(self) -> list[str]:
        """Controlled list of every sector and unit name, in deck order, deduplicated."""
        seen: dict[str, None] = {}
        for s in self.sectors:
            seen.setdefault(s.name)
        for u in self.units:
            seen.setdefault(u.name)
        return list(seen)

    def unit(self, name: str) -> Unit | None:
        key = match_key(name)
        for u in self.units:
            if match_key(u.name) == key:
                return u
        return None

    def sector(self, name: str) -> Sector | None:
        key = match_key(name)
        for s in self.sectors:
            if match_key(s.name) == key:
                return s
        return None

    def find_unit(self, text: str, cutoff: float = 0.75) -> Unit | None:
        """Fuzzy lookup of a unit by name (NFC, ligature-repaired, hamza-folded).

        Exact key match first, then containment either way, then the best
        ``difflib`` ratio at or above ``cutoff``. Deterministic: ties go to the
        earlier page.
        """
        hit, _ = self.match(text, cutoff)
        return hit

    def match(self, text: str, cutoff: float = 0.75) -> tuple[Unit | None, list[str]]:
        """Best unit for ``text`` and the ranked candidate names considered."""
        key = match_key(_strip_prefix(text))
        if not key:
            return None, []
        exact = [u for u in self.units if match_key(u.name) == key]
        if exact:
            return exact[0], [exact[0].name]
        scored: list[tuple[float, int, Unit]] = []
        for i, u in enumerate(self.units):
            ukey = match_key(u.name)
            if key in ukey or ukey in key:
                ratio = 0.999 - 0.0001 * abs(len(ukey) - len(key))
            else:
                ratio = difflib.SequenceMatcher(None, key, ukey).ratio()
            scored.append((ratio, i, u))
        scored.sort(key=lambda t: (-t[0], t[1]))
        candidates = [u.name for r, _, u in scored[:5] if r >= min(cutoff, 0.6)]
        best = scored[0] if scored and scored[0][0] >= cutoff else None
        return (best[2] if best else None), candidates

    def mandate(self, unit: str | Unit) -> Mandate | None:
        """Tasks of a unit with the page they occur on (occurrence only, not approval)."""
        u = unit if isinstance(unit, Unit) else (self.unit(unit) or self.find_unit(unit))
        if u is None:
            return None
        return Mandate(u.name, u.sector, u.page, u.tasks)

    def sector_of(self, unit: str) -> Sector | None:
        u = self.unit(unit) or self.find_unit(unit)
        return self.sector(u.sector) if u else None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "pages_total": self.pages_total,
            "pages_parsed": list(self.pages_parsed),
            "sectors": [{"name": s.name, "page": s.page, "parent": s.parent, "units": list(s.units)}
                        for s in self.sectors],
            "units": [{"name": u.name, "sector": u.sector, "page": u.page, "heading": u.heading,
                       "tasks": list(u.tasks), "internal_contacts": list(u.internal_contacts),
                       "external_contacts": list(u.external_contacts)} for u in self.units],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OrgIndex":
        idx = cls(d["source"], d["pages_total"], title=d.get("title", ""),
                  pages_parsed=tuple(d.get("pages_parsed", ())))
        idx.sectors = [Sector(s["name"], s["page"], tuple(s["units"]), s.get("parent")) for s in d["sectors"]]
        idx.units = [Unit(u["name"], u["sector"], u["page"], tuple(u["tasks"]),
                          tuple(u["internal_contacts"]), tuple(u["external_contacts"]), u.get("heading"))
                     for u in d["units"]]
        return idx


# ------------------------------------------------------------------- parsing
def _strip_prefix(text: str) -> str:
    t = nfc(text)
    for p in ("إدارة ", "قطاع ", "وحدة ", "مكتب "):
        if t.startswith(p) and len(t) > len(p) + 3:
            return t[len(p):]
    return t


def _segments(line: str) -> list[tuple[int, int, str]]:
    """(start_col, end_col, text) of every run of text separated by 3+ spaces.

    Bullets always start an entry, so a run holding several bullets is split
    at each one; columns are measured on the raw line (bidi marks included,
    consistently for every page).
    """
    out: list[tuple[int, int, str]] = []
    for m in _SEG_RE.finditer(line):
        raw = m.group()
        start = m.start()
        parts = [p for p in re.split(f"(?={BULLET})", raw) if p.strip()]
        pos = start
        for part in parts:
            idx = raw.find(part, pos - start)
            s = start + idx
            e = s + len(part)
            text = nfc(part)
            if text:
                out.append((s, e, text))
            pos = e
    return out


def _page_lines(page: str) -> list[list[tuple[int, int, str]]]:
    lines = []
    for raw in page.splitlines():
        segs = _segments(raw)
        if not segs:
            continue
        if len(segs) == 1 and _PAGE_NO_RE.match(strip_marks(segs[0][2]).strip()):
            continue  # slide number
        lines.append(segs)
    return lines


def _header_kind(text: str) -> str | None:
    if text.startswith(H_DIVISION):
        return "division"
    if text.startswith(H_TASKS):
        return "tasks"
    return None


def _parse_division(page_no: int, lines: list[list[tuple[int, int, str]]]) -> Sector:
    names: list[str] = []
    for segs in lines:
        for _, _, text in segs:
            if _header_kind(text) or not text:
                continue
            names.append(text)
    title = names[0]
    rest = [n for n in names[1:]]
    parent = None
    if rest and match_key(rest[0]) != match_key(title):
        parent = rest[0]
        rest = rest[1:]
    units: list[str] = []
    for n in rest:
        if match_key(n) == match_key(title) or n in units:
            continue
        units.append(n)
    return Sector(title, page_no, tuple(units), parent)


def _parse_tasks(page_no: int, lines: list[list[tuple[int, int, str]]], sector: str) -> Unit:
    heading = None
    name = None
    tasks: list[str] = []
    internal: list[str] = []
    external: list[str] = []
    side: list[str] | None = None
    for segs in lines:
        for _, end, text in segs:
            if name is None:
                if _header_kind(text):
                    heading = text
                    continue
                name = text
                continue
            if text == H_MAIN:
                continue
            if text == H_INTERNAL:
                side = internal
                continue
            if text == H_EXTERNAL:
                side = external
                continue
            is_side = end < SIDE_BOX_END_COL
            if text.startswith(BULLET):
                entry = text[len(BULLET):].strip()
                if is_side:
                    (side if side is not None else internal).append(entry)
                else:
                    tasks.append(entry)
            elif is_side:
                target = side if side is not None else internal
                if target:
                    target[-1] = f"{target[-1]} {text}"
            elif tasks:
                tasks[-1] = f"{tasks[-1]} {text}"
    if name is None:
        raise ValueError(f"page {page_no}: no unit name found on a tasks page")
    return Unit(name, sector, page_no, tuple(tasks), tuple(internal), tuple(external), heading)


def parse_org_text(path: str | Path) -> OrgIndex:
    """Parse the ``pdftotext -layout`` text of the deck into an :class:`OrgIndex`.

    Deterministic; records keep their page numbers. The result proves only
    that the names and passages occur in the deck, not that the structure is
    approved or applicable.
    """
    path = Path(path)
    pages = path.read_text(encoding="utf-8").split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    idx = OrgIndex(source=path.name, pages_total=len(pages))
    if pages:
        idx.title = " — ".join(nfc(l) for l in pages[0].splitlines() if nfc(l))
    parsed: list[int] = []
    current: Sector | None = None
    for i, page in enumerate(pages, start=1):
        lines = _page_lines(page)
        if not lines:
            continue
        kind = None
        for segs in lines[:2]:
            for _, _, text in segs:
                kind = kind or _header_kind(text)
        if kind == "division":
            current = _parse_division(i, lines)
            idx.sectors.append(current)
            parsed.append(i)
        elif kind == "tasks":
            unit = _parse_tasks(i, lines, current.name if current else "")
            idx.units.append(unit)
            parsed.append(i)
    # Units drawn on a division page without a tasks page of their own.
    have = {match_key(u.name) for u in idx.units}
    for s in idx.sectors:
        for name in s.units:
            if match_key(name) not in have:
                idx.units.append(Unit(name, s.name, s.page))
                have.add(match_key(name))
    idx.pages_parsed = tuple(parsed)
    return idx
