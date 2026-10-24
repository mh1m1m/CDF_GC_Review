"""Export an approved-by-DEMO-reviewer, still PROVISIONAL synthetic MAT profile.

Never use for real CDF documents or institutional endorsement.
Run after compiling a candidate through the local synthetic calibration app.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from cdf_gco_crms.calibration.store import CalibrationStore, ReviewerContext, CalibrationError


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--db", default="build/private/mat-calibration-dev.sqlite")
    ap.add_argument("--case",required=True)
    ap.add_argument("--version",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--confirm-synthetic-only",action="store_true")
    x=ap.parse_args()
    if os.environ.get("CDF_CALIBRATION_MODE")!="SYNTHETIC_LOCAL_DEV" or not x.confirm_synthetic_only:
        raise SystemExit("SYNTHETIC_LOCAL_DEV_AND_EXPLICIT_ACK_REQUIRED")
    if not x.case.startswith("SYN-"):
        raise SystemExit("SYNTHETIC_CASE_ONLY")
    out=Path(x.out).expanduser().absolute()
    permitted=[(ROOT/"private").resolve(),(ROOT/"build"/"private").resolve()]
    if out.is_symlink() or not any(out.is_relative_to(p) for p in permitted):
        raise SystemExit("OUTPUT_MUST_BE_IN_GITIGNORED_PRIVATE_WORKSPACE")
    if out.exists():
        raise SystemExit("OUTPUT_ALREADY_EXISTS: choose another versioned output path")
    st=CalibrationStore(x.db)
    user=ReviewerContext("SYNTHETIC_ADMIN",frozenset({"CALIBRATION_REVIEWER"}),True)
    try:
        p=st.synthetic_profile_document(x.case,x.version,user)
        if not p.get("synthetic") or p.get("human_approval_status")!="NOT_APPROVED":
            raise CalibrationError("EXPECTED_UNAPPROVED_SYNTHETIC_PROFILE")
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf-8")
        if os.name=="posix":os.chmod(out,0o600)
        print("SYNTHETIC_ONLY — unapproved MAT profile exported to authorized local private path")
    finally:
        st.close()


if __name__=="__main__":
    main()
