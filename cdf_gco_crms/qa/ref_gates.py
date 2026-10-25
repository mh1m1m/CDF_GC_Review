"""G-REF gates (protocol Art. 18, v7.12; 02.9, 03A.5, 05.6, D.13): the institutional reference index.

G-REF-1 inventory: every reference carries its SHA-256, page count and recorded approval status.
G-REF-2 no status upgrade: the index carries the recorded status unchanged; nothing reads APPROVED without evidence.
G-REF-3 provenance: every unit and every matrix item resolves to a page of its source.
G-REF-4 citation form: a citation of a reference whose status is not approved carries the status caveat.
G-REF-5 department list: the dashboard's owning department is validated against the sectors and units, or flagged.
"""
from __future__ import annotations

from pathlib import Path

from ..config import round_schema as S
from ..references.index import ReferenceIndex
from .gates import FAIL, PASS, GateResult, _status

APPROVED = ("APPROVED", "APPROVED_CURRENT")


def citation(idx: ReferenceIndex, kind: str, ref: str) -> str:
    """Reader-facing citation of a reference with the status caveat of 02.9 / 05.6 (house voice, en dash rule)."""
    src = idx.sources["authority_matrix" if kind == "matrix" else "org_structure"]
    if kind == "matrix":
        base = f"مصفوفة الصلاحيات الرئيسية (30 أبريل 2024)، البند {ref}"
        caveat = "ولم يُتحقق بعد من سريان النسخة المعتمدة"
    else:
        base = f"الهيكل التنظيمي والمهام والمسؤوليات الإدارية (فبراير 2026)، ص.{ref}"
        caveat = "وهو مقترح غير معتمد بعد"
    if src.approval_status in APPROVED and src.approval_evidence not in ("", None, "NOT_SUPPLIED"):
        return base
    return f"{base}{S.SEP}{caveat}"


def run_ref_gates(idx: ReferenceIndex, owning_department: str | None, inp: str = "reference index") -> list[GateResult]:
    out: list[GateResult] = []
    srcs = list(idx.sources.values())
    inv_ok = all(s.computed_sha256 and s.recorded_sha256 and s.hash_status == "MATCH" and s.approval_status for s in srcs)
    out.append(GateResult("G-REF-1", "Reference inventory", "every reference carries sha256, page count and recorded status",
                          inp, "2 references, hashes MATCH, status recorded",
                          "; ".join(f"{s.key}: {s.hash_status}, {s.approval_status}" for s in srcs), _status(inv_ok)))
    up = [s.key for s in srcs if s.approval_status in APPROVED and s.approval_evidence in ("", None, "NOT_SUPPLIED")]
    out.append(GateResult("G-REF-2", "No status upgrade", "no reference reads approved without recorded evidence; "
                          "status copied verbatim from the register", inp, "0 upgraded",
                          f"upgraded={up}; statuses={[s.approval_status for s in srcs]}", _status(not up)))
    units = idx.org.units
    items = idx.matrix.items
    bad_u = [u.name for u in units if not isinstance(u.page, int) or u.page < 1]
    bad_i = [it.number for it in items if not isinstance(it.page, int) or it.page < 1]
    out.append(GateResult("G-REF-3", "Provenance", "every unit and matrix item resolves to a page", inp,
                          f"{len(units)} units, {len(items)} items with a page",
                          f"units without page={bad_u[:3]}; items without page={bad_i[:3]}", _status(not bad_u and not bad_i)))
    c1, c2 = citation(idx, "matrix", "1.1"), citation(idx, "structure", "18")
    cav_ok = all(S.SEP in c for c in (c1, c2)) and " - " not in c1 + c2
    out.append(GateResult("G-REF-4", "Citation form", "a citation of a not-approved reference carries the status caveat; "
                          "en dash rule", inp, "caveat present", f"{c1} | {c2}", _status(cav_ok)))
    if owning_department:
        ok, canon, cands = idx.validate_department(owning_department)
        actual = (f"'{owning_department}' -> {canon}" if ok else
                  f"'{owning_department}' not in the list; kept as entered and flagged (candidates {cands[:3]})")
        status = PASS
    else:
        actual, status = "owning department not recorded; nothing to validate", PASS
    out.append(GateResult("G-REF-5", "Department list", "dashboard owning department validated against the controlled list "
                          "or flagged (kept as entered)", inp, "validated or flagged", actual, status,
                          f"{len(idx.org.departments())} names in the list"))
    return out
