"""CDF–GCO–CRMS v7.11 workbook engine.

Builds and maintains the requester feedback workbook of the CDF–GCO–CRMS
protocol: the cumulative data sheet (Art. 10), the executive dashboard
"لوحة المتابعة التنفيذية" (Art. 10.4A) and its hidden helper sheet, the
v7.10-to-v7.11 migration, Word–Excel synchronisation checks and the G-DASH
quality gates.

The dashboard is a view, never a record (D15): every figure is computed from
the data sheet and checked against the independent Python calculation in
``cdf_gco_crms.analytics``.
"""

PROTOCOL_VERSION = "7.12"
ENGINE_VERSION = "7.12.0"
WORKBOOK_SCHEMA = "CDF-GCO-CRMS/requester-workbook/7.12"
