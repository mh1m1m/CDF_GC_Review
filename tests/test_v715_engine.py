"""v7.15 engine constants and the one-sheet dashboard (10.4A.2, 10.4A.3)."""
import cdf_gco_crms as E
from cdf_gco_crms.config import workbook_settings as W


def test_version_constants_are_v715():
    assert E.PROTOCOL_VERSION == "7.15"
    assert E.ENGINE_VERSION == "7.15.0"
    assert E.WORKBOOK_SCHEMA == "CDF-GCO-CRMS/requester-workbook/7.15"


def test_amendment_gates_report_pass_when_met():
    # v7.15 approved on 7 November 2026: no dashboard gate is capped at NOT_VERIFIED for want of the amendment
    assert W.AMENDMENT_DEPENDENT == ()
    assert W.CALC_FIRST_COL == 18                        # column R
