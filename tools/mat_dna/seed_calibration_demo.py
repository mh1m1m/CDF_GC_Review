"""Seed fictional MAT calibration observations for LOCAL DEMO ONLY.

Usage:
  python tools/mat_dna/seed_calibration_demo.py --db build/public-demo/mat-calibration-dev.sqlite
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cdf_gco_crms.calibration.store import CalibrationStore, ReviewerContext

DEMO = [
    {"observation_id": "SYN-001",
     "original_text": "نوصي بإعادة كتابة جميع أحكام التفويض لضبط الصلاحيات والإجراءات.",
     "reviewed_text": "هل جرى اعتماد نموذج التفويض من الجهة المختصة؟",
     "observed_change": "CONVERT_TO_QUESTION",
     "material_categories": ["DELEGATED_AUTHORITY"],
     "primary_type_original": "DIRECT_RECOMMENDATION",
     "primary_type_reviewed": "DIRECT_QUESTION"},
    {"observation_id": "SYN-002",
     "original_text": "نوصي بإضافة آلية تفصيلية لتسجيل حالات الاشتباه ومراجعتها واتخاذ الإجراءات.",
     "reviewed_text": None,
     "observed_change": "REMOVED_FROM_VERSION",
     "material_categories": ["AML"],
     "primary_type_original": "DIRECT_RECOMMENDATION",
     "primary_type_reviewed": None},
    {"observation_id": "SYN-003",
     "original_text": "من المهم إضافة مهلة للاستجابة والتبليغ مع تفصيل أثرها.",
     "reviewed_text": "نوصي بتحديد مهلة الاستجابة خلال يوم عمل.",
     "observed_change": "SHORTEN",
     "material_categories": [],
     "primary_type_original": "DIRECT_RECOMMENDATION",
     "primary_type_reviewed": "DIRECT_RECOMMENDATION"},
    {"observation_id": "SYN-004",
     "original_text": "التأكيد على وجود آلية للاستمرارية عند تعطل النظام.",
     "reviewed_text": "التأكيد على وجود آلية للاستمرارية عند تعطل النظام.",
     "observed_change": "KEEP_UNCHANGED",
     "material_categories": ["CONTROL_FAILURE"],
     "primary_type_original": "DIRECT_RECOMMENDATION",
     "primary_type_reviewed": "DIRECT_RECOMMENDATION"},
]
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",default="build/public-demo/mat-calibration-dev.sqlite")
    args=p.parse_args()
    s=CalibrationStore(args.db)
    identity=ReviewerContext("SYNTHETIC_ADMIN",
        frozenset({"CALIBRATION_ADMIN","CALIBRATION_REVIEWER","DNA_RULE_APPROVER"}),True)
    try:
        digest=s.import_case("SYN-MAT-DEMO-001","a"*64,DEMO,identity)
        print("Seeded fictional case SYN-MAT-DEMO-001",digest)
    except Exception as e:
        if "UNIQUE constraint failed: cases.case_id" not in str(e):
            raise
        print("Synthetic demo case already exists; no changes made.")
    finally:
        s.close()

if __name__=="__main__":main()
