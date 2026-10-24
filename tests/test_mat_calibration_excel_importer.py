"""Synthetic XLSX forensic-register ingestion and fail-closed duplicate tests."""
from openpyxl import Workbook
import pytest

from cdf_gco_crms.calibration.excel_importer import preview_xlsx, import_xlsx
from cdf_gco_crms.calibration.store import CalibrationStore, ReviewerContext, CalibrationError


def _workbook(path, duplicate=False):
    book=Workbook()
    sheet=book.active
    sheet.title="Evolution"
    sheet.append(["observation_id","original_text","reviewed_text","observed_change",
                  "original_class","reviewed_class"])
    sheet.append(["SYN-OBS-01","Long recommendation","هل تم اعتماد المنتج؟","CONVERT_TO_QUESTION",
                  "DIRECT_RECOMMENDATION","DIRECT_QUESTION"])
    sheet.append(["SYN-OBS-02","Risk of missing controls","","REMOVED_FROM_VERSION",
                  "DIRECT_RECOMMENDATION",None])
    if duplicate:
        sheet.append(["SYN-OBS-02","Duplicate","","REMOVED_FROM_VERSION","DIRECT_RECOMMENDATION",None])
    book.save(path)
    return path


def test_register_import_preserves_absence_without_withdrawal(tmp_path):
    p=_workbook(tmp_path/"synthetic.xlsx")
    preview=preview_xlsx(p)
    assert preview["row_count"]==2
    assert preview["withdrawal_decisions_verified"]==0
    removed=next(o for o in preview["observations"] if o["observed_change"]=="REMOVED_FROM_VERSION")
    assert removed["manual_review"] and not removed["documented_withdrawal"]
    db=CalibrationStore(tmp_path/"private"/"cal.db")
    admin=ReviewerContext("synthetic-admin",frozenset({"CALIBRATION_ADMIN","CALIBRATION_REVIEWER"}),True)
    result=import_xlsx(db,"SYN-XLSX-001",p,admin)
    assert result["observations"]==2
    assert db.verify_chain("SYN-XLSX-001",admin)
    db.close()


def test_register_import_blocks_duplicate_ids(tmp_path):
    p=_workbook(tmp_path/"duplicate.xlsx",duplicate=True)
    preview=preview_xlsx(p)
    assert preview["exceptions"][0]["code"]=="DUPLICATE_OBSERVATION_ID"
    db=CalibrationStore(tmp_path/"private"/"cal.db")
    admin=ReviewerContext("synthetic-admin",frozenset({"CALIBRATION_ADMIN"}),True)
    with pytest.raises(CalibrationError,match="EVOLUTION_RECONCILIATION_EXCEPTIONS"):
        import_xlsx(db,"SYN-XLSX-002",p,admin)
    db.close()
