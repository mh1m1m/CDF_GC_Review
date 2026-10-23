"""Recipient persona for the institutional challenge (Art. 19A.2; decisions 62–69 of decisions_100).

A :class:`RecipientPersona` is the position the objector argues from: the
department that will receive the observation, as the reference index records
it. It is built from the index only (decision 67: official documents fix the
authorities; no practice of the Fund is attributed), it is dated by the
source versions (decision 69), and every authority it exposes carries the
status caveat of the source it comes from:

* the mandate tasks come from the organisational-structure deck, whose
  register status is PROPOSED_NOT_APPROVED (decision 62): proposed
  responsibilities never become a signing or approval authority, so
  ``authority_basis`` always carries "وهو غير معتمد بعد" (03A.5);
* the delegated authorities come from the delegation of authority matrix,
  whose register status is UNVERIFIED (decision 63): each carries
  "ولم يُتحقق من سريانها الحالي" (05.6).

A simulated position is not a management position (19A.2): nothing here is
an owner input. ``may_approve`` returns ``None`` where the matrix is silent;
it never fills a gap by inference (05.6, G-REF-4).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..references.authority_matrix import ROLE_APPROVE, canonical_body
from .evidence import EvidenceItem, EvidenceRegistry
from .objection_engine import APPROVED

ORG_CAVEAT = "وهو غير معتمد بعد"
MATRIX_CAVEAT = "ولم يُتحقق من سريانها الحالي"
MATRIX_NAME = "مصفوفة الصلاحيات الرئيسية (30 أبريل 2024)"
ORG_NAME = "الهيكل التنظيمي المقترح"
OWNER_FALLBACK = "الإدارة صاحبة الطلب"


def org_citation(page: int | None, status: str) -> str:
    """House-voice citation of the deck (03A.5); the caveat is dropped only in an approved class."""
    base = f"وفق {ORG_NAME}، ص.{page if page else '؟'}"
    return base if status in APPROVED else f"{base}، {ORG_CAVEAT}"


def matrix_citation(item_number: str, status: str) -> str:
    """House-voice citation of the matrix (05.6); the caveat is dropped only in an approved class."""
    base = f"{MATRIX_NAME}، البند {item_number}"
    return base if status in APPROVED else f"{base}، {MATRIX_CAVEAT}"


@dataclass
class RecipientPersona:
    """The receiving department as the reference index records it (occurrence only, never approval)."""
    department_input: str
    canonical_unit: str | None
    sector: str | None
    page: int | None
    mandate_tasks: tuple[str, ...]
    status_caveat: str
    matrix_status: str
    candidates: list[str] = field(default_factory=list)
    matrix_body: str | None = None
    source_versions: dict = field(default_factory=dict)
    registry: EvidenceRegistry = field(default_factory=EvidenceRegistry, repr=False)

    @classmethod
    def from_index(cls, index, department_name: str, registry: EvidenceRegistry | None = None,
                   matrix_body: str | None = None) -> "RecipientPersona":
        """Build the persona for a department name; ``matrix_body`` is set only when the caller states it."""
        reg = registry or EvidenceRegistry()
        if reg.index is None:
            reg.add_reference_index(index)
        ok, canonical, candidates = index.validate_department(department_name)
        unit = index.org.unit(canonical) if (ok and canonical) else None
        sector = index.org.sector(canonical) if (ok and canonical and unit is None) else None
        tasks: tuple[str, ...] = tuple(t for t in (unit.tasks if unit else ()) if t.strip())
        page = unit.page if unit else (sector.page if sector else None)
        sector_name = unit.sector if unit else (sector.name if sector else None)
        org = index.sources.get("org_structure")
        mat = index.sources.get("authority_matrix")
        body = canonical_body(matrix_body) if matrix_body else None
        if matrix_body and body is None:
            raise ValueError(f"{matrix_body!r} is not a body of the matrix")
        return cls(department_input=department_name, canonical_unit=canonical if ok else None,
                   sector=sector_name, page=page, mandate_tasks=tasks,
                   status_caveat=org.approval_status if org else "PROPOSED_NOT_APPROVED",
                   matrix_status=mat.approval_status if mat else "UNVERIFIED",
                   candidates=list(candidates), matrix_body=body,
                   source_versions={"org_structure": {"file": org.file if org else "", "hash": org.hash_status if org else "",
                                                      "approval_status": org.approval_status if org else ""},
                                    "authority_matrix": {"file": mat.file if mat else "", "hash": mat.hash_status if mat else "",
                                                         "approval_status": mat.approval_status if mat else ""}},
                   registry=reg)

    # ------------------------------------------------------------ mandate
    @property
    def in_index(self) -> bool:
        return self.canonical_unit is not None

    @property
    def addressee(self) -> str:
        """The name an observation may address (03A.2): the canonical unit, else the owner fallback."""
        return self.canonical_unit or OWNER_FALLBACK

    def mandate_evidence(self) -> EvidenceItem | None:
        return self.registry.bind_mandate(self.canonical_unit) if self.canonical_unit else None

    def owns_task(self, text: str) -> tuple[float, str | None]:
        """Best overlap between ``text`` and one of the persona's mandate tasks (occurrence only)."""
        if not self.canonical_unit:
            return 0.0, None
        score, idx = self.registry.best_task_overlap(text, self.canonical_unit)
        tasks = [t for t in self.mandate_tasks if t.strip()]
        return score, (tasks[idx] if 0 <= idx < len(tasks) else None)

    def other_owners(self, text: str, cutoff: float = 0.5) -> list[tuple[str, str, float, int]]:
        """Units of other sectors whose tasks overlap ``text`` at or above ``cutoff``: (unit, sector, score, page)."""
        index = self.registry.index
        if index is None:
            return []
        out: list[tuple[str, str, float, int]] = []
        for u in index.org.units:
            if u.name == self.canonical_unit or u.sector == self.sector:
                continue
            best, _ = self.registry.best_task_overlap(text, u.name)
            if best >= cutoff:
                out.append((u.name, u.sector, round(best, 3), u.page))
        out.sort(key=lambda x: (-x[2], x[3]))
        return out

    # ---------------------------------------------------------- authority
    def delegated_authorities(self, matter: str) -> list[dict]:
        """What the matrix says about the matter, item by item, each with the matrix's status caveat."""
        out = []
        for it in self.registry.matrix_items_for(matter):
            out.append({"item": it.number, "title": it.title, "page": it.page, "roles": dict(it.roles),
                        "approving_bodies": list(it.bodies_with(ROLE_APPROVE)),
                        "persona_role": it.roles.get(self.matrix_body) if self.matrix_body else None,
                        "status": self.matrix_status, "caveat": matrix_citation(it.number, self.matrix_status),
                        "evidence_id": self.registry.bind_matrix_item(it).id})
        return out

    def may_approve(self, matter: str) -> tuple[bool | None, EvidenceItem | None]:
        """(True/False with the matrix item as evidence) or (None, None) when the matrix holds no item."""
        items = self.registry.matrix_items_for(matter)
        if not items:
            return None, None
        if self.matrix_body:
            for it in items:
                if it.roles.get(self.matrix_body) == ROLE_APPROVE:
                    return True, self.registry.bind_matrix_item(it)
        return False, self.registry.bind_matrix_item(items[0])

    @property
    def authority_basis(self) -> list[str]:
        """Citable basis strings; each one carries its source's caveat while the source is unapproved."""
        out = []
        if self.canonical_unit:
            out.append(f"مهام {self.canonical_unit} {org_citation(self.page, self.status_caveat)}"
                       f" (status: {self.status_caveat}; proposed responsibilities are not a signing authority)")
        else:
            out.append(f"{self.department_input}: ليست ضمن القائمة المضبوطة للفهرس المرجعي؛ تُخاطب بوصفها {OWNER_FALLBACK}")
        out.append(f"{MATRIX_NAME}: {MATRIX_CAVEAT} (status: {self.matrix_status})")
        return out

    def to_dict(self) -> dict:
        return {"department_input": self.department_input, "canonical_unit": self.canonical_unit,
                "sector": self.sector, "page": self.page, "mandate_tasks": list(self.mandate_tasks),
                "status_caveat": self.status_caveat, "matrix_status": self.matrix_status,
                "candidates": list(self.candidates), "matrix_body": self.matrix_body,
                "source_versions": self.source_versions, "authority_basis": self.authority_basis,
                "simulated_position_note": "A simulated recipient position is not a management position (19A.2)."}
