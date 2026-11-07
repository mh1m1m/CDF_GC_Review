# Draft export integrity

Word reports are genuine editable DOCX: case/run identifiers, observation IDs, material categories, original finding/recommendation text, fictional DoA/department IDs, evidence IDs and source status, native tables and RTL paragraph/table properties. The existing automated provenance comments and working-copy marks remain intact. Synthetic branding is publication-authorized artwork, not institutional brand approval.

Excel reports retain editable observation records, materiality/recommendation/reference columns, native Executive formulas, a native doughnut chart, materiality/evidence/debate/timeline sheets and source/run provenance. Text cells are explicitly strings to prevent formula injection; only the intentionally constructed metric formula cells are formulas. Structural tests reconcile observation IDs/count and metric fractions. LibreOffice calculateAll runs on a separate copy, whose cached values are compared with backend numerators/denominators; the delivered source hash must remain unchanged.

PDF generation uses stable Writer from the existing DOCX exporter. Acceptance checks genuine PDF bytes, case/run text, page count and actual page rasterization. Excel also gets a rendered preview. Review captures visually; rasterization alone does not prove typography perfection.

Secure retrieval verifies the same stored bytes through CLI, MCP chunks and authenticated browser download. Artifact metadata binds case/job/content hash and state fingerprint. Exports never bypass the central issuance gate.

Limits: native Microsoft Excel is not run; Calc may drop x14 sparkline extensions on resave, so the original is retained. Charts/artwork are labelled appropriately; static gauge artwork is not an interactive or editable native chart. PDF Arabic extraction order may differ from visual order. Private institutional export remains available only through its existing approved in-process workspace, not these public tools.
