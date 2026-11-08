"""Design tokens (protocol Annex D.2, D.7, D.10, D.11, D.14; kit 1.1.0 one-sheet dashboard, v7.15 draft).

Every colour used by the workbook is defined here and nowhere else, and every one is entered in ``TOKEN_FAMILY``
with its family (G-UX-01). Families:

* structure   – spec 4.1: the dark identity band and gauge deck (DASH_HEADER decision), the page surface, cards,
                Warm Gray borders, Powder Blue section bands, ink, muted text, links, zebra.
* brand       – the seven colours printed with their HEX on page 12 "Color Library" of the 87-page CDF Design Guide
                (provenance in ``cdf_gco_crms.branding.brand_tokens``, D.11).
* status.fill – the closure-status fills of D.2, exactly as every issued register paints them; unchanged (AMB-161).
* status.mark – the brand colour of each status (chart marks, gauge arcs, KPI caps; spec 4.2).
* status.deep – the dark tone of each status for numbers on white (spec 4.2).
* flag/chip   – action-list reasons, delta chips, demonstration and historic bands, transition heat scale (4.3).
* chart       – axis text and dashed gridlines of the charts (spec 7.3).
* protocol    – the fixed workbook palette of D.7/D.8 used by the data sheet, unchanged since v7.10.

One hex may serve several roles (e.g. #D9D9D9 is the closed-row grey of D.7 and ON_DARK_MUTED); each role is
listed. The contrast of every text/background pair in use is checked by ``cdf_gco_crms.branding.contrast``
(G-UX-04) and the pairs of spec 4.6 by G-UX-22.
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

# ---------------------------------------------------------------- protocol (D.7, D.8; data sheet, unchanged)
HEADER_CYAN = BRAND_POWDER
LIGHT_GRAY = BRAND_LIGHT
TEXT_BLACK = "000000"
INPUT = "FFF9E5"
BORDER = "BFBFBF"              # data-sheet cell borders (D.7); the dashboard's card border is CARD_BORDER
CLOSED_ROW_GRAY = "D9D9D9"     # 10.4 closed-row requester cells / not-yet-raised cells
CLOSED_ROW_TEXT = "595959"     # 10.4 closed-row status text and closed-row guidance (4.96:1 on D9D9D9)
PLACEHOLDER_GRAY = "808080"    # 10.8 placeholder on requester fills (recorded exception, AMB-153)
CLOSED_GUIDE_TEXT = CLOSED_ROW_TEXT
NOTE_FILL = BRAND_LIGHT        # background of Notes (D.12)

# ---------------------------------------------------------------- structure (spec 4.1)
BAND_DARK = "161616"           # identity band and gauge-deck ground (the logo file's background, DASH_HEADER)
PANEL_DARK = "232323"          # gauge panels on the deck, separated by 3-pt gutters of BAND_DARK
TRACK_DARK = "3A3A3A"          # unfilled track of the mini gauges (decorative)
ON_DARK = WHITE                # titles and values on dark
ON_DARK_MUTED = "D9D9D9"       # header line on the identity band
ON_DARK_CAPTION = "A6A6A6"     # captions and scale labels on panels
PAGE = PAGE_SURFACE            # page surface
CARD = WHITE                   # cards, panels, tables
CARD_BORDER = BRAND_WARM_GRAY  # spec token BORDER: Warm Gray card borders, thin
SECTION = BRAND_POWDER         # Powder Blue section bands, table headers, selector frames
INK = BRAND_INK                # Cinder Black text, rules, chart outlines, footer band
MUTED = "595959"               # labels and notes on white (7.0:1)
LINK = "1F4E79"                # links (8.7:1 on white, 6.0:1 on Powder Blue)
ZEBRA = "F7F7F7"               # alternate table rows

# ---------------------------------------------------------------- status families (spec 4.2; D.2 fills unchanged)
STATUS_FILL = {CLOSED: "E2EFDA", CLOSED_COND: "DDEBF7", REQUIRES_EDIT: "FFF2CC", OPEN: "FCE4D6"}
STATUS_MARK = {CLOSED: BRAND_GREEN, CLOSED_COND: BRAND_WISTFUL, REQUIRES_EDIT: BRAND_YELLOW, OPEN: BRAND_SALMON}
STATUS_TEXT = {CLOSED: "375623", CLOSED_COND: "1F4E79", REQUIRES_EDIT: "7F6000", OPEN: "843C0C"}   # deep tones
STATUS_DEEP = STATUS_TEXT
ROUND1_OPEN_FILL = LIGHT_GRAY  # 10.4: round-1 مفتوحة means awaiting the first response (data sheet)
CARD_CAP = {"issued": SECTION, "closed": STATUS_MARK[CLOSED], "cond": STATUS_MARK[CLOSED_COND],
            "req": STATUS_MARK[REQUIRES_EDIT], "open": STATUS_MARK[OPEN], "rate": INK}
KPI_VALUE = {"issued": INK, "closed": STATUS_DEEP[CLOSED], "cond": STATUS_DEEP[CLOSED_COND],
             "req": STATUS_DEEP[REQUIRES_EDIT], "open": STATUS_DEEP[OPEN], "rate": INK}
CHART_OUTLINE = INK            # 0.75-pt boundary of every mark on white (D.10, WCAG 1.4.11)
DECK_SEPARATOR = PANEL_DARK    # 1.25-pt separator of marks on the dark deck
OUTLINE_EMU = 9525             # 0.75 pt
DECK_SEPARATOR_EMU = 15875     # 1.25 pt
LINE_EMU = 28575               # 2.25 pt
RATE_LINE = INK                # closure rate: Cinder, solid, circle markers
IMPL_LINE = LINK               # implementation rate: LINK, dashed, diamond markers

# ---------------------------------------------------------------- flags and chips (spec 4.3)
FLAG_REOPENED = BRAND_SALMON   # reason 1
FLAG_STALLED = BRAND_YELLOW    # reason 2
FLAG_COND = BRAND_WISTFUL      # reason 3 (reasons 4 and 5 have no fill)
CHIP = {"fav": (STATUS_FILL[CLOSED], STATUS_DEEP[CLOSED]), "unfav": (STATUS_FILL[OPEN], STATUS_DEEP[OPEN]),
        "neutral": (PAGE, MUTED)}
DEMO_BAND = BRAND_SALMON
HISTORIC_BAND = BRAND_YELLOW
HEAT_LOW, HEAT_HIGH = WHITE, BRAND_WISTFUL
NOT_RAISED_FILL = PAGE         # matrix row "لم تكن مطروحة"; not-raised pill
CHART_TEXT = "404040"          # axis text (10.1:1 on white)
CHART_GRID = "E3E0DB"          # dashed gridlines of the round charts

# ---------------------------------------------------------------- type (D.14; nothing below 9 pt, G-DASH-18)
SZ_TITLE = 24
SZ_DOC = 14
SZ_SUBTITLE = 10               # header line on the identity band
SZ_SECTION = 16
SZ_CARD_VALUE = 32             # KPI values
SZ_GAUGE = 30
SZ_MINI = 22
SZ_TILE = 20
SZ_SECONDARY_VALUE = 14
SZ_PANEL_TITLE = 12
SZ_FACT = 11
SZ_NARRATIVE = 11
SZ_CHIP = 16                   # card number chip
SZ_DETAIL_HEAD = 14            # card title
SZ_CARD_LABEL = 10
SZ_BODY = 10
SZ_NOTE = 9
MIN_FONT = 9

# ---------------------------------------------------------------- icons (guide pages 17 and 18; spec 4.5)
ICON_DIR = "shared/icons"      # relative to the kit root; <key>-ink.png on light, <key>-white.png on dark
ICON_PX = {"fact": 16, "kpi": 22, "tile": 24, "band": 28}
ICON_SOURCE = "CDF Design Guide (87 pages), rendered at 600 dpi by cdf_gco_crms.branding.icon_extract"
ICONS = {
    "clipboard": {"page": 17, "box": (1007.0, 273.0, 1042.56, 313.0), "xref": 115,
        "meaning": "إجمالي الملاحظات (KPI)",
        "ink": "f718428948c1e36eb6741d42fa789883e1b5528ba6c398f1dcd2c275f1499dd3",
        "white": "fd640dad569cccf1ea3596d1635268708a91ae885daeb085586ba4e6e6b904a3",
        "ink_rgb": "101519", "clean_share": 0.9989, "max_error": 7},
    "check_circle": {"page": 17, "box": (151.0, 1285.0, 191.0, 1325.0), "xref": 231,
        "meaning": "الملاحظات المغلقة (KPI)",
        "ink": "41f73c8083b14eea3970905f13719e938abcae0683ed3898bebc818676891018",
        "white": "1a07775ef9b5ba11c64b4763944991d363efa14722046adb13c5be7edcca1d38",
        "ink_rgb": "0F161A", "clean_share": 0.9991, "max_error": 9},
    "hourglass": {"page": 17, "box": (280.0, 549.0, 306.67, 589.0), "xref": 143,
        "meaning": "مغلقة بشرط (KPI)",
        "ink": "d9337edf4162ee81c4f9e215c78108028384a6722c582a2088fdb837432f6b78",
        "white": "a72dea07d4ce4b66b5ea7f4bc8046f3a6c83edd36b3adb20325de1d582c04b41",
        "ink_rgb": "0E1519", "clean_share": 0.9992, "max_error": 8},
    "pencil": {"page": 17, "box": (273.0, 1377.0, 313.0, 1417.0), "xref": 242,
        "meaning": "يتطلب تعديل (KPI)",
        "ink": "d187bc084cff64458a1bd85b4ff0797fc5e98117379e13124c96968a5e7c912d",
        "white": "a2188f416d14ec8ef769590300ce4ab182d0a023e38fe27bf2b735c6842153c6",
        "ink_rgb": "0F1519", "clean_share": 0.9985, "max_error": 7},
    "clock": {"page": 17, "box": (396.0, 1009.0, 436.0, 1049.0), "xref": 203,
        "meaning": "مفتوحة (KPI)",
        "ink": "cfd21e00c6f35ed7990dd96850dafd23faf6e40c541600d4d8431de41afcce31",
        "white": "481dbc275ed7bc256b16a29660e07a50c73db1fcc19734b717a0bf945efedd0b",
        "ink_rgb": "0E151B", "clean_share": 0.9973, "max_error": 10},
    "gauge": {"page": 17, "box": (1127.0, 917.0, 1167.0, 957.0), "xref": 199,
        "meaning": "نسبة الإغلاق (KPI)",
        "ink": "0c801ed5f15c4897c948b2c02d667f6c2784bd2105eac7d6bb652fed6c13b272",
        "white": "4fb55c85ee613541f022e2f624dc0f2df48be4c0605bbebd52953e1aad3c74b2",
        "ink_rgb": "0F151A", "clean_share": 0.9995, "max_error": 8},
    "grid": {"page": 17, "box": (883.0, 457.0, 922.11, 497.0), "xref": 137,
        "meaning": "الجولة الحالية (fact)",
        "ink": "30eacd40bfc8b20c3570f675532530064b43dd5f772d8b0d28e80657f04ed79a",
        "white": "6dfb6a3603e3345d0b752821c6044cbe6992ec329c36aa0595cc00dcc6923c65",
        "ink_rgb": "0F1519", "clean_share": 0.9967, "max_error": 8},
    "list": {"page": 17, "box": (1001.0, 1837.0, 1049.42, 1877.0), "xref": 298,
        "meaning": "إصدار الوثيقة (fact)",
        "ink": "71c52eb14cf2cfcf07bb625f208d3429cfdafbe54551803142e50b5a441bb396",
        "white": "d9f4ea8a0954875f9e5ace10677a7eff6f0b3166e1934a88da78d5a35c220456",
        "ink_rgb": "0F1419", "clean_share": 0.9982, "max_error": 7},
    "calendar": {"page": 17, "box": (397.0, 2021.0, 437.89, 2061.0), "xref": 313,
        "meaning": "تاريخ آخر مراجعة (fact); أُغلقت خلال الجولة (tile)",
        "ink": "30f1323cab1e1d379368d5de48148fd08056ce5ed3963f147316f7cf34cafb49",
        "white": "6b46133b8589e1f450f233707c3a16ed8aa513d29dea4ef61cdbfc4713bff312",
        "ink_rgb": "0E151A", "clean_share": 0.994, "max_error": 9},
    "home": {"page": 17, "box": (762.0, 1101.0, 802.0, 1141.0), "xref": 216,
        "meaning": "الإدارة صاحبة الوثيقة (fact)",
        "ink": "b4ac756a3c223723d7461d4e75ade2818f218e01eae6b246322124da8d72e05a",
        "white": "101d1999dc713a02ace6b951fbae311758b312bb9c96d1c64fcba7b1d35ac3af",
        "ink_rgb": "0E151A", "clean_share": 0.9998, "max_error": 6},
    "chat": {"page": 17, "box": (637.0, 1377.0, 680.81, 1417.0), "xref": 245,
        "meaning": "المطلوب من الإدارة (fact)",
        "ink": "33a36025c067da74c783889cffdef1203a8ec826d048cb0bb7c401413b2de6de",
        "white": "013a8d2d06b69efcba1abffce1e12062a61bff0f00c2aa6e1a383d86f4f44dc7",
        "ink_rgb": "0E151B", "clean_share": 0.9993, "max_error": 10},
    "route": {"page": 17, "box": (762.0, 3309.0, 802.0, 3349.0), "xref": 458,
        "meaning": "المتعثرة (tile)",
        "ink": "ff2763cf7f9f39702d63ad95def77a69431fcd0f357ddcc199dfa09112d8fe74",
        "white": "8530f150eae6e753d484191ec22e86083bda784cf67fa6c1e0ca9605b48080b1",
        "ink_rgb": "0F151A", "clean_share": 0.9991, "max_error": 10},
    "search": {"page": 17, "box": (273.0, 1561.0, 313.0, 1601.0), "xref": 262,
        "meaning": "المعاد فتحها (tile)",
        "ink": "7f07ae49c5c26ad5d95fcb9aef0816d0b232705effce5f38f25ffa30d61fbd9d",
        "white": "a1f26d0efc6f3566fd9c2585acbc2c9857e4cd295ed41408e11e6429fd9ffb0d",
        "ink_rgb": "0F161B", "clean_share": 0.9997, "max_error": 6},
    "target": {"page": 17, "box": (876.0, 917.0, 928.44, 957.0), "xref": 504,
        "meaning": "جاهزية المراجعة (tile)",
        "ink": "4a775ef6cc14e5ab3606a24223257b88f2031ab7706eb976c4b712599ae76a67",
        "white": "3e9b101ec3edf4cd7e53ad9a691ab0b7ba0300276048a89e123b2ceb92339b31",
        "ink_rgb": "0D1418", "clean_share": 0.9959, "max_error": 8},
    "star": {"page": 18, "box": (153.0, 834.0, 223.0, 904.0), "xref": 909,
        "meaning": "جديدة في الجولة (tile, page 18)",
        "ink": "9b5608f45e670d78b84d6c723d2deaeed290f24cec1bb011d37a727d34a0f2a4",
        "white": "072ee74f8e7488e1964cf3034203b118e0fba8dfc00dbeb6399275a72baf3d9e",
        "ink_rgb": "293039", "clean_share": 0.9982, "max_error": 15},
    "palm": {"page": 18, "box": (427.04, 340.23, 488.58, 401.77), "xref": 895,
        "meaning": "مستوى إغلاق الملاحظات (band)",
        "ink": "a29ee38ac770a285407084ac57894c506462c78ea7d1e8211c1128de3418e58b",
        "white": "eeec0432ec10251193143e5e0d0d495a9041bbdee40fa1638da3b60f02c3823b",
        "ink_rgb": "283039", "clean_share": 0.9985, "max_error": 14},
    "dallah": {"page": 18, "box": (969.35, 672.23, 1026.37, 733.77), "xref": 907,
        "meaning": "الملاحظات التي تتطلب إجراء (band)",
        "ink": "ba7779dba853b3f4049c207a89a9cdd2b579488a394216ae4a6a973da2f05c2e",
        "white": "5f27fbc64ce87289fcc3614dac20964c3ddb3f2f13e42d1af23a4faf8dafa0d5",
        "ink_rgb": "0A121B", "clean_share": 0.9996, "max_error": 10},
    "fort": {"page": 18, "box": (1237.23, 344.85, 1298.77, 397.0), "xref": 898,
        "meaning": "تطور الملاحظات عبر جولات المراجعة (band)",
        "ink": "95daad5888c53a49e0788cedebb277f709a296b991fb35e5fa7c75412e987172",
        "white": "74b10b64ac7b2b7df54d7ef13f763a638f2ebc758d593ac64c1cc50739c35213",
        "ink_rgb": "10161E", "clean_share": 0.9995, "max_error": 10},
    "jar": {"page": 18, "box": (974.73, 340.23, 1020.68, 401.77), "xref": 897,
        "meaning": "جدول الملاحظات (band)",
        "ink": "95dc71fdf73003d1a9cad967566e77cc32c80ea64cf6541b209096d75ef390b2",
        "white": "2b28b232d6524706f053ae19cf5f732ee7256af51c856d510b19b46ca64f9088",
        "ink_rgb": "11151E", "clean_share": 0.9993, "max_error": 8},
    "books": {"page": 18, "box": (1237.23, 676.08, 1298.77, 730.06), "xref": 908,
        "meaning": "دليل الاستخدام (band)",
        "ink": "e0d547c8275371e44e886184381550747b49334a7f643d459687c5967950464b",
        "white": "db971cc9bfdd9b16f4802f7d68fa8566faca241ca77be4a497650cd4d462fd05",
        "ink_rgb": "09121C", "clean_share": 0.9968, "max_error": 10},
    "oud": {"page": 18, "box": (697.62, 345.62, 759.15, 396.61), "xref": 896,
        "meaning": "بطاقات الملاحظات (band)",
        "ink": "c35dcb11853762e38dcbe244f6282ff1dd0f1a5801dbb1a30e3b68c12bd367ba",
        "white": "7a84ea6bf25619f67e3d634acc1b520e14f6ed0a6b3573c1499fda3ffeb2c587",
        "ink_rgb": "09121C", "clean_share": 0.999, "max_error": 11},
}
HUB = {"file": "gauge-hub.png", "sha256": "0ca60c7f81f958e5e0d1a4a16e5021cc3a883874609764aaa255059f154b97b8",
       "source": "generated by the kit: white disc, PANEL_DARK ring, 64 px shown at 16 px (spec 7.1); not a guide icon"}
KPI_ICON = {"issued": "clipboard", "closed": "check_circle", "cond": "hourglass", "req": "pencil", "open": "clock",
            "rate": "gauge"}
FACT_ICON = ("grid", "list", "calendar", "home", "chat")
TILE_ICON = {"stalled": "route", "reopen": "search", "closed_event": "calendar", "new": "star", "ready": "target"}
BAND_ICON = {"closure": "palm", "queue": "dallah", "rounds": "fort", "table": "jar", "help": "books", "cards": "oud"}

# ---------------------------------------------------------------- family register (G-UX-01)
TOKEN_FAMILY: list[tuple[str, str, str]] = [
    ("BRAND_INK / INK", BRAND_INK, "brand"), ("BRAND_WARM_GRAY / CARD_BORDER", BRAND_WARM_GRAY, "brand"),
    ("BRAND_POWDER / SECTION", BRAND_POWDER, "brand"), ("BRAND_WISTFUL", BRAND_WISTFUL, "brand"),
    ("BRAND_YELLOW", BRAND_YELLOW, "brand"), ("BRAND_SALMON", BRAND_SALMON, "brand"),
    ("BRAND_GREEN", BRAND_GREEN, "brand"), ("PAGE", PAGE, "structure"), ("CARD / ON_DARK", WHITE, "structure"),
    ("BAND_DARK", BAND_DARK, "structure"), ("PANEL_DARK", PANEL_DARK, "structure"),
    ("TRACK_DARK", TRACK_DARK, "structure"), ("ON_DARK_MUTED", ON_DARK_MUTED, "structure"),
    ("ON_DARK_CAPTION", ON_DARK_CAPTION, "structure"), ("MUTED", MUTED, "structure"),
    ("LINK", LINK, "structure"), ("ZEBRA", ZEBRA, "structure"),
    *[(f"STATUS_FILL[{k}]", v, "status.fill") for k, v in STATUS_FILL.items()],
    *[(f"STATUS_MARK[{k}]", v, "status.mark") for k, v in STATUS_MARK.items()],
    *[(f"STATUS_DEEP[{k}]", v, "status.deep") for k, v in STATUS_DEEP.items()],
    ("FLAG_REOPENED / DEMO_BAND", BRAND_SALMON, "flag/chip"), ("FLAG_STALLED / HISTORIC_BAND", BRAND_YELLOW, "flag/chip"),
    ("FLAG_COND / HEAT_HIGH", BRAND_WISTFUL, "flag/chip"), ("CHIP neutral", PAGE, "flag/chip"),
    ("CHART_TEXT", CHART_TEXT, "chart"), ("CHART_GRID", CHART_GRID, "chart"),
    ("TEXT_BLACK", TEXT_BLACK, "protocol"), ("LIGHT_GRAY / NOTE_FILL", LIGHT_GRAY, "protocol"),
    ("INPUT", INPUT, "protocol"), ("BORDER (data sheet)", BORDER, "protocol"),
    ("CLOSED_ROW_GRAY", CLOSED_ROW_GRAY, "protocol"), ("CLOSED_ROW_TEXT", CLOSED_ROW_TEXT, "protocol"),
    ("PLACEHOLDER_GRAY", PLACEHOLDER_GRAY, "protocol"), ("HEADER_CYAN", HEADER_CYAN, "protocol"),
]


def family_of(hex_: str) -> list[str]:
    return sorted({fam for _, h, fam in TOKEN_FAMILY if h == hex_.upper()})


# ---------------------------------------------------------------- contrast table of spec 4.6 (G-UX-22)
# (pair, foreground, background, ratio stated in the spec, kind: text | large | mark)
CONTRAST_TABLE = [
    ("White on BAND_DARK", WHITE, BAND_DARK, 18.1, "text"),
    ("ON_DARK_MUTED on BAND_DARK", ON_DARK_MUTED, BAND_DARK, 12.8, "text"),
    ("White on PANEL_DARK", WHITE, PANEL_DARK, 15.7, "text"),
    ("ON_DARK_CAPTION on PANEL_DARK", ON_DARK_CAPTION, PANEL_DARK, 6.5, "text"),
    ("Cinder on SECTION", INK, SECTION, 12.4, "text"),
    ("Cinder on PAGE", INK, PAGE, 16.1, "text"),
    ("MUTED on white", MUTED, WHITE, 7.0, "text"),
    ("LINK on white", LINK, WHITE, 8.7, "text"),
    ("LINK on SECTION", LINK, SECTION, 6.0, "text"),
    *[(f"Cinder on D.2 {k}", INK, v, None, "text") for k, v in STATUS_FILL.items()],
    *[(f"Cinder on mark {k}", INK, v, None, "text") for k, v in STATUS_MARK.items()],
    *[(f"Deep {k} on white", v, WHITE, None, "text") for k, v in STATUS_DEEP.items()],
    *[(f"Mark {k} on PANEL_DARK", v, PANEL_DARK, None, "mark") for k, v in STATUS_MARK.items()],
    ("Mark Powder Blue on PANEL_DARK (sustainability arc, new tile)", SECTION, PANEL_DARK, None, "mark"),
    ("Chip favourable", CHIP["fav"][1], CHIP["fav"][0], None, "text"),
    ("Chip unfavourable", CHIP["unfav"][1], CHIP["unfav"][0], None, "text"),
    ("Chip neutral", CHIP["neutral"][1], CHIP["neutral"][0], None, "text"),
    ("White on INK (footer, card chip)", WHITE, INK, None, "text"),
    ("MUTED on ZEBRA", MUTED, ZEBRA, None, "text"),
    ("Cinder on ZEBRA", INK, ZEBRA, None, "text"),
    ("Chart text on white", CHART_TEXT, WHITE, None, "text"),
]
CONTRAST_SPEC_RANGES = {"Cinder on D.2": (14.7, 16.0), "Deep": (5.9, 8.7), "Mark": (7.1, 10.9)}

# legacy aliases used by earlier modules
ACCENT = SECTION
MUTED_TEXT = MUTED
TITLE_TEXT = INK
STATUS_CHART = STATUS_TEXT
STATUS_TONE = STATUS_TEXT
HELP_FILL = CARD
LABEL_FILL = CARD
