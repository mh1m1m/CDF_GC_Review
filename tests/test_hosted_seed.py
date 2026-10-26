"""Hosted seeding is idempotent and grants the demo cases only to listed reviewers."""
import json

from cdf_gco_crms.calibration.store import CalibrationStore
from cdf_gco_crms.interfaces import hosted_auth
from cdf_gco_crms.interfaces.hosted_seed import seed_and_grant

REVIEWERS = hosted_auth.load_reviewers(json.dumps([
    {"email": "owner@example.invalid", "principal_id": "SYN-HOSTED-OWNER", "roles": ["CALIBRATION_ADMIN", "CALIBRATION_REVIEWER"]}]))


def test_seed_twice_and_grant(tmp_path):
    db = tmp_path / "hosted.sqlite"
    first = seed_and_grant(db, REVIEWERS)
    second = seed_and_grant(db, REVIEWERS)
    assert set(first) == set(second) == {"SYN-COMMAND-001", "SYN-MAT-DEMO-001"}
    store = CalibrationStore(db)
    try:
        grants = {r[0] for r in store.db.execute("SELECT case_id FROM case_grants WHERE reviewer_id='SYN-HOSTED-OWNER'")}
        events = store.db.execute("SELECT COUNT(*) FROM events WHERE case_id='SYN-MAT-DEMO-001'").fetchone()[0]
    finally:
        store.close()
    assert grants == set(first) and events == 1, "a second start adds no events to an existing case"
