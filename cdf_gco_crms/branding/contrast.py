"""WCAG 2.2 contrast ratio (Innovation 09; gate G-UX-04)."""
from __future__ import annotations


def _channel(v: int) -> float:
    c = v / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex6: str) -> float:
    h = hex6.lstrip("#")[-6:]
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def passes(fg: str, bg: str, *, large: bool = False) -> bool:
    return contrast_ratio(fg, bg) >= (3.0 if large else 4.5)
