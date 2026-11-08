"""CDF–GCO–CRMS workbook engine (kit 1.1.0: one-sheet executive dashboard; kit 1.1.6: protocol v7.15 issued 7 November 2026).

Builds and maintains the requester feedback workbook of the CDF–GCO–CRMS
protocol: the cumulative data sheet (Art. 10) and the executive dashboard
"لوحة المتابعة التنفيذية" (Art. 10.4A) with its calculation block in hidden
columns of the same sheet, the migration of earlier workbooks, Word–Excel
synchronisation checks and the G-DASH quality gates.

The dashboard is a view, never a record (D15): every figure is computed from
the data sheet and checked against the independent Python calculation in
``cdf_gco_crms.analytics``.
"""

PROTOCOL_VERSION = "7.15"
ENGINE_VERSION = "7.15.0"
WORKBOOK_SCHEMA = "CDF-GCO-CRMS/requester-workbook/7.15"
