"""Independent SQLite workers must serialize audited read/modify/write transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from cdf_gco_crms.calibration.store import CalibrationStore


def test_concurrent_read_modify_write_never_loses_update_or_fails_snapshot_upgrade(
    tmp_path,
):
    path = tmp_path / "synthetic-counter.sqlite"
    first = CalibrationStore(path)
    second = CalibrationStore(path)
    first.db.execute("CREATE TABLE synthetic_counter (value INTEGER NOT NULL)")
    first.db.execute("INSERT INTO synthetic_counter VALUES (0)")
    first.db.commit()
    attempted, finished = Event(), Event()

    def competing_worker():
        attempted.set()
        with second.transaction():
            value = second.db.execute("SELECT value FROM synthetic_counter").fetchone()[
                0
            ]
            second.db.execute("UPDATE synthetic_counter SET value=?", (value + 1,))
        finished.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with first.transaction():
                value = first.db.execute(
                    "SELECT value FROM synthetic_counter"
                ).fetchone()[0]
                future = pool.submit(competing_worker)
                assert attempted.wait(2)
                finished.wait(
                    0.25
                )  # competing WAL writer may commit while a deferred reader is open
                first.db.execute("UPDATE synthetic_counter SET value=?", (value + 1,))
            future.result(timeout=5)
        assert (
            first.db.execute("SELECT value FROM synthetic_counter").fetchone()[0] == 2
        )
    finally:
        first.close()
        second.close()
