"""Guard against accidental institutional-data and credential publication in PUBLIC Git.

This is a heuristic safety net, not a DLP certification. It checks Git-tracked
paths and text blobs; deliberately does not inspect ignored private workspaces.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT=pathlib.Path(__file__).resolve().parents[2]
PROHIBITED_PARTS={"private","sources","EVIDENCE","secrets"}
PROHIBITED_SUFFIX={".docx",".docm",".pdf",".pem",".key",".p12",".pfx",".sqlite",".db",".kdbx"}
PRIVATE_NAMED=re.compile(r"(?i)(MAT_(OBSERVATION_EVOLUTION_REGISTER|PROFESSIONAL_DNA_QUESTIONNAIRE|WRITING_STYLE_DNA|PROFILE_EVIDENCE_REGISTER|PROFESSIONAL_DNA_PROFILE)|CDF_.*CONFIDENTIAL)")
TEXT_PATTERNS=[
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"sk-ant-[A-Za-z0-9_-]{24,}"),
    re.compile(rb"ghp_[A-Za-z0-9]{30,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
]
ALLOWLIST={"RELEASE-GATE-MATRIX.xlsx"}  # legacy public workbook: requires independent periodic classification review
MAX_TEXT_FILE=2_000_000


def main()->int:
    files=subprocess.check_output(["git","ls-files","-z"],cwd=ROOT).split(b"\0")
    findings=[]
    for raw in files:
        if not raw:continue
        rel=raw.decode("utf-8","surrogateescape")
        path=ROOT/rel
        if not path.is_file():continue
        p=pathlib.PurePosixPath(rel)
        if any(part in PROHIBITED_PARTS for part in p.parts):
            findings.append(f"RESTRICTED_PATH:{rel}")
        if PRIVATE_NAMED.search(rel):
            findings.append(f"INSTITUTIONAL_ARTIFACT_NAME:{rel}")
        if p.suffix.lower() in PROHIBITED_SUFFIX and rel not in ALLOWLIST:
            findings.append(f"RESTRICTED_EXTENSION:{rel}")
        if p.suffix.lower()==".xlsx" and rel not in ALLOWLIST and not rel.startswith("tests/fixtures/"):
            findings.append(f"UNAPPROVED_EXCEL_BINARY:{rel}")
        if p.name.startswith(".env") or p.name.endswith((".env",".env.production")):
            findings.append(f"ENV_FILE:{rel}")
        if path.stat().st_size <= MAX_TEXT_FILE and p.suffix.lower() not in {".xlsx",".zip",".png",".jpg",".jpeg",".gif",".woff",".ttf"}:
            data=path.read_bytes()
            for pat in TEXT_PATTERNS:
                if pat.search(data):
                    findings.append(f"CREDENTIAL_SIGNATURE:{rel}:{pat.pattern[:24]!r}")
    if findings:
        print("PUBLIC_REPOSITORY_SAFETY_SCAN: FAILED")
        for issue in sorted(set(findings)):print(issue)
        return 1
    print(f"PUBLIC_REPOSITORY_SAFETY_SCAN: PASS ({len(files)-1} tracked entries; heuristic only)")
    return 0


if __name__=="__main__":
    sys.exit(main())
