"""Release authorisation gate (v7.12, 19A.9 / P0 issuance bypass).

One place decides whether a review state may be written as an issuable
requester file. The decision is bound to the *content* that the pre-issue
challenge examined, not to a file name or a command sequence:

  * :func:`state_fingerprint` hashes the document identity, the rounds and the
    substantive content of every observation (location, quote, comment, the
    round cells and the closure basis). Title decisions are excluded: they
    carry their own human-decision proof (``TitleEvidence``, 10.4A.16), so
    approving or issuing titles does not reopen the challenge.
  * ``review`` / ``challenge`` / ``adjudicate`` write a gate record keyed by
    that fingerprint (:func:`record_review`) next to the challenge record.
  * Every issuing command asks :func:`authorize` before it writes. An issue is
    authorised only when a gate record exists for exactly this content, its
    status is CLEAR (no blocker without a verified reviewer decision), the
    challenge record on disk is unaltered and itself clean, its hash chains
    verify, and the review did not run against the SYNTHETIC reference
    fixture (unless the document is a demo).
  * Without authorisation a command refuses (return code 3) unless the caller
    asks for a working copy, which is written under a ``WORKING-COPY`` file
    name with the working-copy marker in its package properties
    (:func:`working_copy_name`, :func:`mark_working_copy_docx`, and the
    ``working_copy`` flag of ``build_workbook``).

The gate is deterministic and offline. It never grants institutional
approval: it only refuses to write an issuable file for content whose
challenge is not cleanly closed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from ..model.entities import ReviewState, plain_text

GATE_SCHEMA = "CDF-RELEASE-GATE-v7.12"
FINGERPRINT_SCHEMA = "CDF-STATE-FP-v7.12"
DEFAULT_GATE_DIR = Path("build/adversarial/gate")
STATUS_CLEAR = "CLEAR"
STATUS_BLOCKED = "BLOCKED"
MODE_SYNTHETIC = "SYNTHETIC"
WORKING_COPY_PREFIX = "INTERNAL_DRAFT__"          # file-name classification of every non-issuable output (PR #2 convention)
WORKING_COPY_SUFFIX = " - WORKING-COPY"            # legacy marker of the first gate release; still recognised, no longer written
WORKING_COPY_MARK = "نسخة عمل غير معتمدة للإصدار — INTERNAL DRAFT, NOT AUTHORISED FOR ISSUE"
WORKING_COPY_KEYWORD = "نسخة عمل"
DRAFT_CLASSIFICATION = "INTERNAL_DRAFT_NOT_APPROVED"

# reasons (stable identifiers for callers and tests)
R_NO_RECORD = "NO_REVIEW_RECORD_FOR_THIS_CONTENT"
R_BLOCKERS = "BLOCKERS_OUTSTANDING"
R_CHAINS = "HASH_CHAINS_NOT_VERIFIED"
R_MISMATCH = "RECORD_DOCUMENT_OR_ROUND_MISMATCH"
R_RECORD_FILE = "CHALLENGE_RECORD_MISSING_OR_ALTERED"
R_RECORD_CONTENT = "CHALLENGE_RECORD_NOT_CLEAN"
R_SYNTHETIC = "SYNTHETIC_REFERENCE_NOT_ISSUABLE"
R_SCHEMA = "GATE_RECORD_SCHEMA_UNKNOWN"
R_PROVIDER_FAILURE = "PROVIDER_FAILURE_IN_REVIEW"
R_FINAL_REVIEW_MISSING = "FINAL_REVIEW_MISSING"
R_FINAL_REVIEW_NOT_READY = "FINAL_REVIEW_NOT_READY"
R_TRUST_STORE_REQUIRED = "TRUST_STORE_REQUIRED_FOR_RECORDED_DECISIONS"
R_DECISION_INVALID = "HUMAN_DECISION_INVALID"
R_DECISION_RECORD_MISSING = "HUMAN_DECISION_RECORD_MISSING"
R_SOURCE_DOCUMENT_MISMATCH = "SOURCE_DOCUMENT_VERSION_MISMATCH"
R_SOURCE_DOCUMENT_REQUIRED = "SOURCE_DOCUMENT_HASH_REQUIRED_FOR_INSTITUTIONAL_ISSUE"
R_FINAL_REVIEW_NOT_LIVE = "FINAL_REVIEW_NOT_LIVE"
R_FINAL_REVIEW_RECEIPT = "FINAL_REVIEW_EXECUTION_RECEIPT_INVALID"
R_FINAL_REVIEW_STATE = "FINAL_REVIEW_BOUND_TO_OTHER_REVIEW_STATE"
R_INDEPENDENCE_NOT_VERIFIED = "AGENT_INDEPENDENCE_NOT_VERIFIED"
R_ATTESTATION_MISSING = "RELEASE_ATTESTATION_MISSING"
R_ATTESTATION_INVALID = "RELEASE_ATTESTATION_INVALID"
PURPOSE_INSTITUTIONAL = "INSTITUTIONAL_ISSUE"
PURPOSE_DEMO = "DEMO_OR_INTERNAL"


# ------------------------------------------------------------------ fingerprint
def _cells(o) -> dict:
    out = {}
    for r in sorted(o.cells):
        c = o.cells[r]
        out[str(r)] = {"closure": plain_text(c.closure), "feedback": plain_text(c.feedback),
                       "response": plain_text(c.response), "impl": plain_text(c.impl)}
    return out


def fingerprint_payload(state: ReviewState) -> dict:
    """The exact content the fingerprint covers (deterministic order, plain text only)."""
    d = state.document
    return {
        "schema": FINGERPRINT_SCHEMA,
        "document": {"name": d.name, "code": d.code, "cover_version": d.cover_version,
                     "owning_department": d.owning_department, "is_demo": bool(d.is_demo)},
        "rounds": [{"number": r.number, "date": r.date, "document_version": r.document_version}
                   for r in sorted(state.rounds, key=lambda r: r.number)],
        "observations": [{"internal_id": o.internal_id, "reader_no": o.reader_no, "birth_round": o.birth_round,
                          "location": plain_text(o.location), "quote": plain_text(o.quote),
                          "comment": plain_text(o.comment), "cells": _cells(o),
                          "closure_basis": {str(k): v for k, v in sorted(o.closure_basis.items())}}
                         for o in sorted(state.observations, key=lambda o: o.internal_id)],
    }


def state_fingerprint(state: ReviewState) -> str:
    payload = json.dumps(fingerprint_payload(state), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ records
def gate_record_path(fingerprint: str, gate_dir=DEFAULT_GATE_DIR) -> Path:
    return Path(gate_dir) / f"{fingerprint}.json"


def record_review(state: ReviewState, record, record_path, *, reference_mode: str, gate_dir=DEFAULT_GATE_DIR,
                  decisions_applied: int = 0, command: str = "review", provider_failures: int = 0,
                  final_review: dict | None = None, human_decisions: list[dict] | None = None,
                  source_document_sha256: str | None = None, execution_summary: dict | None = None,
                  role_execution_proofs: list[dict] | None = None, independence: dict | None = None,
                  trace_path: str | None = None, attestation: dict | None = None) -> dict:
    """Write the gate record of a challenge run for the content of ``state`` (overwrites the previous one).

    ``final_review`` is ``{"recommendation": READY|NOT_READY|READY_WITH_CONDITIONS, "mode": LIVE|DETERMINISTIC|...,
    "execution_id": ..., "status": OK|...}`` from the independent final reviewer; ``human_decisions`` lists the
    verified decisions relied on (decision_id, signing_key_id, observation_id, timestamp, valid_until,
    review_state_fingerprint, synthetic) so that :func:`authorize` can re-validate them against the trust store
    at issue time; ``provider_failures`` counts agent invocations that failed — any failure blocks.
    """
    record_path = Path(record_path)
    blockers = record.blockers()
    fp = state_fingerprint(state)
    status = STATUS_BLOCKED if (blockers or provider_failures) else STATUS_CLEAR
    rec = {
        "schema": GATE_SCHEMA, "fingerprint": fp, "fingerprint_schema": FINGERPRINT_SCHEMA,
        "document_code": state.document.code, "round": state.current_round, "is_demo": bool(state.document.is_demo),
        "status": status, "blockers": blockers,
        "chains_verified": bool(record.verify_chains()), "chain_hash": record.chain_hash,
        "independence": record.independence, "role_isolation": record.role_isolation,
        "reference_mode": reference_mode, "command": command, "decisions_applied": int(decisions_applied),
        "provider_failures": int(provider_failures), "final_review": final_review,
        "human_decisions": list(human_decisions or []), "source_document_sha256": source_document_sha256,
        "execution_summary": execution_summary,
        "role_execution_proofs": list(role_execution_proofs or []),
        "independence": independence or {"verified": False, "reasons": ["NOT_EVALUATED"], "live_executions": 0},
        "trace_path": trace_path, "attestation": attestation,
        "purpose": PURPOSE_DEMO if state.document.is_demo else PURPOSE_INSTITUTIONAL,
        "challenge_record": str(record_path), "challenge_record_sha256": sha256_file(record_path),
        "recorded_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "note": ("authorisation means only that no blocker stands for exactly this content; "
                 "institutional approval of the issue is a human act outside the engine (19A.9)"),
    }
    out = gate_record_path(fp, gate_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def attach_attestation(fingerprint: str, attestation: dict, gate_dir=DEFAULT_GATE_DIR) -> dict:
    """Store a signed release attestation inside the gate record of ``fingerprint`` (the record stays otherwise unchanged)."""
    p = gate_record_path(fingerprint, gate_dir)
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["attestation"] = attestation
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def load_gate_record(state: ReviewState, gate_dir=DEFAULT_GATE_DIR) -> dict | None:
    p = gate_record_path(state_fingerprint(state), gate_dir)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@dataclass
class Authorization:
    ok: bool
    fingerprint: str
    reasons: list[str] = field(default_factory=list)
    record: dict | None = None

    def to_dict(self) -> dict:
        return {"authorized": self.ok, "fingerprint": self.fingerprint, "reasons": list(self.reasons),
                "gate_record": self.record}


def authorize(state: ReviewState, gate_dir=DEFAULT_GATE_DIR, *, trust_store=None, now: dt.datetime | None = None,
              source_document_sha256: str | None = None, require_final_review: bool = True,
              purpose: str | None = None) -> Authorization:
    """Decide whether the content of ``state`` may be written as an issuable file (see module docstring).

    Beyond the content binding, the gate re-checks at issue time: no provider failure in the review, the
    independent final review is present and READY, every human decision the record relied on is still valid
    (trust store: key status, expiry, role, state binding; synthetic keys never for an institutional document).

    For an INSTITUTIONAL issue (``purpose`` defaults to the document's class: non-demo = institutional) the gate
    additionally requires, from evidence rather than labels: the source document's SHA-256 supplied by the
    caller and equal to the one the review examined; a final review that ran LIVE with a verifiable execution
    receipt in the trace and bound to this review-state fingerprint; verified independence of the challenge
    roles (``independence.verified``); and a release attestation signed by a trust-store key holding the
    RELEASE_ATTESTOR role, bound to this content, in its validity interval. A deterministic or mock READY, a
    forged LIVE label, an omitted source hash or a self-made record never clears an institutional issue.
    """
    from . import attestation as ATT
    fp = state_fingerprint(state)
    rec = load_gate_record(state, gate_dir)
    if rec is None:
        return Authorization(False, fp, [R_NO_RECORD])
    reasons: list[str] = []
    institutional = not state.document.is_demo
    purpose = purpose or (PURPOSE_INSTITUTIONAL if institutional else PURPOSE_DEMO)
    institutional = institutional or purpose == PURPOSE_INSTITUTIONAL
    if rec.get("provider_failures"):
        reasons.append(f"{R_PROVIDER_FAILURE}:{rec['provider_failures']}")
    fr = rec.get("final_review")
    if require_final_review:
        if not fr or fr.get("status", "OK") != "OK":
            reasons.append(R_FINAL_REVIEW_MISSING)
        elif fr.get("recommendation") != "READY":
            reasons.append(f"{R_FINAL_REVIEW_NOT_READY}:{fr.get('recommendation')}")
        elif institutional:
            # Directive 1: the receipt, not the label, proves a live Article 20 review of exactly this content
            if fr.get("mode") != "LIVE":
                reasons.append(f"{R_FINAL_REVIEW_NOT_LIVE}:{fr.get('mode')}")
            problems = ATT.verify_execution_receipt(ATT.load_trace(rec.get("trace_path")), fr.get("execution_id"), ATT.FINAL_ROLE,
                                                    fr.get("response_hash"))
            if problems:
                reasons.append(f"{R_FINAL_REVIEW_RECEIPT}:{'|'.join(problems)}")
            if fr.get("fingerprint") != fp:
                reasons.append(R_FINAL_REVIEW_STATE)
    # Directive 2: the source document is bound, and for an institutional issue its hash is mandatory
    if institutional and not source_document_sha256:
        reasons.append(R_SOURCE_DOCUMENT_REQUIRED)
    if source_document_sha256 and (not rec.get("source_document_sha256") or rec["source_document_sha256"] != source_document_sha256):
        reasons.append(R_SOURCE_DOCUMENT_MISMATCH)
    if institutional:
        # Directive 3: independence from receipts, never from mode labels
        ind = rec.get("independence") or {}
        if not ind.get("verified"):
            reasons.append(f"{R_INDEPENDENCE_NOT_VERIFIED}:{'|'.join(ind.get('reasons') or ['NOT_EVALUATED'])[:200]}")
        # Directive 4: an authenticated attestation binds the local record to an institution-held key
        att = rec.get("attestation")
        if not att:
            reasons.append(R_ATTESTATION_MISSING)
        else:
            problems = ATT.verify(att, trust_store, now=now, fingerprint=fp, document_sha256=rec.get("source_document_sha256"),
                                  challenge_record_sha256=rec.get("challenge_record_sha256"), purpose=PURPOSE_INSTITUTIONAL,
                                  gate_record=rec)
            if problems:
                reasons.append(f"{R_ATTESTATION_INVALID}:{'|'.join(problems)}")
    decisions = rec.get("human_decisions") or []
    if decisions:
        if trust_store is None:
            reasons.append(R_TRUST_STORE_REQUIRED)
        else:
            from ..assurance.objection_engine import HumanDecision
            for d in decisions:
                try:
                    hd = HumanDecision(**{k: d.get(k, "") for k in HumanDecision.__dataclass_fields__})
                except TypeError:
                    reasons.append(f"{R_DECISION_RECORD_MISSING}:{d.get('decision_id')}")
                    continue
                problems = trust_store.check_decision(hd, now=now, fingerprint=fp, institutional=institutional)
                if problems:
                    reasons.append(f"{R_DECISION_INVALID}:{hd.decision_id}:{'|'.join(problems)}")
    if rec.get("schema") != GATE_SCHEMA or rec.get("fingerprint") != fp:
        reasons.append(R_SCHEMA)
    if rec.get("document_code") != state.document.code or rec.get("round") != state.current_round:
        reasons.append(R_MISMATCH)
    if rec.get("status") != STATUS_CLEAR or rec.get("blockers"):
        reasons.append(f"{R_BLOCKERS}:{len(rec.get('blockers') or [])}")
    if rec.get("chains_verified") is not True:
        reasons.append(R_CHAINS)
    if rec.get("reference_mode") == MODE_SYNTHETIC and not state.document.is_demo:
        reasons.append(R_SYNTHETIC)
    path = Path(rec.get("challenge_record", ""))
    if not path.is_file() or sha256_file(path) != rec.get("challenge_record_sha256"):
        reasons.append(R_RECORD_FILE)
    else:
        try:
            chal = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            chal = None
        if (not isinstance(chal, dict) or chal.get("blockers") or chal.get("chains_verified") is not True
                or chal.get("document_code") != state.document.code or chal.get("round") != state.current_round):
            reasons.append(R_RECORD_CONTENT)
    return Authorization(not reasons, fp, reasons, rec)


# ------------------------------------------------------------------ working copies
def working_copy_name(path) -> Path:
    """``name.xlsx`` → ``INTERNAL_DRAFT__name.xlsx`` (idempotent; a legacy ``- WORKING-COPY`` name is re-labelled)."""
    p = Path(path)
    if p.name.startswith(WORKING_COPY_PREFIX):
        return p
    stem = p.stem[:-len(WORKING_COPY_SUFFIX)] if p.stem.endswith(WORKING_COPY_SUFFIX) else p.stem
    return p.with_name(f"{WORKING_COPY_PREFIX}{stem}{p.suffix}")


def official_name(path) -> Path:
    """The issuable file name for a draft name: strips the draft prefix (and the legacy suffix)."""
    p = Path(path)
    name = p.name[len(WORKING_COPY_PREFIX):] if p.name.startswith(WORKING_COPY_PREFIX) else p.name
    q = p.with_name(name)
    if q.stem.endswith(WORKING_COPY_SUFFIX):
        q = q.with_name(f"{q.stem[:-len(WORKING_COPY_SUFFIX)]}{q.suffix}")
    return q


def is_working_copy_name(path) -> bool:
    p = Path(path)
    return p.name.startswith(WORKING_COPY_PREFIX) or p.stem.endswith(WORKING_COPY_SUFFIX)


_CORE_PART = "docProps/core.xml"
_CT_PART = "[Content_Types].xml"
_RELS_PART = "_rels/.rels"
_CORE_CT = "application/vnd.openxmlformats-package.core-properties+xml"
_CORE_REL = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_EMPTY_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<cp:coreProperties xmlns:cp="{_CP}" xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"></cp:coreProperties>'
)


def _set_core_element(xml: str, tag: str, value: str) -> str:
    """Set ``<cp:tag>`` to ``value`` in a core.xml string (replace or append before the closing tag)."""
    pat = re.compile(rf"<cp:{tag}(?:\s[^>]*)?>.*?</cp:{tag}>|<cp:{tag}(?:\s[^>]*)?/>", re.S)
    elem = f"<cp:{tag}>{escape(value)}</cp:{tag}>"
    if pat.search(xml):
        return pat.sub(elem, xml, count=1)
    return xml.replace("</cp:coreProperties>", elem + "</cp:coreProperties>", 1)


def mark_working_copy_docx(path) -> None:
    """Stamp a Word package as a working copy: category and keywords in ``docProps/core.xml``.

    Works at package level so that it applies equally to files produced by ``python-docx`` and to real
    documents annotated by ``comment_document``; every other part is copied byte for byte.
    """
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    core = parts.get(_CORE_PART, _EMPTY_CORE.encode("utf-8")).decode("utf-8")
    core = _set_core_element(core, "category", WORKING_COPY_MARK)
    core = _set_core_element(core, "keywords", WORKING_COPY_KEYWORD)
    if _CORE_PART not in parts:
        ct = parts[_CT_PART].decode("utf-8")
        if "docProps/core.xml" not in ct:
            ct = ct.replace("</Types>", f'<Override PartName="/{_CORE_PART}" ContentType="{_CORE_CT}"/></Types>', 1)
        parts[_CT_PART] = ct.encode("utf-8")
        rels = parts[_RELS_PART].decode("utf-8")
        if _CORE_REL not in rels:
            rels = rels.replace("</Relationships>", f'<Relationship Id="rIdCoreWC" Type="{_CORE_REL}" '
                                                     f'Target="{_CORE_PART}"/></Relationships>', 1)
        parts[_RELS_PART] = rels.encode("utf-8")
    parts[_CORE_PART] = core.encode("utf-8")
    tmp = path.with_name(f".{path.name}.wc.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        names = [i.filename for i in infos]
        for name in names + [n for n in parts if n not in names]:
            z.writestr(name, parts[name])
    tmp.replace(path)


def docx_is_working_copy(path) -> bool:
    with zipfile.ZipFile(path) as z:
        if _CORE_PART not in z.namelist():
            return False
        return WORKING_COPY_MARK in z.read(_CORE_PART).decode("utf-8", "replace")


def xlsx_is_working_copy(path) -> bool:
    with zipfile.ZipFile(path) as z:
        if _CORE_PART not in z.namelist():
            return False
        return WORKING_COPY_MARK in z.read(_CORE_PART).decode("utf-8", "replace")
