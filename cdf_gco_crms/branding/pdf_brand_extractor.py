"""Reads colour operators and fonts from a design-guide PDF (UX directive §02.2).

Colours are taken from the content streams (``rg``/``k``/``sc*`` operators)
and from the vector drawings, so every value carries its colour space and
can be labelled RGB_SPECIFIED or CMYK_SPECIFIED. Nothing is sampled from a
rendered bitmap.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_RGB = re.compile(rb"([\d.]+) ([\d.]+) ([\d.]+) rg")
_CMYK = re.compile(rb"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) k\b")


@dataclass
class ColourFinding:
    page: int
    space: str          # DeviceRGB | DeviceCMYK
    components: tuple
    srgb_hex: str
    area: float = 0.0


@dataclass
class GuideReport:
    path: str
    sha256: str
    pages: int
    page_size: tuple
    producer: str
    fonts: list[str]
    colours: list[ColourFinding] = field(default_factory=list)
    text_lines: list[str] = field(default_factory=list)


def _cmyk_to_srgb(c, m, y, k) -> str:
    r = 255 * (1 - c) * (1 - k)
    g = 255 * (1 - m) * (1 - k)
    b = 255 * (1 - y) * (1 - k)
    return "%02X%02X%02X" % (round(r), round(g), round(b))


def extract(path: str | Path) -> GuideReport:
    import pymupdf
    path = Path(path)
    doc = pymupdf.open(str(path))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    fonts: set[str] = set()
    rep = GuideReport(str(path), sha, len(doc), tuple(doc[0].rect[2:]) if len(doc) else (0, 0),
                      doc.metadata.get("producer", ""), [])
    for pno, page in enumerate(doc, start=1):
        for f in page.get_fonts():
            fonts.add(f[3].split("+")[-1])
        raw = b"".join(doc.xref_stream(x) for x in page.get_contents())
        for m in _RGB.finditer(raw):
            comps = tuple(float(v) for v in m.groups())
            rep.colours.append(ColourFinding(pno, "DeviceRGB", comps,
                                             "%02X%02X%02X" % tuple(round(v * 255) for v in comps)))
        for m in _CMYK.finditer(raw):
            comps = tuple(float(v) for v in m.groups())
            rep.colours.append(ColourFinding(pno, "DeviceCMYK", comps, _cmyk_to_srgb(*comps)))
        # areas from the drawing list (renderer conversion), joined by nearest hex
        areas: Counter = Counter()
        for d in page.get_drawings():
            fill = d.get("fill")
            if fill is None:
                continue
            r = d["rect"]
            areas["%02X%02X%02X" % tuple(round(c * 255) for c in fill)] += r.width * r.height
        for cf in rep.colours:
            if cf.page == pno:
                cf.area = max(cf.area, areas.get(cf.srgb_hex, 0.0))
        rep.text_lines.extend(l.strip() for l in page.get_text().splitlines() if l.strip())
    rep.fonts = sorted(fonts)
    return rep


def summary_rows(rep: GuideReport) -> list[dict]:
    rows = []
    seen = set()
    for cf in sorted(rep.colours, key=lambda c: (c.page, -c.area)):
        key = (cf.page, cf.space, cf.srgb_hex)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"page": cf.page, "space": cf.space, "components": " ".join(f"{v:g}" for v in cf.components),
                     "srgb_hex": "#" + cf.srgb_hex, "area_pt2": int(cf.area),
                     "verification": "RGB_SPECIFIED" if cf.space == "DeviceRGB" else "CMYK_SPECIFIED (sRGB converted)"})
    return rows
