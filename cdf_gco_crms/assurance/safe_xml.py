"""Hardened parsing for XML parts read from uploaded Office packages.

OOXML parts never carry a document type declaration, so any part that does is
refused before parsing. This blocks entity-expansion and external-entity
payloads regardless of the installed expat version. The check runs on the
decoded text, so a UTF-16 or UTF-32 part cannot hide the declaration.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

ParseError = ET.ParseError

_DTD = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)

# Byte-order marks and the first bytes of "<?" in each wide encoding (XML 1.0, Appendix F).
_WIDE_ENCODINGS = (
    (b"\x00\x00\xfe\xff", "utf-32-be"), (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\x00<", "utf-32-be"), (b"<\x00\x00\x00", "utf-32-le"),
    (b"\xfe\xff", "utf-16-be"), (b"\xff\xfe", "utf-16-le"),
    (b"\x00<", "utf-16-be"), (b"<\x00", "utf-16-le"),
)


def _decoded(raw: bytes) -> str:
    for prefix, encoding in _WIDE_ENCODINGS:
        if raw.startswith(prefix):
            return raw.decode(encoding, "replace")
    # ASCII-compatible encodings (UTF-8, Latin-1, ...) keep "<!DOCTYPE" as plain bytes.
    return raw.decode("latin-1")


def has_dtd(data: bytes | str) -> bool:
    """True when an XML part declares a DOCTYPE or ENTITY in any supported encoding."""
    text = data if isinstance(data, str) else _decoded(data)
    return bool(_DTD.search(text))


def fromstring(data: bytes | str) -> ET.Element:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if has_dtd(raw):
        raise ParseError("document type declarations are not permitted in package parts")
    return ET.fromstring(raw)  # nosec B314 - DTD/entity declarations rejected above
