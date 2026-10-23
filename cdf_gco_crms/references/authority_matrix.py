"""Parser of the CDF Delegation-of-Authority matrix ("مصفوفة الصلاحيات الرئيسية لصندوق التنمية الثقافي", 30 April 2024).

The matrix pages (8–26 in the supplied export) are a table: one column per
body (مجلس الإدارة, اللجنة التنفيذية, لجنة المراجعة والمخاطر والامتثال, ...),
a column "البنود" with the item title, a column with the item number and a
column "الفئة" with the group. The ``pdftotext -layout`` text is column-garbled,
so the parser reads the PDF with ``pdfplumber``: the ruling lines of the table
give the column and row boundaries, every word is placed in a cell by its
coordinates, and a role word (الإعداد / المراجعة / التوصية / الاعتماد /
الإخطار) is assigned to the body whose column holds it. Nothing is assumed about
the number or order of the columns: the header row of every page is read anew.

pdfplumber returns the glyphs of this PowerPoint export in visual order, so
each Arabic word is reversed back to logical order and the lam-alef ligature
breaks are repaired by :mod:`textnorm`.

A cell that holds text the role vocabulary does not cover is left unassigned
and the item is marked PARTIAL; an empty cell never receives a role.
Extraction proves only that a passage occurs on a page of the matrix; it
establishes neither the legal applicability of an item nor the approval
status of the document, which the source register records as UNVERIFIED.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .textnorm import match_key, nfc

# Canonical body names (reader-facing). Header cells are matched to these by a
# loose key; a header that matches nothing is kept verbatim and reported.
BODIES = (
    "مجلس الإدارة",
    "أمانة مجلس الإدارة",
    "اللجنة التنفيذية",
    "لجنة المراجعة والمخاطر والامتثال",
    "لجنة الترشيحات والمكافآت",
    "لجنة الاستثمار",
    "الرئيس التنفيذي",
    "رئيس المراجعة الداخلية",
    "صندوق التنمية الوطني",
)

ROLE_PREPARE = "الإعداد"
ROLE_REVIEW = "المراجعة"
ROLE_RECOMMEND = "التوصية"
ROLE_APPROVE = "الاعتماد"
ROLE_NOTIFY = "الإخطار"
ROLE_INFORM = "الإبلاغ"
ROLE_BRIEF = "الإحاطة"
ROLE_EXECUTE = "التنفيذ"
ROLE_ORDER = (ROLE_PREPARE, ROLE_REVIEW, ROLE_RECOMMEND, ROLE_APPROVE, ROLE_NOTIFY, ROLE_INFORM,
              ROLE_BRIEF, ROLE_EXECUTE)
# Loose stems (match_key form) that identify a role inside a cell text.
_ROLE_STEMS = (
    ("اعتماد", ROLE_APPROVE),
    ("توصيه", ROLE_RECOMMEND),
    ("مراجعه", ROLE_REVIEW),
    ("اعداد", ROLE_PREPARE),
    ("اخطار", ROLE_NOTIFY),
    ("ابلاغ", ROLE_INFORM),
    ("احاطه", ROLE_BRIEF),
    ("تنفيذ", ROLE_EXECUTE),
)

H_ITEMS = "البنود"
H_GROUP = "الفئة"
CONF_HIGH = "HIGH"
CONF_PARTIAL = "PARTIAL"

_NUM_RE = re.compile(r"^\d+(?:\.\d+)?$")
_ITEM_RE = re.compile(r"^\d+\.\d+$")
_LTR_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.,%/()-]*")
_ARABIC = re.compile("[؀-ۿ]")


@dataclass(frozen=True)
class Item:
    """One numbered row of the matrix with the role of every body that holds one.

    ``roles`` maps a canonical body to a canonical role; ``qualifiers`` keeps
    what the cell said beyond the role word ("(رئيس المجلس)", "1", "2", "*").
    ``unresolved`` holds cell texts no role could be read from (left out of
    ``roles``). ``confidence`` is HIGH when every non-empty role cell was
    assigned unambiguously and the number and title were read, else PARTIAL.
    Occurrence on ``page`` is all that is proven; applicability is not.
    """
    number: str
    category: str
    title: str
    page: int
    roles: dict[str, str] = field(default_factory=dict)
    qualifiers: dict[str, str] = field(default_factory=dict)
    unresolved: dict[str, str] = field(default_factory=dict)
    group: str = ""
    category_number: int | None = None
    confidence: str = CONF_HIGH
    notes: tuple[str, ...] = ()

    def bodies_with(self, role: str) -> tuple[str, ...]:
        return tuple(b for b, r in self.roles.items() if r == role)

    def sort_key(self) -> tuple[int, ...]:
        return tuple(int(x) for x in self.number.split("."))


@dataclass(frozen=True)
class MatrixPage:
    page: int
    bodies: tuple[str, ...]
    unrecognised_headers: tuple[str, ...]
    notes: tuple[str, ...]
    item_numbers: tuple[str, ...]


@dataclass
class MatrixIndex:
    """Index over the parsed matrix (deterministic order by item number)."""
    source: str
    pages_total: int
    items: list[Item] = field(default_factory=list)
    categories: dict[int, str] = field(default_factory=dict)
    pages: list[MatrixPage] = field(default_factory=list)
    title: str = ""
    approval_text: str = ""
    approval_page: int | None = None

    # ---------------------------------------------------------------- queries
    def item(self, number: str) -> Item | None:
        for it in self.items:
            if it.number == number:
                return it
        return None

    def find_items(self, keyword: str) -> list[Item]:
        """Items whose number, title, category or group contains ``keyword`` (loose key)."""
        key = match_key(keyword)
        if not key:
            return []
        out = []
        for it in self.items:
            hay = " ".join((it.number, it.title, it.category, it.group))
            if key in match_key(hay) or keyword.strip() == it.number:
                out.append(it)
        return out

    def decision_owners(self, item: str | Item) -> tuple[str, ...]:
        it = self._resolve(item)
        return it.bodies_with(ROLE_APPROVE) if it else ()

    def decision_owner(self, item: str | Item) -> str | None:
        """The single body whose role on the item is الاعتماد; None when no cell says so.

        Raises ``ValueError`` when the matrix names more than one approving
        body, so that no body is silently preferred.
        """
        owners = self.decision_owners(item)
        if len(owners) > 1:
            raise ValueError(f"item has several approving bodies: {owners}")
        return owners[0] if owners else None

    def chain(self, item: str | Item) -> list[tuple[str, tuple[str, ...]]]:
        """Bodies per stage in matrix order: الإعداد, المراجعة, التوصية, الاعتماد, الإخطار, ...

        Only stages a cell actually names are listed; recommendation bodies
        with a numbered qualifier ("1", "2") are ordered by that number.
        """
        it = self._resolve(item)
        if it is None:
            return []
        out = []
        for role in ROLE_ORDER:
            bodies = list(it.bodies_with(role))
            if not bodies:
                continue
            if role == ROLE_RECOMMEND:
                order = {b: i for i, b in enumerate(bodies)}
                bodies.sort(key=lambda b: (_qualifier_rank(it.qualifiers.get(b, "")), order[b]))
            out.append((role, tuple(bodies)))
        return out

    def bodies(self) -> list[str]:
        seen: dict[str, None] = {}
        for p in self.pages:
            for b in p.bodies:
                seen.setdefault(b)
        return list(seen)

    def coverage(self) -> dict:
        high = [it.number for it in self.items if it.confidence == CONF_HIGH]
        partial = [it.number for it in self.items if it.confidence != CONF_HIGH]
        return {
            "pages_parsed": [p.page for p in self.pages],
            "items_parsed": len(self.items),
            "items_high_confidence": len(high),
            "items_partial_confidence": len(partial),
            "partial_items": partial,
            "items_with_decision_owner": sum(1 for it in self.items if it.bodies_with(ROLE_APPROVE)),
            "bodies_recognised": self.bodies(),
            "unrecognised_headers": sorted({h for p in self.pages for h in p.unrecognised_headers}),
            "categories": len(self.categories),
        }

    def _resolve(self, item: str | Item) -> Item | None:
        return item if isinstance(item, Item) else self.item(item)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "pages_total": self.pages_total,
            "categories": {str(k): v for k, v in sorted(self.categories.items())},
            "pages": [{"page": p.page, "bodies": list(p.bodies), "unrecognised_headers": list(p.unrecognised_headers),
                       "notes": list(p.notes), "item_numbers": list(p.item_numbers)} for p in self.pages],
            "items": [{"number": it.number, "category": it.category, "category_number": it.category_number,
                       "group": it.group, "title": it.title, "page": it.page, "roles": dict(it.roles),
                       "qualifiers": dict(it.qualifiers), "unresolved": dict(it.unresolved),
                       "confidence": it.confidence, "notes": list(it.notes)} for it in self.items],
            "approval_text": self.approval_text,
            "approval_page": self.approval_page,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MatrixIndex":
        idx = cls(d["source"], d["pages_total"], title=d.get("title", ""), approval_text=d.get("approval_text", ""),
                  approval_page=d.get("approval_page"))
        idx.categories = {int(k): v for k, v in d["categories"].items()}
        idx.pages = [MatrixPage(p["page"], tuple(p["bodies"]), tuple(p["unrecognised_headers"]),
                                tuple(p["notes"]), tuple(p["item_numbers"])) for p in d["pages"]]
        idx.items = [Item(i["number"], i["category"], i["title"], i["page"], dict(i["roles"]), dict(i["qualifiers"]),
                          dict(i["unresolved"]), i.get("group", ""), i.get("category_number"), i["confidence"],
                          tuple(i.get("notes", ()))) for i in d["items"]]
        return idx


# ------------------------------------------------------------------- helpers
def _qualifier_rank(q: str) -> int:
    m = re.search(r"\d+", q)
    return int(m.group()) if m else 0


def logical_order(word: str) -> str:
    """Reverse a visual-order Arabic word to logical order, keeping LTR runs (digits, Latin) intact."""
    if not _ARABIC.search(word):
        return word
    rev = word[::-1]
    return _LTR_RUN.sub(lambda m: m.group()[::-1], rev)


def canonical_body(header: str) -> str | None:
    key = match_key(header)
    if not key:
        return None
    best, score = None, 0.0
    for body in BODIES:
        bkey = match_key(body)
        r = difflib.SequenceMatcher(None, key, bkey).ratio()
        if bkey in key or key in bkey:
            r = max(r, 0.9)
        if r > score:
            best, score = body, r
    return best if score >= 0.8 else None


def classify_role(cell: str) -> tuple[str | None, str]:
    """(canonical role, qualifier) of a cell text; (None, text) when no role word is present.

    The qualifier is what the cell says beyond the role word: a footnote mark,
    a rank ("1", "2") or a holder such as "(رئيس المجلس)". It is kept verbatim
    (normalised) and never turned into a role.
    """
    key = match_key(cell)
    for stem, role in _ROLE_STEMS:
        if stem in key:
            marks = "".join(re.findall(r"\*+", cell))
            rolekey = match_key(role)
            rest = []
            for tok in re.sub(r"[-–—]", " ", nfc(cell)).split():
                tkey = match_key(tok)
                if not tkey or tkey in rolekey or stem in tkey:
                    continue
                rest.append(tok)
            qual = " ".join(rest).strip(" -–—*")
            if marks:
                qual = f"{qual} {marks}".strip()
            return role, qual
    return None, cell


def match_key_text(text: str) -> str:
    """NFC text with hamza forms folded and ta-marbuta unified, spaces kept (for qualifier tidying)."""
    t = nfc(text)
    return t.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"}))


def _merge(values: list[float], tol: float = 3.0) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if out and v - out[-1] < tol:
            continue
        out.append(v)
    return out


def _cell_text(words: list[dict]) -> str:
    """Join words of a cell: visual lines top to bottom, each right to left."""
    if not words:
        return ""
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: w["top"]):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= 4:
            rows[-1].append(w)
        else:
            rows.append([w])
    parts = []
    for row in rows:
        parts.append(" ".join(logical_order(w["text"]) for w in sorted(row, key=lambda w: -w["x1"])))
    return nfc(" ".join(parts))


# ------------------------------------------------------------------- parsing
def parse_matrix(path: str | Path) -> MatrixIndex:
    """Parse the matrix PDF into a :class:`MatrixIndex` (deterministic).

    The result proves only that the items and role words occur on the pages
    recorded; it establishes neither applicability nor approval.
    """
    import pdfplumber  # local import: only the matrix parser needs it

    path = Path(path)
    idx = MatrixIndex(source=path.name, pages_total=0)
    with pdfplumber.open(str(path)) as pdf:
        idx.pages_total = len(pdf.pages)
        if pdf.pages:
            idx.title = _plain_page_text(pdf.pages[0])
        other: dict[int, str] = {}
        for pno, page in enumerate(pdf.pages, start=1):
            if _parse_page(page, pno, idx) is None:
                other[pno] = _plain_page_text(page)
        # the approval decision follows the last table page
        last_table = max((p.page for p in idx.pages), default=0)
        for pno in sorted(other):
            if pno > last_table and len(other[pno]) > 40:
                idx.approval_text = other[pno]
                idx.approval_page = pno
                break
    idx.items.sort(key=Item.sort_key)
    return idx


def _plain_page_text(page) -> str:
    words = [w for w in page.extract_words(extra_attrs=["size"]) if w["size"] >= 6 and w["x1"] - w["x0"] > 0.5]
    return _cell_text(words)


def _parse_page(page, pno: int, idx: MatrixIndex) -> MatrixPage | None:
    long_v = [l for l in page.lines if abs(l["x0"] - l["x1"]) < 1 and (l["bottom"] - l["top"]) >= 100]
    if len(long_v) < 4:
        return None
    xs = _merge([l["x0"] for l in long_v])
    top = min(l["top"] for l in long_v)
    bottom = max(l["bottom"] for l in long_v)
    width = xs[-1] - xs[0]
    ys = _merge([l["top"] for l in page.lines
                 if abs(l["top"] - l["bottom"]) < 1 and (l["x1"] - l["x0"]) >= 0.4 * width
                 and top - 3 <= l["top"] <= bottom + 3])
    if len(ys) < 3:
        return None
    cols = list(zip(xs, xs[1:]))
    bands = list(zip(ys, ys[1:]))
    words = [w for w in page.extract_words(extra_attrs=["size"])
             if w["size"] >= 6 and w["x1"] - w["x0"] > 0.5 and xs[0] - 2 <= (w["x0"] + w["x1"]) / 2 <= xs[-1] + 2]

    def col_of(w):
        cx = (w["x0"] + w["x1"]) / 2
        for i, (a, b) in enumerate(cols):
            if a <= cx < b:
                return i
        return None

    def band_of(w):
        cy = (w["top"] + w["bottom"]) / 2
        for i, (a, b) in enumerate(bands):
            if a <= cy < b:
                return i
        return None

    grid: dict[tuple[int, int], list[dict]] = {}
    below: list[dict] = []
    for w in words:
        c, b = col_of(w), band_of(w)
        if c is None:
            continue
        if b is None:
            if (w["top"] + w["bottom"]) / 2 >= bands[-1][1]:
                below.append(w)
            continue
        grid.setdefault((b, c), []).append(w)

    # header row: the band whose cells include "البنود"
    header_band = None
    for b in range(len(bands)):
        texts = {c: _cell_text(grid.get((b, c), [])) for c in range(len(cols))}
        if any(match_key(t) == match_key(H_ITEMS) for t in texts.values()):
            header_band = b
            headers = texts
            break
    if header_band is None:
        return None
    title_col = next(c for c, t in headers.items() if match_key(t) == match_key(H_ITEMS))
    number_col = title_col + 1 if title_col + 1 < len(cols) else None
    group_col = next((c for c, t in headers.items() if match_key(t) == match_key(H_GROUP)), None)
    if number_col is None:
        return None
    body_cols: dict[int, str] = {}
    unrecognised: list[str] = []
    for c, t in headers.items():
        if c in (title_col, number_col, group_col) or not t:
            continue
        body = canonical_body(t)
        if body is None:
            unrecognised.append(t)
            body = t
        body_cols[c] = body

    # rows: split every band at its number anchors (a band may hold a category row and an item)
    rows: list[dict[int, list[dict]]] = []
    for b in range(header_band + 1, len(bands)):
        cells = {c: grid.get((b, c), []) for c in range(len(cols))}
        anchors = sorted((w for w in cells.get(number_col, []) if _NUM_RE.match(w["text"])),
                         key=lambda w: w["top"])
        if len(anchors) <= 1:
            rows.append(cells)
            continue
        cuts = [(anchors[i]["bottom"] + anchors[i + 1]["top"]) / 2 for i in range(len(anchors) - 1)]
        parts: list[dict[int, list[dict]]] = [dict() for _ in range(len(anchors))]
        for c, ws in cells.items():
            for w in ws:
                cy = (w["top"] + w["bottom"]) / 2
                k = sum(1 for cut in cuts if cy >= cut)
                parts[k].setdefault(c, []).append(w)
        rows.extend(parts)

    group_words: list[dict] = []
    if group_col is not None:
        for b in range(header_band + 1, len(bands)):
            group_words.extend(grid.get((b, group_col), []))
    group = _cell_text(group_words)
    notes: list[str] = []
    item_numbers: list[str] = []
    for cells in rows:
        number = _cell_text(cells.get(number_col, []))
        title = _cell_text(cells.get(title_col, []))
        if not number and not title and not any(cells.get(c) for c in body_cols):
            continue
        if _NUM_RE.match(number) and "." not in number:
            idx.categories[int(number)] = title
            continue
        if _ITEM_RE.match(number):
            roles: dict[str, str] = {}
            quals: dict[str, str] = {}
            unresolved: dict[str, str] = {}
            for c, body in body_cols.items():
                text = _cell_text(cells.get(c, []))
                if not text:
                    continue
                role, qual = classify_role(text)
                if role is None:
                    unresolved[body] = text
                else:
                    roles[body] = role
                    if qual:
                        quals[body] = qual
            cat_no = int(number.split(".")[0])
            conf = CONF_HIGH if (title and not unresolved and not unrecognised) else CONF_PARTIAL
            idx.items.append(Item(number, idx.categories.get(cat_no, ""), title, pno, roles, quals, unresolved,
                                  group, cat_no, conf))
            item_numbers.append(number)
            continue
        # anything else inside the frame is a footnote row
        text = _cell_text([w for ws in cells.values() for w in ws])
        if text:
            notes.append(text)
    if below:
        notes.append(_cell_text(below))
    mp = MatrixPage(pno, tuple(body_cols[c] for c in sorted(body_cols, reverse=True)), tuple(unrecognised),
                    tuple(notes), tuple(item_numbers))
    idx.pages.append(mp)
    if notes:
        for i, it in enumerate(idx.items):
            if it.page == pno and it.number in item_numbers and not it.notes:
                idx.items[i] = Item(it.number, it.category, it.title, it.page, it.roles, it.qualifiers, it.unresolved,
                                    it.group, it.category_number, it.confidence, tuple(notes))
    return mp
