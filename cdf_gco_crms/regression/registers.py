"""Content of the design registers: brand verification, UX audit, 50-innovation matrix, concepts A–E.

Statuses are stated against what the generated workbook actually contains;
an innovation is IMPLEMENTED only when the demonstration workbook carries it
and a gate or test checks it.
"""
from __future__ import annotations

from ..branding import brand_tokens as BT
from ..branding.contrast import contrast_ratio
from ..config import design_tokens as T

IMPL, PART, NOT = "IMPLEMENTED", "PARTIAL", "NOT_IMPLEMENTED"

# (no, group, title, status, priority, approach, compatibility, performance, governance, validation, limitations)
INNOVATIONS = [
    (1, "A", "Official Brand Token Engine", IMPL, "P1", "config/design_tokens.py holds every colour; branding/brand_tokens.py records the provenance of each brand value: the seven HEX values printed on page 12 of the 87-page CDF Design Guide, re-checked against the rendered swatches (branding/guide_page_check.py)",
     "Native fills and fonts", "None", "Brand, derived and protocol colours kept apart; no invented brand value", "G-UX-01", "Derived dark tones for text and chart marks are recorded as not brand"),
    (2, "A", "Executive Brand Header", IMPL, "P1", "Ink top rule, then the Warm Gray identity band of the guide's own pages carrying the supplied horizontal logo in black, background removed, proportions kept; powder-blue divider under the selectors",
     "Picture in a one-cell anchor", "92 KB image", "Logo used only from the supplied file; never redrawn", "G-UX-02", "The supplied guide states no clear-space measure; a margin of 24 px is applied"),
    (3, "A", "Brand-Consistent KPI Cards", IMPL, "P1", "Six equal two-column white cards on the page surface, each capped with the D.2 fill of the status it counts, the same fill as the register (Powder Blue total, Warm Gray rate); 32 pt values in the dark tone of the status",
     "Merged cells and borders", "None", "Values come from formulas only", "G-UX-19, G-DASH-04", ""),
    (4, "A", "Semantic Status Palette", IMPL, "P1", "Three token families: brand (D.11, structure only), semantic status fills of D.2 shared with the register, protocol (D.7)",
     "Native", "None", "A status reads the same fill on the dashboard and in the register (AMB-161); every colour accompanies its written value", "G-UX-01, G-UX-13", ""),
    (5, "A", "Institutional Typography Hierarchy", IMPL, "P1", "Calibri type scale of the guide's page 21 applied as D.12: title 24, document 14, sections 16, card values 32, body 10, notes 9", "Native", "None",
     "The guide itself names Calibri; the v7.11 conflict with the identity file's Brando Arabic is closed (AMB-150)", "G-UX-03, G-DASH-18", ""),
    (6, "A", "Subtle Brand Motifs", NOT, "P3", "Not built", "", "", "Only pages 12 and 21 of the 87-page guide were supplied as renders; no motif page was seen, so none is invented",
     "—", "Requires the motif pages of the full design guide"),
    (7, "A", "Refined Empty States", IMPL, "P2", "Texts for no observation, empty action list, empty table scope and empty detail panel",
     "Formulas", "None", "No zero shown as a result where nothing exists", "G-DASH-15", ""),
    (8, "A", "Unified Visual Components", IMPL, "P2", "Shared builders for text, formula cells, boxes, sections and status rules (excel/dashboard_writer.py)",
     "Native", "None", "", "G-UX-19", ""),
    (9, "A", "Contrast-Aware Palette", IMPL, "P1", "WCAG contrast computed for every static cell, every dashboard conditional pair and every data-sheet cell painted by a conditional font rule (branding/contrast.py, qa/ux_gates.py)",
     "n/a", "None", "", "G-UX-04", "Placeholder grey #808080 kept on the requester fills (3.75:1 on #FFF9E5, 3.53:1 on #F2F2F2) because 10.8 fixes it; closed-row guidance moved to #595959 (2.80:1 to 4.96:1) (AMB-153)"),
    (10, "A", "Executive Presentation Mode", PART, "P3", "The dashboard itself is the presentation view; print set to A4 portrait, one page wide",
     "Native", "None", "Records untouched", "TEST 16", "No separate mode: a second view would need macros or a duplicate sheet"),
    (11, "B", "Intelligent KPI Hierarchy", IMPL, "P2", "Total, closed, conditional, requires modification, open, rate in reading order; secondary indicators below",
     "Native", "None", "", "G-UX-19", ""),
    (12, "B", "Review Completion Progress", IMPL, "P1", "100 % stacked bar of the four values plus the rate card", "Native bar chart", "None",
     "Readiness text adds that full closure is not approval of the document", "G-DASH-08", ""),
    (13, "B", "Round-over-Round Comparison Cards", IMPL, "P2", "Each card shows its value in the previous round", "Formulas", "None", "", "G-DASH-05", ""),
    (14, "B", "Observation Movement Matrix", IMPL, "P2", "5 × 4 transition matrix between the comparison round and the selected round", "COUNTIFS", "25 formulas", "",
     "G-DASH-05", ""),
    (15, "B", "Reopened Observation Indicator", IMPL, "P1", "Count of reopened rows (state) and events per round; salmon flag in lists", "Formulas", "None",
     "Reopening only after an earlier مغلقة (AMB-141)", "TEST 20, G-DASH-19", ""),
    (16, "B", "Stalled Review Indicator", IMPL, "P1", "SC-50 definition excluding the birth round", "Formulas", "None", "No escalation implied", "TEST 04", ""),
    (17, "B", "Closure Sustainability Measure", IMPL, "P2", "\"x من y شهدت إغلاقاً\" for the selected round", "Formulas", "None",
     "Not presented as proof of control effectiveness", "TEST 20", ""),
    (18, "B", "Review Readiness Panel", IMPL, "P2", "Rule-based categorical readiness", "Formulas", "None", "States that it is not an approval", "G-DASH-05", ""),
    (19, "B", "Executive Narrative Generator", IMPL, "P2", "Two deterministic sentences built by formulas", "Formulas", "None", "No inference beyond the counts",
     "G-DASH-05", ""),
    (20, "B", "Visual History of Review Rounds", IMPL, "P2", "Stacked composition by round, closure-rate line, movement columns", "Native charts", "3 charts",
     "", "G-DASH-08", "Charts show every recorded round"),
    (21, "C", "Adaptive Round-Aware Table", IMPL, "P1", "Fixed eight-column table driven by the selected round", "Formulas", "N rows × 8", "", "TEST 19", ""),
    (22, "C", "Dynamic Column Labels", IMPL, "P2", "Previous/selected status headers follow the selected round", "Formulas", "None", "", "G-DASH-05", ""),
    (23, "C", "Intelligent Column Widths", IMPL, "P2", "Grid of 13-character columns sized for Arabic; data sheet widths per 10.3", "Native", "None", "", "G-DASH-18", ""),
    (24, "C", "Adaptive Row Heights", PART, "P2", "Heights computed at build from the longest content over all rounds, capped", "Native", "None", "",
     "G-UX-06", "Excel cannot refit rows to formula results without macros; some rows keep spare space"),
    (25, "C", "Focused Action View", IMPL, "P1", "Action list (top ten) and the scope \"الملاحظات التي تتطلب إجراء\"", "Formulas", "None",
     "Order is workflow, not severity (AMB-145)", "G-UX-17", ""),
    (26, "C", "Compact Full-History View", IMPL, "P2", "Full table (default scope) plus per-observation timeline", "Formulas", "None", "", "TEST 19", ""),
    (27, "C", "Alternating Row Surfaces", IMPL, "P3", "Conditional zebra and rule only on filled rows", "Conditional formatting", "2 rules", "", "TEST 16", ""),
    (28, "C", "Observation Navigation Links", IMPL, "P1", "HYPERLINK to the row found by Internal_ID", "HYPERLINK, MATCH", "None", "", "TEST 11, G-DASH-06", ""),
    (29, "C", "Selected Observation Highlight", IMPL, "P3", "Conditional fill of the selected number in the table", "Conditional formatting", "1 rule", "", "TEST 16", ""),
    (30, "C", "Cross-Round Consistency Highlights", IMPL, "P2", "Change column flags (reopened, no progress, closed)", "Conditional formatting", "4 rules",
     "Official values untouched", "G-DASH-19", ""),
    (31, "D", "Contextual Cell Notes", IMPL, "P1", "Notes on every visible data-sheet header and on selectors and key labels", "Legacy Notes (VML)", "One note per header",
     "No authority created; claims not presented as verified", "G-UX-07, G-UX-08", "Hover display depends on the Excel platform"),
    (32, "D", "Round-Specific Help", IMPL, "P2", "Notes generated per round ordinal; current-round and history wordings", "Notes", "None", "", "G-UX-07", ""),
    (33, "D", "Input Selection Guidance", IMPL, "P1", "Input messages on current response cells, status cells (literal 10.3 text) and selectors",
     "Data validation messages", "None", "", "G-UX-07", "Shown on selection, not on hover"),
    (34, "D", "Example-Based Guidance", IMPL, "P3", "One labelled example in the note and the user guide", "Text", "None",
     "Labelled \"مثال توضيحي (ليس إفادة فعلية)\"", "G-UX-07", ""),
    (35, "D", "Smart Status Definitions", IMPL, "P2", "Status meanings in notes and in the user guide", "Text", "None", "", "G-UX-07", ""),
    (36, "D", "Input Completeness Indicator", IMPL, "P2", "\"الإفادة عن n ملاحظة غير مغلقة (أُدخلت x)\" counts real entries live", "Formulas", "None",
     "Placeholders and closed-row guidance are not counted", "G-UX-18", ""),
    (37, "D", "Read-Only Field Cues", PART, "P2", "GCO headers in brand cyan, owner headers grey; notes say \"للعرض فقط\"", "Native", "None",
     "The data sheet is not locked (10.4 forbids protection)", "G-UX-07", "Cells stay editable by design; edits are caught on return (10.6)"),
    (38, "D", "Closed-Row Guidance", IMPL, "P1", "10.2 prefill plus an input message on closed rows' response cells", "Data validation", "None",
     "Dispute path preserved (10.6)", "TEST 02", ""),
    (39, "D", "Contextual Error Prevention", IMPL, "P2", "Stop alerts with messages on every list; selectors restricted to lists", "Data validation", "None", "",
     "G-UX-09", ""),
    (40, "D", "Interactive Help Center", IMPL, "P2", "User guide zone and navigation row", "Text and links", "None", "", "G-UX-18", ""),
    (41, "E", "Observation Detail Panel", IMPL, "P1", "Status, locations, observation, latest feedback, action, latest owner response and claim, closure basis",
     "Formulas", "None", "No Internal_ID shown", "TEST 19", ""),
    (42, "E", "Observation Lifecycle Timeline", IMPL, "P2", "One row per round up to the selected one", "Formulas", "R rows", "", "TEST 20", ""),
    (43, "E", "Conditional Closure Tracker", PART, "P2", "Conditional rows in the action list with the \"شرط الإغلاق:\" text; scope filter", "Formulas", "None",
     "", "TEST 02", "The fulfilment of a condition is not a recorded field; tracking it needs a register field"),
    (44, "E", "Action Queue", IMPL, "P1", "Ordered list with reason, status, action and link", "SMALL/MATCH", "None", "No deadline invented", "G-DASH-05", ""),
    (45, "E", "Executive Comparison Mode", IMPL, "P2", "Comparison-round selector and transition matrix", "Formulas", "None", "", "G-DASH-05", ""),
    (46, "E", "Status Distribution Visualization", IMPL, "P1", "Native 100 % stacked bar, values labelled", "Native chart", "1 chart", "", "G-DASH-08", ""),
    (47, "E", "One-Click Review Navigation", IMPL, "P1", "Links to each zone, to the current input column and to each row", "Internal hyperlinks", "None", "",
     "G-UX-18, G-DASH-06", ""),
    (48, "E", "Responsive Desktop Layout Strategy", PART, "P2", "Fixed grid within a laptop width budget; rendered and inspected at one size", "Native", "None", "",
     "G-DASH-18", "A worksheet is not responsive; other zoom levels were not rendered"),
    (49, "E", "Accessible Visual Language", IMPL, "P1", "Every colour accompanies a written value", "Native", "None", "", "G-UX-04, G-UX-13", ""),
    (50, "E", "Premium Executive Workbook Experience", IMPL, "P1", "Opening view states the document, round, progress, outstanding items and next action",
     "Native", "None", "", "G-UX-18, manual inspection", "Judged on LibreOffice renders; Excel rendering not verified"),
]

