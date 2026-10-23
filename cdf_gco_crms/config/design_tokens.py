"""Design tokens (protocol Annex D.2, D.7, D.10, D.11, D.12; v7.12 brand library rebase).

Every colour used by the workbook is defined here and nowhere else. Three
families are kept apart:

* brand      – the seven colours printed with their HEX on page 12 "Color
               Library" of the 87-page CDF Design Guide, plus the guide's page
               surface; provenance in ``cdf_gco_crms.branding.brand_tokens``
               (D.11). They dress the structure of the dashboard: identity
               band, page surface, accents, flags.
* semantic   – the closure-status fills of D.2, exactly as every issued
               register paints them (مغلقة #E2EFDA, مغلقة بشرط #DDEBF7,
               يتطلب تعديل #FFF2CC, مفتوحة #FCE4D6, bold black text). The
               dashboard uses the same fills, so a status reads the same on
               both sheets (protocol owner's decision of 23 October 2026,
               AMB-161). Dark tones for status text on white and chart marks
               derive from these fills (D.10).
* protocol   – the fixed workbook palette of D.7 (input, border, placeholder,
               closed-row grey), unchanged since v7.10.

The contrast of every text/background pair actually used is checked by
``cdf_gco_crms.branding.contrast`` (G-UX-04).
"""
from __future__ import annotations

from .round_schema import CLOSED, CLOSED_COND, OPEN, REQUIRES_EDIT

FONT = "Calibri"

# ---------------------------------------------------------------- brand (D.11, guide page 12)
BRAND_INK = "101820"          # Cinder Black
BRAND_WARM_GRAY = "D7D2CB"    # Warm Gray
BRAND_POWDER = "BBDDE6"       # Powder Blue (= the protocol HEADER_CYAN of D.7)
BRAND_WISTFUL = "A5B0E3"      # Wistful Blue
BRAND_YELLOW = "FDD086"       # Chardonnay Yellow
BRAND_SALMON = "FA9370"       # Light Salmon
BRAND_GREEN = "B5E1C4"        # Jetstream Green
BRAND_SURFACE = BRAND_POWDER  # name kept for the modules written in v7.11
PAGE_SURFACE = "F3F3F4"       # page background of the guide (pages 12, 21)
BRAND_LIGHT = "F2F2F2"        # content panels of the identity-applications file (= protocol LIGHT_GRAY)
WHITE = "FFFFFF"

# ---------------------------------------------------------------- protocol (D.7)
HEADER_CYAN = BRAND_POWDER
LIGHT_GRAY = BRAND_LIGHT
TEXT_BLACK = "000000"
INPUT = "FFF9E5"
BORDER = "BFBFBF"
CLOSED_ROW_GRAY = "D9D9D9"     # 10.4 closed-row requester cells / not-yet-raised cells
CLOSED_ROW_TEXT = "595959"     # 10.4 closed-row status text and closed-row guidance (4.96:1 on D9D9D9)
PLACEHOLDER_GRAY = "808080"    # 10.8 placeholder on requester fills (recorded exception, AMB-153)
CLOSED_GUIDE_TEXT = CLOSED_ROW_TEXT

# ---------------------------------------------------------------- semantic (D.2: the fills of every issued register, unchanged)
STATUS_FILL = {
    CLOSED: "E2EFDA",
    CLOSED_COND: "DDEBF7",
    REQUIRES_EDIT: "FFF2CC",
    OPEN: "FCE4D6",
}
ROUND1_OPEN_FILL = LIGHT_GRAY  # 10.4: round-1 مفتوحة means awaiting the first response
# dark tones of the same hues for status text on white (>= 5.8:1) and chart marks; not brand colours
STATUS_TEXT = {
    CLOSED: "375623",
    CLOSED_COND: "1F4E79",
    REQUIRES_EDIT: "7F6000",
    OPEN: "843C0C",
}
STATUS_CHART = STATUS_TEXT                     # marks drawn in a dark tone (bars are filled with the brand fill + ink outline)
CHART_OUTLINE = BRAND_INK                      # 3:1 boundary of every filled chart mark (WCAG 1.4.11)
MOVEMENT_CHART = {"new": "595959", "closed": STATUS_TEXT[CLOSED], "reopened": STATUS_TEXT[OPEN]}
RATE_LINE = BRAND_INK
RATE_MARKER = BRAND_WISTFUL

# ---------------------------------------------------------------- dashboard roles (D.10)
TOP_RULE = BRAND_INK           # 6-pt rule above the identity band
TITLE_BAND = BRAND_WARM_GRAY   # identity band, as the guide's own page header; logo black on it
TITLE_TEXT = BRAND_INK
ACCENT = BRAND_POWDER          # section markers, table headers, selector frames, GCO headers of the data sheet
MUTED_TEXT = "595959"
SECTION_RULE = BRAND_WARM_GRAY
CARD_BORDER = BRAND_WARM_GRAY
CARD_FILL = WHITE
CARD_CAP = {                   # colour cap of each KPI card: the D.2 fill of the status it counts (same as the register)
    "issued": BRAND_POWDER, "closed": STATUS_FILL[CLOSED], "cond": STATUS_FILL[CLOSED_COND],
    "req": STATUS_FILL[REQUIRES_EDIT], "open": STATUS_FILL[OPEN], "rate": BRAND_WARM_GRAY,
}
SELECTOR_FILL = INPUT
SELECTOR_FRAME = BRAND_INK
HISTORIC_BAND = BRAND_YELLOW
DEMO_BAND = BRAND_SALMON
FLAG_REOPENED = BRAND_SALMON
FLAG_STALLED = BRAND_YELLOW
SELECTED_ROW = BRAND_WISTFUL
LABEL_FILL = BRAND_WARM_GRAY   # label column of the detail panel
ZEBRA = "F7F7F7"
LINK = STATUS_TEXT[CLOSED_COND]  # links in the dark blue of مغلقة بشرط (#1F4E79, 10.4:1 on white)
CHART_TEXT = "404040"          # axis and data-label text of the charts (10.1:1 on white)
NOTE_FILL = BRAND_LIGHT        # background of Notes (D.12)
HELP_FILL = BRAND_LIGHT

# font sizes (pt) – the guide's type scale (page 21), nothing below 9 (G-DASH-18)
SZ_TITLE = 24          # H1
SZ_DOC = 14            # Body 1
SZ_SUBTITLE = 10       # Body 3
SZ_SECTION = 16        # H3
SZ_CARD_VALUE = 32     # Display
SZ_CARD_LABEL = 10
SZ_SECONDARY_VALUE = 16
SZ_DETAIL_HEAD = 14
SZ_BODY = 10
SZ_NOTE = 9
MIN_FONT = 9

# legacy alias used by earlier modules
STATUS_TONE = STATUS_CHART
