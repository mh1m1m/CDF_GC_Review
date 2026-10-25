"""Hardened parsing for XML parts read from uploaded Office packages.

OOXML parts never carry a document type declaration, so any part that does is
refused before parsing. This blocks entity-expansion and external-entity
payloads regardless of the installed expat version.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

ParseError = ET.ParseError

_DTD = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def fromstring(data: bytes | str) -> ET.Element:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if _DTD.search(raw):
        raise ParseError("document type declarations are not permitted in package parts")
    return ET.fromstring(raw)  # nosec B314 - DTD/entity declarations rejected above
