"""Evidence registry for the institutional challenge (Art. 19A.3, 19A.7; patch V712-037..046).

Every claim argued in the challenge is bound to an :class:`EvidenceItem`
that names a file, its SHA-256, a page or paragraph, an excerpt of at most
240 characters, the source version, the approval class carried from the
source register (never upgraded here) and the applicability class
(NOT_ESTABLISHED unless the caller states another).

Four kinds exist: DOCUMENT (a paragraph of the reviewed document, found by
an NFC / whitespace / lam-alef tolerant search), REFERENCE_ORG (a unit's
mandate page of the organisational-structure deck, PROPOSED_NOT_APPROVED as
the register records it), REFERENCE_MATRIX (an item of the delegation of
authority matrix, UNVERIFIED as the register records it) and POLICY (a
provision the caller supplies with its own class).

What binding proves, and only that: the passage occurs in the hashed text.
It proves neither the approval nor the current effect of a reference
(19A.3, 02.9, G-ADV-02). A DOCUMENT item is the anchor of an observation in
the document under review, which is the subject of the review and not a
source of authority; its :meth:`EvidenceItem.verification` therefore says
``authority_verified`` for the anchor fact alone, with ``basis`` naming
that meaning. A reference or policy item is ``authority_verified`` only in
an approved class. A fake evidence id never resolves (``KeyError``).

Pure Python; no model call; deterministic ids.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..references.textnorm import lam_alef_insensitive, match_key, nfc
from .objection_engine import APPROVED
from .reference_verify import APPROVALS, norm

KINDS = ("DOCUMENT", "REFERENCE_ORG", "REFERENCE_MATRIX", "POLICY")
EXCERPT_MAX = 240
APPLICABILITY_DEFAULT = "NOT_ESTABLISHED"
ID_PREFIX = "EV-"
ID_PATTERN = re.compile(r"\bEV-[0-9a-f]{12}\b")
MIN_QUOTE_CHARS = 8
DOCUMENT_STATUS = "DRAFT_UNDETERMINED"       # the reviewed document is the subject of the review, not a source
MATRIX_VERSION = "30 أبريل 2024"
ORG_VERSION = "2026-02"

_ELLIPSIS = re.compile(r"[…]+|\.{3,}")
_STOP = frozenset({
    "الصندوق", "للصندوق", "بما", "ذلك", "مع", "من", "في", "على", "الى", "إلى", "عن", "او", "أو", "بشكل",
    "خلال", "وفق", "وفقا", "حسب", "لضمان", "ضمان", "بالتنسيق", "التنسيق", "المعنية", "ذات", "الصلة",
    "جميع", "كافة", "كل", "هذه", "هذا", "التي", "الذي", "بين", "بعد", "قبل", "عند", "حال", "دون", "غير",
    "المعتمدة", "المعتمد", "اللازمة", "الوحدات", "التنظيمية", "الإدارة", "الادارة", "إدارة", "ادارة", "قطاع",
    "التوصية", "المطلوب", "نوصي", "نأمل", "نقترح", "نرجو", "البند", "المادة",
})


def stem(token: str) -> str:
    """Loose stem for overlap matching only: match key without a leading conjunction, preposition or article."""
    k = match_key(token)
    if len(k) > 4 and k[0] in "وف":
        k = k[1:]
    if k.startswith("لل") and len(k) > 5:
        k = k[2:]
    elif len(k) > 4 and k[0] in "بلك" and k[1:3] == "ال":
        k = k[1:]
    if k.startswith("ال") and len(k) > 5:
        k = k[2:]
    return k


_STOP_STEMS = frozenset(stem(s) for s in _STOP)


def content_words(text: str) -> list[str]:
    """Content stems of a text (stop words and short tokens removed; for matching only, never for citation)."""
    out: list[str] = []
    for tok in nfc(text).split():
        k = stem(tok)
        if len(k) >= 4 and k not in _STOP_STEMS and tok not in _STOP:
            out.append(k)
    return out


def overlap(a: str, b: str) -> float:
    """Share of the content words of ``a`` that occur in ``b`` (0.0 when ``a`` has none)."""
    wa = content_words(a)
    if not wa:
        return 0.0
    wb = set(content_words(b))
    return sum(1 for w in wa if w in wb) / len(wa)


def _excerpt(text: str) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= EXCERPT_MAX else t[: EXCERPT_MAX - 1] + "…"


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceItem:
    """One bound piece of evidence (occurrence only; never approval or applicability)."""
    id: str
    kind: str
    file: str
    sha256: str
    page_or_paragraph: str
    excerpt: str
    source_version: str
    approval_status: str
    applicability: str = APPLICABILITY_DEFAULT

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"Unknown evidence kind {self.kind!r}")
        if len(self.excerpt) > EXCERPT_MAX:
            raise ValueError("Excerpt exceeds 240 characters")
        if self.approval_status not in APPROVALS:
            raise ValueError(f"Unknown source approval class {self.approval_status!r}")
        if not re.fullmatch(r"EV-[0-9a-f]{12}", self.id):
            raise ValueError("Evidence id must be EV-<12 hex>")

    @property
    def authority_verified(self) -> bool:
        """True only for a reference or policy of an approved class, or for the anchor fact of a DOCUMENT item."""
        if self.kind == "DOCUMENT":
            return bool(self.sha256)
        return self.approval_status in APPROVED

    def verification(self) -> dict:
        """Verification record in the shape ``objection_engine.Objection.decide`` reads."""
        if self.kind == "DOCUMENT":
            basis = "ANCHOR_OCCURS_IN_HASHED_REVIEWED_DOCUMENT"
        elif self.approval_status in APPROVED:
            basis = "APPROVED_CLASS_SOURCE"
        else:
            basis = f"OCCURRENCE_ONLY_{self.approval_status}"
        return {"authority_verified": self.authority_verified, "occurrence_verified": True,
                "approval_status": self.approval_status, "applicability": self.applicability, "basis": basis,
                "kind": self.kind}

    def to_dict(self) -> dict:
        return asdict(self)


def _make_id(*parts: str) -> str:
    return ID_PREFIX + hashlib.sha256("\u001f".join(parts).encode("utf-8")).hexdigest()[:12]


class EvidenceRegistry:
    """Evidence bound for one challenge run: the reviewed document, the reference index, supplied policies."""

    def __init__(self):
        self._items: dict[str, EvidenceItem] = {}
        self._doc: dict | None = None
        self.index = None
        self._basis: dict[str, list[str]] = {}
        self._modes: dict[str, str] = {}
        self._task_cache: dict[str, tuple[frozenset, ...]] = {}

    # ----------------------------------------------------------- document
    def add_document_text(self, path_or_text: str | Path, name: str | None = None) -> dict:
        """Index the reviewed document by paragraph (a .docx/.txt path, or the text itself)."""
        source = str(path_or_text)
        p = Path(source) if len(source) < 400 and "\n" not in source else None
        if p is not None and p.is_file():
            if p.suffix.lower() == ".docx":
                from .reference_verify import load_source_text
                text = load_source_text(p)
            else:
                text = p.read_text(encoding="utf-8")
            file_name = name or p.name
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            text = source
            file_name = name or "reviewed-document.txt"
            digest = sha_text(text)
        paragraphs = [nfc(x) for x in text.splitlines() if x.strip()]
        keys = [norm(x) for x in paragraphs]
        lam = [lam_alef_insensitive(x) for x in paragraphs]
        self._doc = {"name": file_name, "sha256": digest, "paragraphs": paragraphs, "keys": keys, "lam": lam}
        return {"name": file_name, "sha256": digest, "paragraphs": len(paragraphs)}

    @property
    def document(self) -> dict | None:
        return None if self._doc is None else {"name": self._doc["name"], "sha256": self._doc["sha256"],
                                               "paragraphs": len(self._doc["paragraphs"])}

    def document_paragraphs(self) -> list[str]:
        return list(self._doc["paragraphs"]) if self._doc else []

    def _locate(self, needle_key: str, keys: list[str]) -> int | None:
        """Paragraph index holding ``needle_key``; a needle spanning paragraphs maps to its first one."""
        for i, k in enumerate(keys):
            if needle_key and needle_key in k:
                return i
        joined = " ".join(keys)
        pos = joined.find(needle_key) if needle_key else -1
        if pos < 0:
            return None
        offset = 0
        for i, k in enumerate(keys):
            if pos < offset + len(k):
                return i
            offset += len(k) + 1
        return None

    def bind_clause(self, quote) -> EvidenceItem | None:
        """Find a quoted passage in the reviewed document (NFC, whitespace and lam-alef tolerant)."""
        if self._doc is None:
            return None
        from ..model.entities import plain_text
        q = _ELLIPSIS.sub(" ", plain_text(quote)).strip(" \"'«»“”")
        needle = norm(q)
        if len(needle) < MIN_QUOTE_CHARS:
            return None
        idx = self._locate(needle, self._doc["keys"])
        mode = "NORMALIZED"
        if idx is None and len(needle) >= 3 * MIN_QUOTE_CHARS:
            idx = self._locate(lam_alef_insensitive(q), self._doc["lam"])
            mode = "LAM_ALEF_INSENSITIVE"
        if idx is None:
            return None
        para = self._doc["paragraphs"][idx]
        item = EvidenceItem(_make_id("DOCUMENT", self._doc["sha256"], str(idx), q), "DOCUMENT", self._doc["name"],
                            self._doc["sha256"], f"¶{idx + 1}", _excerpt(para), "reviewed", DOCUMENT_STATUS,
                            APPLICABILITY_DEFAULT)
        self._items.setdefault(item.id, item)
        self._modes[item.id] = mode
        return self._items[item.id]

    def bind_document(self) -> EvidenceItem | None:
        """Evidence that the whole hashed document was searched (cited when a quote is not found)."""
        if self._doc is None:
            return None
        first = self._doc["paragraphs"][0] if self._doc["paragraphs"] else ""
        item = EvidenceItem(_make_id("DOCUMENT", self._doc["sha256"], "WHOLE"), "DOCUMENT", self._doc["name"],
                            self._doc["sha256"], f"¶1–¶{len(self._doc['paragraphs'])}",
                            _excerpt(f"[النص الكامل، {len(self._doc['paragraphs'])} فقرة] {first}"), "reviewed",
                            DOCUMENT_STATUS, APPLICABILITY_DEFAULT)
        return self._items.setdefault(item.id, item)

    def match_mode(self, evidence_id: str) -> str | None:
        return self._modes.get(evidence_id)

    # ---------------------------------------------------------- references
    def add_reference_index(self, index) -> None:
        self.index = index

    def _matrix_status(self) -> str:
        src = (self.index.sources or {}).get("authority_matrix") if self.index else None
        return src.approval_status if src else "UNVERIFIED"

    def _org_status(self) -> str:
        src = (self.index.sources or {}).get("org_structure") if self.index else None
        return src.approval_status if src else "PROPOSED_NOT_APPROVED"

    def _matrix_file(self) -> tuple[str, str]:
        src = (self.index.sources or {}).get("authority_matrix") if self.index else None
        return (src.file, src.computed_sha256 or src.recorded_sha256 or "") if src else ("", "")

    def _org_file(self) -> tuple[str, str]:
        src = (self.index.sources or {}).get("org_structure") if self.index else None
        return (src.file, src.computed_sha256 or src.recorded_sha256 or "") if src else ("", "")

    def matrix_items_for(self, matter_keyword: str) -> list:
        """Matrix items for a matter: the index's loose search first, then title-word overlap (deterministic)."""
        if self.index is None or not matter_keyword or not matter_keyword.strip():
            return []
        found = self.index.matrix.find_items(matter_keyword)
        if found:
            return sorted(found, key=lambda it: it.sort_key())
        hit = self.find_matter(matter_keyword)
        return [hit] if hit else []

    def find_matter(self, text: str):
        """Best matrix item whose title words occur in ``text`` (at least two words and half the title)."""
        if self.index is None:
            return None
        hay = set(content_words(text))
        best, best_score = None, 0.0
        for it in self.index.matrix.items:
            words = content_words(it.title)
            if len(words) < 2:
                continue
            hits = sum(1 for w in words if w in hay)
            score = hits / len(words)
            if hits >= 2 and score >= 0.5 and (score > best_score or (score == best_score and best is not None
                                                                    and it.sort_key() < best.sort_key())):
                best, best_score = it, score
        return best

    def bind_matrix_item(self, item) -> EvidenceItem:
        """Evidence for one matrix item: number, title, page and the roles it names (status as recorded)."""
        file, digest = self._matrix_file()
        roles = "؛ ".join(f"{b}: {r}" for b, r in item.roles.items())
        text = f"البند {item.number} ({item.category}): {item.title} — {roles}"
        ev = EvidenceItem(_make_id("REFERENCE_MATRIX", digest, item.number), "REFERENCE_MATRIX", file, digest,
                          f"p.{item.page}", _excerpt(text), MATRIX_VERSION, self._matrix_status())
        return self._items.setdefault(ev.id, ev)

    def bind_authority(self, body_name: str, matter_keyword: str) -> EvidenceItem | None:
        """Matrix item where ``body_name`` holds a role for the matter; None when the matrix is silent."""
        from ..references.authority_matrix import canonical_body
        body = canonical_body(body_name) if body_name else None
        if body is None:
            return None
        for it in self.matrix_items_for(matter_keyword):
            if body in it.roles:
                return self.bind_matrix_item(it)
        return None

    def bind_source_status(self, key: str) -> EvidenceItem | None:
        """Evidence of a source's recorded status (org_structure | authority_matrix) from the register."""
        if self.index is None or key not in (self.index.sources or {}):
            return None
        src = self.index.sources[key]
        kind = "REFERENCE_ORG" if key == "org_structure" else "REFERENCE_MATRIX"
        text = (f"سجل المصادر: {src.file} — approval_status={src.approval_status}; "
                f"approval_evidence={src.approval_evidence}; hash={src.hash_status}; applicability={src.applicability}")
        ev = EvidenceItem(_make_id(kind, src.computed_sha256 or "", "STATUS"), kind, src.file,
                          src.computed_sha256 or src.recorded_sha256 or "", "register", _excerpt(text),
                          ORG_VERSION if key == "org_structure" else MATRIX_VERSION, src.approval_status)
        return self._items.setdefault(ev.id, ev)

    def bind_mandate(self, unit_name: str) -> EvidenceItem | None:
        """Mandate page of a unit of the deck (PROPOSED_NOT_APPROVED as recorded); None when not in the index."""
        if self.index is None or not unit_name:
            return None
        m = self.index.org.mandate(unit_name)
        if m is None:
            return None
        file, digest = self._org_file()
        tasks = " | ".join(t for t in m.tasks if t.strip())
        text = f"{m.unit} ({m.sector})، ص.{m.page}: {tasks}"
        ev = EvidenceItem(_make_id("REFERENCE_ORG", digest, m.unit), "REFERENCE_ORG", file, digest, f"p.{m.page}",
                          _excerpt(text), ORG_VERSION, self._org_status())
        return self._items.setdefault(ev.id, ev)

    def mandate_of(self, unit_name: str):
        return self.index.org.mandate(unit_name) if self.index else None

    def task_stems(self, unit_name: str) -> tuple[frozenset, ...]:
        """Content stems of each task of a unit (cached; matching only)."""
        if unit_name not in self._task_cache:
            u = self.index.org.unit(unit_name) if self.index else None
            self._task_cache[unit_name] = tuple(frozenset(content_words(t)) for t in (u.tasks if u else ()) if t.strip())
        return self._task_cache[unit_name]

    def best_task_overlap(self, text: str, unit_name: str) -> tuple[float, int]:
        """(best share of ``text``'s stems found in one task of the unit, that task's index)."""
        words = content_words(text)
        if not words:
            return 0.0, -1
        best, idx = 0.0, -1
        for i, stems in enumerate(self.task_stems(unit_name)):
            score = sum(1 for w in words if w in stems) / len(words)
            if score > best:
                best, idx = score, i
        return best, idx

    # ------------------------------------------------------------- policy
    def add_policy(self, name: str, excerpt: str, *, approval_status: str = "UNVERIFIED",
                   applicability: str = APPLICABILITY_DEFAULT, file: str = "", sha256: str = "",
                   location: str = "", version: str = "") -> EvidenceItem:
        """Register a policy or regulatory provision the caller supplies, with the class the caller states."""
        ev = EvidenceItem(_make_id("POLICY", name, sha256, location, excerpt), "POLICY", file or name, sha256,
                          location or "n/a", _excerpt(excerpt), version or "n/a", approval_status, applicability)
        return self._items.setdefault(ev.id, ev)

    # -------------------------------------------------------------- basis
    def attach_basis(self, observation_id: str, *evidence_ids: str) -> None:
        """Record the evidence an observation relies on (each id must resolve)."""
        for e in evidence_ids:
            self.resolve(e)
            if e not in self._basis.setdefault(observation_id, []):
                self._basis[observation_id].append(e)

    def basis(self, observation_id: str) -> list[EvidenceItem]:
        return [self._items[e] for e in self._basis.get(observation_id, [])]

    # ------------------------------------------------------------- access
    def resolve(self, evidence_id: str) -> EvidenceItem:
        if evidence_id not in self._items:
            raise KeyError(f"Unknown evidence id {evidence_id!r}")
        return self._items[evidence_id]

    def has(self, evidence_id: str) -> bool:
        return evidence_id in self._items

    def items(self) -> list[EvidenceItem]:
        return [self._items[k] for k in sorted(self._items)]

    def verifications(self, ids: Iterable[str] | None = None) -> dict[str, dict]:
        keys = sorted(self._items) if ids is None else [i for i in ids if i in self._items]
        return {k: self._items[k].verification() for k in keys}

    def to_dict(self) -> dict:
        return {"schema": "CDF-ADV-EVIDENCE-v7.12", "document": self.document,
                "sources": ({k: v.to_dict() for k, v in self.index.sources.items()} if self.index else {}),
                "items": [it.to_dict() for it in self.items()],
                "basis": {k: list(v) for k, v in sorted(self._basis.items())},
                "note": ("Binding proves occurrence in the hashed text only; approval classes are carried from the "
                         "source register and never upgraded; applicability is NOT_ESTABLISHED unless stated.")}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
