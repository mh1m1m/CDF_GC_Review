"""Re-checks the printed HEX values of the guide's colour library against the rendered page (D.11, v7.12).

The 87-page CDF Design Guide prints each colour's HEX under its swatch on page
12. The rendered page (sources/v7.12/guide_page12.png) is sampled at the
centre of each swatch and the sampled pixel is compared with the printed HEX.
Nothing is sampled from a bitmap to *define* a token: the token is the printed
value; the sample only confirms that the render shows the same colour.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PRINTED_PAGE_12: tuple[tuple[str, str], ...] = (
    ("Cinder Black", "101820"), ("Warm Gray", "D7D2CB"), ("Powder Blue", "BBDDE6"), ("Wistful Blue", "A5B0E3"),
    ("Chardonnay Yellow", "FDD086"), ("Light Salmon", "FA9370"), ("Jetstream Green", "B5E1C4"),
)
# swatch centres as fractions of the page size (seven equal columns)
_X0, _DX, _Y = 0.107, 0.1317, 0.315


@dataclass
class SwatchCheck:
    name: str
    printed: str
    sampled: str
    equal: bool
    x: int
    y: int


def check_page12(png: str | Path) -> list[SwatchCheck]:
    from PIL import Image
    im = Image.open(png).convert("RGB")
    w, h = im.size
    out = []
    for i, (name, hx) in enumerate(PRINTED_PAGE_12):
        x, y = int(w * (_X0 + i * _DX)), int(h * _Y)
        r, g, b = im.getpixel((x, y))
        s = f"{r:02X}{g:02X}{b:02X}"
        out.append(SwatchCheck(name, hx, s, s == hx, x, y))
    return out


def page_surface(png: str | Path) -> str:
    from PIL import Image
    im = Image.open(png).convert("RGB")
    w, h = im.size
    r, g, b = im.getpixel((int(w * 0.5), int(h * 0.95)))
    return f"{r:02X}{g:02X}{b:02X}"
