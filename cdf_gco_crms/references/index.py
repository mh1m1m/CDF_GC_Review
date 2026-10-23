"""Authority reference layer: the organisational-structure deck and the authority matrix in one index.

The index loads both parsers, carries the approval status of each source
exactly as recorded in ``INSTITUTIONAL-SOURCE-STATUS.json`` (never upgraded by
this code), checks the SHA-256 of each PDF against the recorded hash and
exports the parsed records as JSON with page provenance and a coverage report.

Nothing here establishes authority: extraction proves only that a passage
occurs in a source file, not its legal applicability (recorded as
NOT_ESTABLISHED) nor the approval of the source (PROPOSED_NOT_APPROVED for the
deck, UNVERIFIED for the matrix, as the register records them).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .authority_matrix import MatrixIndex, parse_matrix
from .org_structure import OrgIndex, parse_org_text
from .textnorm import match_key, nfc

APPLICABILITY = "NOT_ESTABLISHED"
HASH_MATCH = "MATCH"
HASH_MISMATCH = "HASH_MISMATCH"
HASH_UNAVAILABLE = "SOURCE_NOT_AVAILABLE"
HASH_NOT_RECORDED = "NO_RECORDED_HASH"
EXPORT_SCHEMA = "CDF-GCO-CRMS/references/7.12"

# Recorded hashes of the two sources (prefixes are enough to find the register entry).
ORG_HASH_PREFIX = "2dac803a"
MATRIX_HASH_PREFIX = "240cad3b"

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORG_TEXT = _ROOT / "sources" / "reference" / "374afc34-______________________________.pdf.txt"
DEFAULT_ORG_PDF = _ROOT / "sources" / "reference" / "CDF - الهيكل التنظيمي والمهام والمسؤوليات (2026-02).pdf"
DEFAULT_MATRIX_PDF = _ROOT / "sources" / "reference" / "CDF - مصفوفة الصلاحيات الرئيسية (2024-04-30).pdf"
DEFAULT_STATUS = _ROOT / "sources" / "v7.12" / "INSTITUTIONAL-SOURCE-STATUS.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class SourceStatus:
    """Status of one source file as carried from the register, plus the hash check.

    ``approval_status`` and ``approval_evidence`` are copied from the register
    verbatim; this layer never raises them. ``hash_status`` is MATCH,
    HASH_MISMATCH, SOURCE_NOT_AVAILABLE or NO_RECORDED_HASH.
    """
    key: str
    file: str
    recorded_name: str | None
    recorded_sha256: str | None
    computed_sha256: str | None
    hash_status: str
    approval_status: str
    approval_evidence: str
    applicability: str = APPLICABILITY
    pages: int | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key, "file": self.file, "recorded_name": self.recorded_name,
            "recorded_sha256": self.recorded_sha256, "computed_sha256": self.computed_sha256,
            "hash_status": self.hash_status, "approval_status": self.approval_status,
            "approval_evidence": self.approval_evidence, "applicability": self.applicability,
            "pages": self.pages,
        }


def _register_entry(register: list[dict], prefix: str) -> dict | None:
    for entry in register:
        if str(entry.get("sha256", "")).startswith(prefix):
            return entry
    return None


def source_status(key: str, pdf: Path | None, register: list[dict], prefix: str, pages: int | None) -> SourceStatus:
    """Carry the register flags for a source and compare the PDF hash; never fails on a mismatch."""
    entry = _register_entry(register, prefix) or {}
    recorded = entry.get("sha256")
    computed = sha256_of(pdf) if pdf and Path(pdf).is_file() else None
    if computed is None:
        hash_status = HASH_UNAVAILABLE
    elif recorded is None:
        hash_status = HASH_NOT_RECORDED
    else:
        hash_status = HASH_MATCH if computed == recorded else HASH_MISMATCH
    return SourceStatus(
        key=key, file=Path(pdf).name if pdf else "", recorded_name=entry.get("name"),
        recorded_sha256=recorded, computed_sha256=computed, hash_status=hash_status,
        approval_status=str(entry.get("approval_status", "UNVERIFIED")),
        approval_evidence=str(entry.get("approval_evidence", "NOT_SUPPLIED")),
        applicability=APPLICABILITY, pages=pages,
    )


@dataclass
class ReferenceIndex:
    """Both reference sources with their carried status flags.

    Everything exposed here is occurrence evidence with page provenance; no
    method asserts applicability or approval.
    """
    org: OrgIndex
    matrix: MatrixIndex
    sources: dict[str, SourceStatus] = field(default_factory=dict)

    @classmethod
    def load(cls, org_text: Path = DEFAULT_ORG_TEXT, org_pdf: Path | None = DEFAULT_ORG_PDF,
             matrix_pdf: Path = DEFAULT_MATRIX_PDF, status_path: Path | None = DEFAULT_STATUS) -> "ReferenceIndex":
        register: list[dict] = []
        if status_path and Path(status_path).is_file():
            register = json.loads(Path(status_path).read_text(encoding="utf-8"))
        org = parse_org_text(org_text)
        matrix = parse_matrix(matrix_pdf)
        sources = {
            "org_structure": source_status("org_structure", org_pdf, register, ORG_HASH_PREFIX, org.pages_total),
            "authority_matrix": source_status("authority_matrix", matrix_pdf, register, MATRIX_HASH_PREFIX,
                                              matrix.pages_total),
        }
        return cls(org, matrix, sources)

    # ----------------------------------------------------------- departments
    def validate_department(self, name: str) -> tuple[bool, str | None, list[str]]:
        """Check a department name for the workbook header field "الإدارة صاحبة الوثيقة".

        Returns ``(ok, canonical_name, candidates)``: ``ok`` when the name
        matches a sector or unit of the deck (NFC, ligature-repaired,
        hamza-folded, with or without a leading "إدارة"/"قطاع"); otherwise the
        closest names as candidates. A match proves occurrence in the deck
        (PROPOSED_NOT_APPROVED), not that the department exists or is approved.
        """
        text = nfc(name)
        if not text:
            return False, None, []
        key = match_key(text)
        for dep in self.org.departments():
            if match_key(dep) == key:
                return True, dep, [dep]
        stripped = key
        for p in ("اداره", "قطاع", "وحده", "مكتب"):
            if key.startswith(p) and len(key) > len(p) + 3:
                stripped = key[len(p):]
                break
        if stripped != key:
            for dep in self.org.departments():
                if match_key(dep) == stripped:
                    return True, dep, [dep]
        unit, candidates = self.org.match(text, cutoff=0.85)
        sector_names = [s.name for s in self.org.sectors]
        for s in sector_names:
            skey = match_key(s)
            if (stripped in skey or skey in stripped) and s not in candidates:
                candidates.insert(0, s)
        if unit is not None:
            return True, unit.name, candidates
        return False, None, candidates[:5]

    # ----------------------------------------------------------------- export
    def coverage(self) -> dict:
        org_units = [u for u in self.org.units if u.tasks]
        return {
            "org_structure": {
                "pages_total": self.org.pages_total,
                "pages_parsed": len(self.org.pages_parsed),
                "sectors": len(self.org.sectors),
                "units": len(self.org.units),
                "units_with_tasks": len(org_units),
                "tasks": sum(len(u.tasks) for u in org_units),
                "departments": len(self.org.departments()),
            },
            "authority_matrix": self.matrix.coverage(),
        }

    def sources_report(self) -> dict:
        return {
            "schema": EXPORT_SCHEMA,
            "note": ("Extraction proves only that a passage occurs in the source file; it establishes neither "
                     "legal applicability (NOT_ESTABLISHED) nor approval. Status flags are carried from "
                     "INSTITUTIONAL-SOURCE-STATUS.json and are never upgraded here."),
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
            "coverage": self.coverage(),
        }

    def export_json(self, out_dir: str | Path) -> dict[str, Path]:
        """Write org_structure.json, authority_matrix.json and reference_sources.json to ``out_dir``."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        org_src = self.sources["org_structure"]
        mat_src = self.sources["authority_matrix"]
        files = {
            "org_structure": out / "org_structure.json",
            "authority_matrix": out / "authority_matrix.json",
            "reference_sources": out / "reference_sources.json",
        }
        org = {"schema": EXPORT_SCHEMA, "approval_status": org_src.approval_status,
               "applicability": APPLICABILITY, "hash_status": org_src.hash_status, **self.org.to_dict()}
        mat = {"schema": EXPORT_SCHEMA, "approval_status": mat_src.approval_status,
               "applicability": APPLICABILITY, "hash_status": mat_src.hash_status, **self.matrix.to_dict()}
        files["org_structure"].write_text(json.dumps(org, ensure_ascii=False, indent=2), encoding="utf-8")
        files["authority_matrix"].write_text(json.dumps(mat, ensure_ascii=False, indent=2), encoding="utf-8")
        files["reference_sources"].write_text(json.dumps(self.sources_report(), ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        return files

    @classmethod
    def from_export(cls, out_dir: str | Path) -> "ReferenceIndex":
        """Rebuild the index from an earlier :meth:`export_json` (round-trip)."""
        out = Path(out_dir)
        org = OrgIndex.from_dict(json.loads((out / "org_structure.json").read_text(encoding="utf-8")))
        mat = MatrixIndex.from_dict(json.loads((out / "authority_matrix.json").read_text(encoding="utf-8")))
        rep = json.loads((out / "reference_sources.json").read_text(encoding="utf-8"))
        sources = {k: SourceStatus(**v) for k, v in rep["sources"].items()}
        return cls(org, mat, sources)