CONCEPTS = [
    ("A", "Interactive Observation Journey", IMPL, "Delivered as the detail panel's timeline (41, 42)."),
    ("B", "Smart Review Health Indicator", IMPL, "Delivered as review readiness and the input-completeness line; states that it is not a compliance status."),
    ("C", "Executive Decision Focus", NOT, "Rows awaiting an authorised decision (risk acceptance, GCO reassessment) are register workflow statuses (17.3) "
                                          "that the requester workbook does not carry; showing them would cross the information boundary. Proposed for the internal register dashboard."),
    ("D", "Intelligent Navigation Map", PART, "A navigation row links every zone and the input column; no diagram is drawn."),
    ("E", "Design System Self-Audit", IMPL, "qa/ux_gates.py checks colours against the tokens, fonts, contrast and component consistency (G-UX-01, 03, 04, 19)."),
]

UX_AUDIT = [
    # component, before (v7.10 print view / earlier prototype), brand alignment, issue, redesign, priority, evidence
    ("Workbook opening view", "v7.10: opens on the data sheet of 24+ columns; prototype: opens on a dark band without content", "Partial",
     "No answer to \"where do we stand and what must we do\" on opening", "Opens on the dashboard, first screen states round, counts and the required action", "P1",
     "screenshots/before_v710_printview.png; before_prototype.png; after_dashboard_round5_p1.png"),
    ("Dashboard heading", "v7.11: Powder Blue band #BBDDE6 with the black logo; prototype: full-width #101820 bar with white text", "Partial (v7.11 used a verified colour, but not the guide's own header)",
     "The guide's pages carry a Warm Gray header band; v7.11 chose the surface colour instead", "Ink top rule, Warm Gray band #D7D2CB with the black logo, title 24 pt, document name 14 pt", "P1", "after_dashboard_round5_p1.png"),
    ("Logo", "None in either version", "Missing", "No institutional identity", "Supplied logo, proportions kept (G-UX-02)", "P1", "after_dashboard_round5_p1.png"),
    ("KPI cards", "v7.11: six white cards with a dark top rule; prototype: two cards (total, closed)", "Partial", "v7.11 cards carried no brand colour; the page had no surface", "Six cards capped in the D.2 fill of their status, the register's own colours, on a #F3F3F4 page surface, 32 pt values", "P1", "after_dashboard_round5_p1.png"),
    ("Review-round selector", "Prototype: numeric cell \"3\" without list", "n/a", "Free typing; no validation; no historic band",
     "Four validated selectors with Notes and input messages; historic band", "P2", ""),
    ("Observation table", "v7.10: full register copy; prototype: number, location, summary, status", "n/a",
     "No change or action column; no link", "Eight fixed columns, adaptive headers, links", "P1", ""),
    ("Column headers", "v7.10: cyan/grey per role", "Aligned (cyan is a brand colour, D.11)", "No explanation of each column", "Notes on every header per round", "P1", ""),
    ("Status formatting", "D.2 fills E2EFDA/DDEBF7/FFF2CC/FCE4D6 in the register; v7.11 dashboard used the same", "Semantic (kept)", "Colour alone in the prototype legend", "Kept exactly as the issued registers on both sheets (AMB-161); cards capped in the same fills; value always written beside the colour", "P1", ""),
    ("Response-entry cells", "Placeholders (10.8)", "Protocol", "No selection-time guidance on response cells", "Input messages on current response cells; closed-row message", "P1", ""),
    ("Navigation", "None", "n/a", "Reader must scroll and search", "Navigation row and per-row links", "P2", ""),
    ("Charts", "v7.11: dark Office tones; none (v7.10)", "Partial", "Chart marks in colours outside the brand", "Marks filled with the D.2 status fills of the register and outlined in ink (3:1 boundary); rate line in ink with Wistful Blue markers", "P2", "after_dashboard_round5_p2.png"),
    ("Guidance", "Transmittal text only", "n/a", "Rules live outside the file", "User guide zone, Notes, input messages", "P1", ""),
    ("Historical review blocks", "All blocks expanded; print view shows the latest two", "n/a", "Wide sheet", "Older blocks grouped (expanded) for one-click collapse", "P2", ""),
    ("Print settings", "Print view sheet, A4 landscape", "n/a", "Extra sheet to maintain", "Dashboard prints A4 portrait one page wide; data sheet prints with grouped columns", "P3", ""),
    ("Footer", "None", "n/a", "—", "Not added: the guide's legal footer is a logo variant, not supplied as a file", "P3", ""),
    ("Empty states", "Not handled (errors or blanks)", "n/a", "Broken-looking dashboard when empty", "Explicit empty-state texts (G-DASH-15)", "P2", ""),
]


