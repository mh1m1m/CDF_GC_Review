"""Assurance modules (v7.12): reference verification, production gate, objection engine.

Ported from the earlier v7.12 batch. A verified citation proves only that a
passage occurs in a source file (never approval or applicability); the
production gate blocks synthetic workbooks presented as institutional and
malformed decision records; the objection engine never lets an objection
override an issued observation without a verified human-decision record.
"""
from .objection_engine import (  # noqa: F401
    FIXTURES, ApprovedTitle, HumanDecision, Objection, SourceEvidence, release_gates, run_fixtures, save_register,
)
from .production_guard import GateDecision, audit_xlsx, check_decision_record, evaluate, evaluate_many  # noqa: F401
from .reference_verify import VerifiedCitation, build_reference_status, load_source_text, norm  # noqa: F401
