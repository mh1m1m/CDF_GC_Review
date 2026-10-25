"""Source hygiene and hardened package-part parsing."""
import re
import subprocess
from pathlib import Path

import pytest

from cdf_gco_crms.assurance import safe_xml

ROOT = Path(__file__).resolve().parents[1]
_BIDI_CONTROLS = re.compile("[\u202a-\u202e\u2066-\u2069]")


def test_tracked_source_has_no_literal_bidi_controls():
    files = subprocess.run(["git", "ls-files", "*.py", "*.ts", "*.tsx", "*.js"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    offenders = []
    for name in files:
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        offenders += [f"{name}:{n}" for n, line in enumerate(text.splitlines(), 1) if _BIDI_CONTROLS.search(line)]
    assert offenders == [], "write bidi controls as \\u escapes: " + ", ".join(offenders)


def test_safe_xml_parses_plain_ooxml_part():
    root = safe_xml.fromstring(b'<?xml version="1.0"?><w:document xmlns:w="urn:x"><w:t>ok</w:t></w:document>')
    assert "".join(root.itertext()) == "ok"


@pytest.mark.parametrize("payload", [
    b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><r>&b;</r>',
    b'<!doctype r SYSTEM "http://example.invalid/x.dtd"><r/>',
    '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>',
])
def test_safe_xml_rejects_dtd_and_entities(payload):
    with pytest.raises(safe_xml.ParseError):
        safe_xml.fromstring(payload)
