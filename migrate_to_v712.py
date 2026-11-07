#!/usr/bin/env python3
"""CDF–GCO–CRMS: migrate a v7.10 or v7.11 requester workbook to v7.12 (protocol 10.4A.13).

A v7.10 source keeps its data sheet and loses its print view; a v7.11 source keeps its data sheet and has its
dashboard and helper sheet rebuilt in the v7.12 design (brand library of Annex D.11). No round is appended.

Usage:
    python migrate_to_v712.py SOURCE.xlsx OUTPUT_DIR [--name "اسم المستند"] [--code DOC]
                                   [--version "الإصدار 0.3"] [--department "..."]
                                   [--round-date 1=2026-07-05 --round-date 2=2026-07-26 ...]

The source is never modified. A timestamped backup is written to OUTPUT_DIR/backup, the migrated
workbook is written to OUTPUT_DIR under the same file name (the Word/Excel stem of Art. 09.1 is kept),
and a JSON report is written next to it. Exit code 0 only when every verification passed.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdf_gco_crms.migration.migrate import MigrationError, migrate  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("output_dir")
    ap.add_argument("--name", help="document name (02.4) when the workbook title does not carry it")
    ap.add_argument("--code", help="document code (02.5) when it cannot be read from the Internal_IDs")
    ap.add_argument("--version", help="cover version as recorded (never invented)")
    ap.add_argument("--department", help="owning department as recorded")
    ap.add_argument("--round-date", action="append", default=[], help="N=YYYY-MM-DD, as recorded")
    ap.add_argument("--no-guidance", action="store_true", help="do not add header notes to the data sheet")
    a = ap.parse_args(argv)
    overrides = {k: v for k, v in (("name", a.name), ("code", a.code), ("cover_version", a.version),
                                   ("owning_department", a.department)) if v}
    round_meta = {}
    for item in a.round_date:
        n, d = item.split("=", 1)
        round_meta[int(n)] = {"date": d, "version": None}
    try:
        rep = migrate(a.source, a.output_dir, overrides=overrides, round_meta=round_meta or None,
                      add_guidance=not a.no_guidance)
    except MigrationError as e:
        print(f"MIGRATION ERROR: {e}", file=sys.stderr)
        return 2
    report = Path(a.output_dir) / (Path(a.source).stem + ".migration-report.json")
    report.write_text(rep.to_json(), encoding="utf-8")
    print(rep.to_json())
    return 0 if rep.status == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
