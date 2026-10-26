"""Hosted synthetic demo: seed the fictional cases once and grant them to the listed reviewers.

Runs at API start in HOSTED_SYNTHETIC_DEMO mode (CDF_HOSTED_SEED=0 turns it off). Idempotent: an existing case is
never replaced or appended to, a concurrent start that loses the race is ignored, and grants are inserted with
ON CONFLICT DO NOTHING. Only SYN- cases exist in this database (bind_public_database refuses anything else).
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)


def _load(relative: str):
    spec = importlib.util.spec_from_file_location("cdf_seed_" + Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_and_grant(database, reviewers) -> list[str]:
    if os.getenv("CDF_HOSTED_SEED", "1") == "0":
        return []
    for relative, call in (("tools/seed_visual_demo.py", lambda m: m.seed(database)),
                           ("tools/mat_dna/seed_calibration_demo.py", None)):
        try:
            module = _load(relative)
            if call:
                call(module)
            else:
                _seed_calibration(module, database)
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:   # a concurrent start seeded it first
            log.info("seed %s skipped: %s", relative, type(exc).__name__)
    from ..calibration.store import CalibrationStore

    store = CalibrationStore(database)
    try:
        cases = [r[0] for r in store.db.execute("SELECT case_id FROM cases WHERE case_id LIKE 'SYN-%'")]
        with store.transaction():
            for reviewer in reviewers.values():
                for case_id in cases:
                    store.db.execute("INSERT INTO case_grants (case_id, reviewer_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                                     (case_id, reviewer.principal_id))
        return cases
    finally:
        store.close()


def _seed_calibration(module, database):
    from ..calibration.store import CalibrationStore, ReviewerContext

    store = CalibrationStore(database)
    try:
        if store.db.execute("SELECT 1 FROM cases WHERE case_id='SYN-MAT-DEMO-001'").fetchone():
            return
        identity = ReviewerContext("SYNTHETIC_ADMIN", frozenset({"CALIBRATION_ADMIN", "CALIBRATION_REVIEWER",
                                                                 "DNA_RULE_APPROVER"}), True)
        store.import_case("SYN-MAT-DEMO-001", "a" * 64, module.DEMO, identity)
    finally:
        store.close()
