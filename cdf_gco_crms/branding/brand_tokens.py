"""Verified CDF brand tokens with provenance (protocol Annex D.11, v7.12).

Two guide files exist:

* "CDF Design Guide" (87 pages, PowerPoint export). Page 12 "Color Library"
  prints seven named colours with their HEX values; page 21 "Typography"
  states Calibri and a type scale (Display 32, H1 24, H2 20, H3 16, Body 1 14,
  Body 2 12, Body 3 10). The rendered pages are kept in sources/v7.12
  (guide_page12.png, guide_page21.png) and the printed HEX of every swatch
  is re-checked against the swatch pixels by ``guide_page_check`` (seven of
  seven equal). Verification: HEX_PRINTED_IN_GUIDE.
* "Identity Applications" (8 pages, Illustrator). Logo versions, the rule
  that the logo is black on coloured backgrounds, co-branding layouts; its
  colours are CMYK-specified and were converted in v7.11 (D8D3CB, A7B0D9,
  FED186, F69271). Those conversions lie within 2/255 of the printed HEX of
  the 87-page guide and are superseded by it (SUPERSEDED_CONVERSION); the
  file remains the logo source.

The typography conflict recorded in v7.11 (AMB-150: the 8-page file embeds
Brando Arabic) is closed: page 21 of the 87-page guide names Calibri, which
is also the protocol's binding typeface (Art. 08.2, 10.4).
"""
from __future__ import annotations

from dataclasses import dataclass

HEX_PRINTED = "HEX_PRINTED_IN_GUIDE"
RGB_SPECIFIED = "RGB_SPECIFIED"
CMYK_SPECIFIED = "CMYK_SPECIFIED (sRGB converted)"
SUPERSEDED = "SUPERSEDED_CONVERSION"
NOT_IN_GUIDE = "NOT_IN_GUIDE"
PROTOCOL_PALETTE = "PROTOCOL_PALETTE (D.7)"
DERIVED = "DERIVED_TONE (not brand)"
SEMANTIC = "SEMANTIC_STATUS (D.2, not brand)"

GUIDE_87 = "CDF Design Guide (87 pages)"
GUIDE_8 = "CDF Identity Applications (8 pages)"


@dataclass(frozen=True)
class Token:
    name: str
    hex: str
    verification: str
    source: str
    page: str
    use: str
    note: str = ""


BRAND_TOKENS: tuple[Token, ...] = (
    Token("brand.cinder_black", "101820", HEX_PRINTED, GUIDE_87, "page 12, swatch 1 (Cinder Black)",
          "every title and body text, top rule, chart outlines", "Also the wordmark colour of the identity file."),
    Token("brand.warm_gray", "D7D2CB", HEX_PRINTED, GUIDE_87, "page 12, swatch 2 (Warm Gray)",
          "identity band of the dashboard (the guide's own page header), card borders, section rules, label column",
          "The guide's pages carry this band with the logo at the reading edge."),
    Token("brand.powder_blue", "BBDDE6", HEX_PRINTED, GUIDE_87, "page 12, swatch 3 (Powder Blue)",
          "accent surface: section markers, table headers, selector frames, GCO headers of the data sheet, total card",
          "Identical to the protocol palette HEADER_CYAN (D.7)."),
    Token("brand.wistful_blue", "A5B0E3", HEX_PRINTED, GUIDE_87, "page 12, swatch 4 (Wistful Blue)",
          "selected observation, rate-line markers", ""),
    Token("brand.chardonnay_yellow", "FDD086", HEX_PRINTED, GUIDE_87, "page 12, swatch 5 (Chardonnay Yellow)",
          "historic-round band, stalled flag", ""),
    Token("brand.light_salmon", "FA9370", HEX_PRINTED, GUIDE_87, "page 12, swatch 6 (Light Salmon)",
          "demonstration band, reopened flag", ""),
    Token("brand.jetstream_green", "B5E1C4", HEX_PRINTED, GUIDE_87, "page 12, swatch 7 (Jetstream Green)",
          "not used on its own (the closure fills stay the D.2 fills of the issued registers, AMB-161)", ""),
    Token("brand.page_surface", "F3F3F4", HEX_PRINTED, GUIDE_87, "pages 12 and 21 (page background, sampled F3F3F4)",
          "page surface of the dashboard behind the white cards", "Sampled from the rendered page; not printed as a swatch."),
    Token("brand.surface.light", "F2F2F2", RGB_SPECIFIED, GUIDE_8, "pages 2 to 7 (content panel background; rg 0.949)",
          "notes, help panel, round-1 مفتوحة fill", "Also the protocol LIGHT_GRAY (D.7)."),
    Token("brand.surface.white", "FFFFFF", HEX_PRINTED, GUIDE_87, "page 12 (swatch cards)", "cards, tables, chart areas", ""),
)

