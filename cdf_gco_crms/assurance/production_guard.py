"""Fail-closed production gate for workbook deliverables (read-only; never modifies a file).

Ported from the earlier v7.12 batch (production_guard.py + ooxml_audit.py)
without its package-relative paths. The audit reads the OOXML package with
the standard library only and does not claim Microsoft Excel compatibility.

Two things this gate exists to block:

* a synthetic or demonstration workbook presented as an institutional one
  (gate NOT_SYNTHETIC_AS_INSTITUTIONAL): a file is synthetic when its name
  carries a synthetic marker, when its core properties carry the demo keyword
  the engine writes for ``is_demo`` documents, or when any cell carries the
  demonstration banner of the protocol;
* a human decision record without the declared shape (:func:`check_decision_record`).

The structural gates (visible sheets, dashboard and hidden helper present,
core columns A–E, unique Internal_IDs, no external links) are release-blocking.
OOXML parsing is not an Excel opening test and reference-case verification
and human GCO approval are external facts: unless the caller states them, the
decision stays OPERATIONAL_VALIDATION_PENDING. Passing every gate establishes
nothing about the review content; it is a packaging check.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from ..config import round_schema as S
from ..config import workbook_settings as W

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
}
DEMO_KEYWORD = "بيانات تجريبية"
SYNTHETIC_NAME_MARKERS = ("SYNTHETIC", "DEMO", "SAMPLE", "FIXTURE", "تجريب", "اختبار")

REQUIRED = (
    "VISIBLE_SHEETS", "DASHBOARD_PRESENT", "HELPER_PRESENT", "HELPER_HIDDEN", "CORE_COLUMNS_AE",
    "INTERNAL_ID_UNIQUENESS", "NO_EXTERNAL_LINK_FILES", "NOT_SYNTHETIC_AS_INSTITUTIONAL",
)
# Reported but not release-blocking: the v7.12 engine never writes this label.
INFORMATIONAL = ("TITLE_LED_DASHBOARD", "FORMULAS_PRESENT", "EXCEL365_ACTUAL")

STATUS_INCOMPLETE = "PRODUCTION_ENGINEERING_INCOMPLETE"
STATUS_PENDING = "OPERATIONAL_VALIDATION_PENDING"
STATUS_APPROVED = "OPERATIONALLY_APPROVED"

DECISION_FIELDS = ("decision_id", "observation_id", "decision", "reviewer", "role", "reference", "timestamp",
                   "evidence_ref")
DECISION_VERIFIED = "VERIFIED_HUMAN_RECORD"


# ------------------------------------------------------------------ OOXML audit
def _cell_value(cell, shared: list[str]):
    typ = cell.get("t")
    if typ == "inlineStr":
        return "".join(x.text or "" for x in cell.findall(".//m:t", NS))
    v = cell.find("m:v", NS)
    if v is None:
        return None
    if typ == "s":
        return shared[int(v.text)]
    return v.text


def _rich_text(si) -> str:
    return "".join(t.text or "" for t in si.findall(".//m:t", NS))


def audit_xlsx(path: str | Path) -> dict:
    """Read-only OOXML audit; returns findings per gate and package details."""
    p = Path(path)
    findings: list[dict] = []
    try:
        z = ZipFile(p)
    except (BadZipFile, FileNotFoundError, IsADirectoryError) as exc:
        findings.append({"gate": "PKG_INTEGRITY", "status": "FAIL", "detail": repr(exc)})
        return {"summary": {"FAIL": 1}, "findings": findings, "details": {"file": p.name}}
    with z:
        bad = z.testzip()
        if bad:
            findings.append({"gate": "PKG_INTEGRITY", "status": "FAIL", "detail": bad})
        names_in_pkg = set(z.namelist())
        book = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = [{"name": s.get("name"), "state": s.get("state", "visible"), "id": s.get("{%s}id" % NS["r"])}
                  for s in book.findall(".//m:sheet", NS)]
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {x.get("Id"): x.get("Target") for x in rels}
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names_in_pkg:
            st = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [_rich_text(si) for si in st.findall("m:si", NS)]
        names = [s["name"] for s in sheets]
        visible = [s for s in sheets if s["state"] == "visible"]
        findings.append({"gate": "VISIBLE_SHEETS", "status": "PASS" if len(visible) == 2 else "FAIL", "detail": names})
        findings.append({"gate": "DASHBOARD_PRESENT", "status": "PASS" if W.DASHBOARD_SHEET in names else "FAIL"})
        findings.append({"gate": "HELPER_PRESENT", "status": "PASS" if W.HELPER_SHEET in names else "FAIL"})
        if W.HELPER_SHEET in names:
            helper = next(s for s in sheets if s["name"] == W.HELPER_SHEET)
            findings.append({"gate": "HELPER_HIDDEN", "status": "PASS" if helper["state"] == "hidden" else "FAIL",
                             "detail": helper["state"]})
        else:
            findings.append({"gate": "HELPER_HIDDEN", "status": "FAIL", "detail": "helper sheet missing"})
        observations: list[dict] = []
        dashboard_text: list[str] = []
        header_cells: dict[str, str] = {}
        all_text: list[str] = []
        for s in sheets:
            target = (targets.get(s["id"]) or "").lstrip("/")
            if target.startswith("xl/"):
                target = target[3:]
            part = "xl/" + target
            if part not in names_in_pkg:
                findings.append({"gate": "SHEET_PATH", "status": "FAIL", "detail": s["name"]})
                continue
            root = ET.fromstring(z.read(part))
            cells = {c.get("r"): _cell_value(c, shared) for c in root.findall(".//m:sheetData/m:row/m:c", NS)}
            all_text.extend(str(v) for v in cells.values() if v is not None)
            if s["name"] == W.DASHBOARD_SHEET:
                dashboard_text = [str(v) for v in cells.values() if v is not None]
            elif s["name"] != W.HELPER_SHEET:
                header_cells = {ref: val for ref, val in cells.items() if re.fullmatch(r"[A-Z]+1", ref)}
                by_row: dict[int, dict] = {}
                for ref, val in cells.items():
                    mt = re.fullmatch(r"([A-Z]+)(\d+)", ref)
                    if mt and int(mt.group(2)) >= 2:
                        by_row.setdefault(int(mt.group(2)), {})[mt.group(1)] = val
                observations = [r for r in by_row.values() if r.get("A") is not None]
        actual = [header_cells.get(k + "1") for k in "ABCDE"]
        findings.append({"gate": "CORE_COLUMNS_AE", "status": "PASS" if actual == list(S.FIXED_HEADERS) else "FAIL",
                         "detail": actual})
        ids = [str(o.get("B")) for o in observations]
        findings.append({"gate": "INTERNAL_ID_UNIQUENESS",
                         "status": "PASS" if ids and len(ids) == len(set(ids)) and all(i and i != "None" for i in ids) else "FAIL",
                         "detail": len(ids)})
        findings.append({"gate": "TITLE_LED_DASHBOARD",
                         "status": "PASS" if any("عنوان الملاحظة" in t for t in dashboard_text) else "NOT_VERIFIED"})
        external = [e for e in names_in_pkg if e.startswith("xl/externalLinks/")]
        findings.append({"gate": "NO_EXTERNAL_LINK_FILES", "status": "PASS" if not external else "FAIL",
                         "detail": external})
        formula_total = 0
        for entry in names_in_pkg:
            if entry.startswith("xl/worksheets/sheet") and entry.endswith(".xml"):
                formula_total += len(ET.fromstring(z.read(entry)).findall(".//m:f", NS))
        findings.append({"gate": "FORMULAS_PRESENT", "status": "PASS" if formula_total > 0 else "NOT_VERIFIED",
                         "detail": formula_total})
        findings.append({"gate": "EXCEL365_ACTUAL", "status": "NOT_VERIFIED",
                         "detail": "OOXML parse is not a Microsoft Excel opening test"})
        # synthetic / demonstration markers
        markers = synthetic_markers(p, z, names_in_pkg, all_text)
        findings.append({"gate": "NOT_SYNTHETIC_AS_INSTITUTIONAL", "status": "PASS" if not markers else "FAIL",
                         "detail": markers})
    details = {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "sheets": sheets,
               "observation_count": len(observations), "formula_count": formula_total, "synthetic_markers": markers}
    return {"summary": dict(Counter(f["status"] for f in findings)), "findings": findings, "details": details}


def synthetic_markers(path: Path, z: ZipFile, names_in_pkg: set[str], all_text: list[str]) -> list[str]:
    """Every sign that a workbook is synthetic or a demonstration (empty list = none found)."""
    markers: list[str] = []
    upper = path.name.upper()
    for m in SYNTHETIC_NAME_MARKERS:
        if m.upper() in upper:
            markers.append(f"FILENAME:{m}")
    if "docProps/core.xml" in names_in_pkg:
        core = ET.fromstring(z.read("docProps/core.xml"))
        kw = core.find("cp:keywords", NS)
        if kw is not None and kw.text and DEMO_KEYWORD in kw.text:
            markers.append("CORE_KEYWORDS:" + DEMO_KEYWORD)
    if any(S.DEMO_BANNER in t for t in all_text):
        markers.append("CELL:DEMO_BANNER")
    return markers


# ------------------------------------------------------------------ gate decision
@dataclass(frozen=True)
class GateDecision:
    artifact: str
    status: str
    passed: tuple[str, ...]
    blocked: tuple[str, ...]
    unverified: tuple[str, ...]
    informational: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"artifact": self.artifact, "status": self.status, "passed": list(self.passed),
                "blocked": list(self.blocked), "unverified": list(self.unverified),
                "informational": list(self.informational)}


def evaluate(path: str | Path, *, excel365_verified: bool = False, human_approved: bool = False,
             reference_case_verified: bool = False, declared_institutional: bool = True) -> GateDecision:
    """Gate decision for one workbook (fail-closed).

    ``declared_institutional`` says the file is being presented as an
    institutional deliverable; a synthetic workbook presented that way is
    blocked. With ``declared_institutional=False`` the synthetic gate is
    reported but not blocking (the file is openly a demonstration).
    """
    path = Path(path)
    report = audit_xlsx(path)
    by_gate = {f["gate"]: f["status"] for f in report["findings"]}
    required = list(REQUIRED)
    if not declared_institutional:
        required.remove("NOT_SYNTHETIC_AS_INSTITUTIONAL")
    blocked = tuple(sorted(g for g in required if by_gate.get(g) != "PASS"))
    passed = tuple(sorted(g for g in required if by_gate.get(g) == "PASS"))
    info = tuple(f"{g}={by_gate.get(g, 'ABSENT')}" for g in INFORMATIONAL)
    unverified = tuple(label for label, val in (("MS_EXCEL_365", excel365_verified),
                                                 ("HUMAN_GCO_APPROVAL", human_approved),
                                                 ("ARTICLE_00_8", reference_case_verified)) if not val)
    status = STATUS_INCOMPLETE if blocked else (STATUS_PENDING if unverified else STATUS_APPROVED)
    return GateDecision(str(path), status, passed, blocked, unverified, info)


def evaluate_many(paths, report_path: str | Path, **flags) -> list[dict]:
    results = [evaluate(x, **flags).to_dict() for x in paths]
    p = Path(report_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "CDF-v7.12-PRODUCTION-GATE-1", "results": results},
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return results


# ------------------------------------------------------------------ decision records
def check_decision_record(record: dict) -> list[str]:
    """Problems with a human decision record; an empty list means the declared shape holds.

    The declared shape is the field set of ``objection_engine.HumanDecision``:
    every audit field non-empty, ``verification_status`` equal to
    VERIFIED_HUMAN_RECORD, and a signing key id with a signature. Shape is
    not validity: the signature is checked only by the engine against an
    institution-managed trust store.
    """
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["NOT_A_MAPPING"]
    for f in DECISION_FIELDS:
        v = record.get(f)
        if v is None or not str(v).strip():
            problems.append(f"MISSING:{f}")
    if record.get("verification_status") != DECISION_VERIFIED:
        problems.append("VERIFICATION_STATUS_NOT_VERIFIED_HUMAN_RECORD")
    if not str(record.get("signing_key_id") or "").strip():
        problems.append("MISSING:signing_key_id")
    if not str(record.get("signature_b64") or "").strip():
        problems.append("MISSING:signature_b64")
    unknown = sorted(set(record) - set(DECISION_FIELDS) - {"verification_status", "signing_key_id", "signature_b64"})
    if unknown:
        problems.append("UNDECLARED_FIELDS:" + ",".join(unknown))
    return problems