def brand_rows(guide_report=None) -> list[list]:
    rows = []
    for t in BT.BRAND_TOKENS + BT.SEMANTIC_FILLS + BT.DERIVED_TONES + BT.SUPERSEDED_CONVERSIONS + BT.UNVERIFIED_CLAIMS:
        rows.append([t.name, "#" + t.hex, t.verification, t.source, t.page, t.use, t.note])
    rows.append(["typography", "Calibri (guide page 21)", "STATED_IN_GUIDE", BT.GUIDE_87, "page 21",
                 "every cell, chart text and Note", BT.TYPOGRAPHY_FINDING])
    rows.append(["logo", "official horizontal logo (supplied image)", "SUPPLIED_FILE", "image sent on 23 October 2026",
                 "—", "dashboard identity band", BT.LOGO_FINDING])
    return rows


def contrast_rows() -> list[list]:
    pairs = [
        ("Title text on the identity band", T.BRAND_INK, T.TITLE_BAND), ("Fund line on the identity band", T.MUTED_TEXT, T.TITLE_BAND),
        ("Body on white", T.BRAND_INK, T.WHITE), ("Body on the page surface", T.BRAND_INK, T.PAGE_SURFACE),
        ("Muted labels on white", T.MUTED_TEXT, T.WHITE), ("Muted labels on the page surface", T.MUTED_TEXT, T.PAGE_SURFACE),
        ("Card cap: total (Powder Blue)", T.BRAND_INK, T.CARD_CAP["issued"]), ("Card cap: closed (D.2)", T.BRAND_INK, T.CARD_CAP["closed"]),
        ("Card cap: conditional (D.2)", T.BRAND_INK, T.CARD_CAP["cond"]), ("Card cap: requires modification (D.2)", T.BRAND_INK, T.CARD_CAP["req"]),
        ("Card cap: open (D.2)", T.BRAND_INK, T.CARD_CAP["open"]), ("Card cap: rate (Warm Gray)", T.BRAND_INK, T.CARD_CAP["rate"]),
        ("Detail labels on Warm Gray", T.BRAND_INK, T.LABEL_FILL), ("Table headers on Powder Blue", T.BRAND_INK, T.ACCENT),
        ("Closed card value", T.STATUS_TEXT["مغلقة"], T.WHITE), ("Conditional card value", T.STATUS_TEXT["مغلقة بشرط"], T.WHITE),
        ("Requires-modification card value", T.STATUS_TEXT["يتطلب تعديل"], T.WHITE), ("Open card value", T.STATUS_TEXT["مفتوحة"], T.WHITE),
        ("Text on مغلقة fill", T.BRAND_INK, T.STATUS_FILL["مغلقة"]), ("Text on مغلقة بشرط fill", T.BRAND_INK, T.STATUS_FILL["مغلقة بشرط"]),
        ("Text on يتطلب تعديل fill", T.BRAND_INK, T.STATUS_FILL["يتطلب تعديل"]), ("Text on مفتوحة fill", T.BRAND_INK, T.STATUS_FILL["مفتوحة"]),
        ("Reopened flag", T.BRAND_INK, T.FLAG_REOPENED), ("Stalled flag / historic band", T.BRAND_INK, T.FLAG_STALLED),
        ("Selected observation", T.BRAND_INK, T.SELECTED_ROW), ("Selector cell", T.BRAND_INK, T.SELECTOR_FILL),
        ("Help text", T.BRAND_INK, T.HELP_FILL), ("Closed-row status (9 pt)", T.CLOSED_ROW_TEXT, T.CLOSED_ROW_GRAY),
        ("Closed-row guidance (v7.11; was #808080 = 2.80:1)", T.CLOSED_GUIDE_TEXT, T.CLOSED_ROW_GRAY),
        ("Placeholder (protocol 10.8) on current input", T.PLACEHOLDER_GRAY, T.INPUT),
        ("Placeholder (protocol 10.8) left unanswered in an earlier block", T.PLACEHOLDER_GRAY, T.LIGHT_GRAY),
        ("Chart axis and labels", T.CHART_TEXT, T.WHITE), ("Note text", T.TEXT_BLACK, T.NOTE_FILL),
        ("Links", T.LINK, T.WHITE),
    ]
    out = []
    for name, fg, bg in pairs:
        r = contrast_ratio(fg, bg)
        exc = name.startswith("Placeholder")
        status = "PASS" if r >= 4.5 else ("RECORDED_EXCEPTION" if exc else "FAIL")
        out.append([name, "#" + fg, "#" + bg, round(r, 2), status,
                    "colour fixed by protocol 10.8; italic guidance that disappears on typing (AMB-153)" if exc else ""])
    return out