# Conversions of v7.11 from the CMYK operators of the 8-page file, superseded by the printed HEX of the 87-page guide
SUPERSEDED_CONVERSIONS: tuple[Token, ...] = (
    Token("v7.11.warm_gray", "D8D3CB", SUPERSEDED, GUIDE_8, "page 5, swatch 3 (k 0.148 0.131 0.171 0)", "not used", "Printed HEX: D7D2CB."),
    Token("v7.11.wistful_blue", "A7B0D9", SUPERSEDED, GUIDE_8, "page 5, swatch 2 (k 0.336 0.263 0 0)", "not used", "Printed HEX: A5B0E3."),
    Token("v7.11.yellow", "FED186", SUPERSEDED, GUIDE_8, "page 5, swatch 4 (k 0.003 0.189 0.539 0)", "not used", "Printed HEX: FDD086."),
    Token("v7.11.salmon", "F69271", SUPERSEDED, GUIDE_8, "page 5, swatch 5 (k 0 0.521 0.55 0)", "not used", "Printed HEX: FA9370."),
)

# No brand claim is left unverified in v7.12 (the gate G-UX-01 still checks this tuple).
UNVERIFIED_CLAIMS: tuple[Token, ...] = ()

SEMANTIC_FILLS: tuple[Token, ...] = (
    Token("status.closed", "E2EFDA", SEMANTIC, "protocol D.2", "every issued register", "مغلقة: register cells, dashboard cards, tables, chart marks", "Same fill on both sheets (AMB-161)."),
    Token("status.conditional", "DDEBF7", SEMANTIC, "protocol D.2", "every issued register", "مغلقة بشرط", ""),
    Token("status.requires_edit", "FFF2CC", SEMANTIC, "protocol D.2", "every issued register", "يتطلب تعديل", ""),
    Token("status.open", "FCE4D6", SEMANTIC, "protocol D.2", "every issued register", "مفتوحة", ""),
)
DERIVED_TONES: tuple[Token, ...] = (
    Token("derived.closed_text", "375623", DERIVED, "engine", "hue of #E2EFDA darkened", "KPI value, مغلقة text on white", "8.4:1 on white"),
    Token("derived.conditional_text", "1F4E79", DERIVED, "engine", "hue of #DDEBF7 darkened", "KPI value, links, مغلقة بشرط text on white", "10.4:1 on white"),
    Token("derived.requires_edit_text", "7F6000", DERIVED, "engine", "hue of #FFF2CC darkened", "KPI value, يتطلب تعديل text on white", "6.4:1 on white"),
    Token("derived.open_text", "843C0C", DERIVED, "engine", "hue of #FCE4D6 darkened", "KPI value, reopened marks, مفتوحة text on white", "7.9:1 on white"),
)

TYPOGRAPHY_FINDING = ("Page 21 of the 87-page guide names Calibri as the font family with the scale Display 32, H1 24, "
                      "H2 20, H3 16, Body 1 14, Body 2 12, Body 3 10. The workbook uses Calibri throughout (Art. 08.2, 10.4) "
                      "with title 24, document 14, sections 16, card values 32, body 10, notes 9. The v7.11 conflict with the "
                      "Brando Arabic typeface embedded in the 8-page identity file is closed (AMB-150).")
LOGO_FINDING = ("The 8-page identity file shows the logo versions (vertical, horizontal, Arabic, symbol, legal footer) as vector "
                "art, with the rule that the logo is black on coloured backgrounds and white on black only in special cases. "
                "The official horizontal logo was supplied separately as an image (1186 × 212 px); it is embedded unchanged "
                "except that its white background is made transparent so that it sits black on the Warm Gray identity band, as "
                "on the guide's own pages. It is never redrawn or traced.")
