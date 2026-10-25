"""Guard against accidental institutional-data and credential publication in PUBLIC Git.

This is a heuristic safety net, not a DLP certification. It checks Git-tracked paths and text blobs and
deliberately does not inspect ignored private workspaces.

Checks
  * paths: restricted folders, private artifact names, restricted extensions, unapproved Excel binaries, env files;
  * credential signatures (private keys, provider and GitHub tokens, AWS keys);
  * shareable Google Drive / Docs links (a link discloses a file id, and "anyone with the link" sharing exposes the file);
  * kunya-style personal references (an honorific, then a kunya such as أبو/أم, then a name) — a real colleague's name must never reach the public tree;
  * an optional PRIVATE deny-list (names, source titles, file ids, document hashes) kept outside Git: the file named by
    ``CDF_PRIVATE_DENYLIST_FILE`` (default ``private/denylist.txt``) and/or the newline-separated terms in
    ``CDF_PRIVATE_DENYLIST_TERMS`` (for CI, from a repository secret). Matches are reported by term index only, so a
    CI log never reveals the term itself.

``--history`` also scans every blob reachable from HEAD (documents what is already published; it does not fail CI
by default because history can only be cleaned by a deliberate rewrite).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROHIBITED_PARTS = {"private", "sources", "EVIDENCE", "secrets"}
PROHIBITED_SUFFIX = {".docx", ".docm", ".pdf", ".pem", ".key", ".p12", ".pfx", ".sqlite", ".db", ".kdbx"}
PRIVATE_NAMED = re.compile(r"(?i)(MAT_(OBSERVATION_EVOLUTION_REGISTER|PROFESSIONAL_DNA_QUESTIONNAIRE|WRITING_STYLE_DNA|PROFILE_EVIDENCE_REGISTER|PROFESSIONAL_DNA_PROFILE)|CDF_.*CONFIDENTIAL)")
TEXT_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"sk-ant-[A-Za-z0-9_-]{24,}"),
    re.compile(rb"ghp_[A-Za-z0-9]{30,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
]
DRIVE_LINK = re.compile(r"(?:drive|docs)\.google\.com/(?:file|document|spreadsheets|presentation)/d/[A-Za-z0-9_-]{20,}")
KUNYA = re.compile(r"(?:الأخ|الاخ|الأخت|الاخت|الزميل|الزميلة)\s+(?:أبو|ابو|أبا|ابا|أم|ام)\s+\S+")
BINARY_SUFFIX = {".xlsx", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2", ".ttf", ".ico"}
ALLOWLIST = {"RELEASE-GATE-MATRIX.xlsx"}  # legacy public workbook: requires independent periodic classification review
MAX_TEXT_FILE = 2_000_000
_DIACRITICS = re.compile("[ً-ْٰـ]")


def fold(text: str) -> str:
    """Hamza-, ta-marbuta-, diacritic- and case-insensitive form, so spelling variants of a term still match."""
    t = _DIACRITICS.sub("", unicodedata.normalize("NFKC", text or ""))
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", t).strip().lower()


def load_denylist(env: dict | None = None, root: pathlib.Path = ROOT) -> list[str]:
    env = os.environ if env is None else env
    terms: list[str] = []
    path = pathlib.Path(env.get("CDF_PRIVATE_DENYLIST_FILE") or root / "private" / "denylist.txt")
    if path.is_file():
        terms += path.read_text(encoding="utf-8").splitlines()
    terms += (env.get("CDF_PRIVATE_DENYLIST_TERMS") or "").splitlines()
    return [fold(t) for t in terms if t.strip() and not t.lstrip().startswith("#") and len(fold(t)) >= 4]


def scan_text(rel: str, data: bytes, denylist: list[str]) -> list[str]:
    findings = []
    for pat in TEXT_PATTERNS:
        if pat.search(data):
            findings.append(f"CREDENTIAL_SIGNATURE:{rel}:{pat.pattern[:24]!r}")
    text = data.decode("utf-8", "ignore")
    if DRIVE_LINK.search(text):
        findings.append(f"SHAREABLE_DRIVE_LINK:{rel}")
    if KUNYA.search(text):
        findings.append(f"PERSONAL_REFERENCE:{rel}")
    if denylist:
        folded = fold(text)
        for i, term in enumerate(denylist):
            if term in folded:
                findings.append(f"PRIVATE_DENYLIST_TERM:{rel}:#{i + 1}")
    return findings


def scan_tree(root: pathlib.Path, files: list[str], denylist: list[str]) -> list[str]:
    findings = []
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        p = pathlib.PurePosixPath(rel)
        if any(part in PROHIBITED_PARTS for part in p.parts):
            findings.append(f"RESTRICTED_PATH:{rel}")
        if PRIVATE_NAMED.search(rel):
            findings.append(f"INSTITUTIONAL_ARTIFACT_NAME:{rel}")
        if p.suffix.lower() in PROHIBITED_SUFFIX and rel not in ALLOWLIST:
            findings.append(f"RESTRICTED_EXTENSION:{rel}")
        if p.suffix.lower() == ".xlsx" and rel not in ALLOWLIST and not rel.startswith("tests/fixtures/"):
            findings.append(f"UNAPPROVED_EXCEL_BINARY:{rel}")
        if p.name.startswith(".env") or p.name.endswith((".env", ".env.production")):
            findings.append(f"ENV_FILE:{rel}")
        if path.stat().st_size <= MAX_TEXT_FILE and p.suffix.lower() not in BINARY_SUFFIX:
            findings += scan_text(rel, path.read_bytes(), denylist)
    return findings


def scan_history(root: pathlib.Path, denylist: list[str]) -> list[str]:
    """Every blob reachable from HEAD (all commits, not only the tip)."""
    objects = subprocess.check_output(["git", "rev-list", "--objects", "HEAD"], cwd=root).decode("utf-8", "surrogateescape")
    findings = []
    for line in objects.splitlines():
        sha, _, rel = line.partition(" ")
        if not rel or pathlib.PurePosixPath(rel).suffix.lower() in BINARY_SUFFIX:
            continue
        kind = subprocess.run(["git", "cat-file", "-t", sha], cwd=root, capture_output=True, text=True).stdout.strip()
        if kind != "blob":
            continue
        data = subprocess.check_output(["git", "cat-file", "blob", sha], cwd=root)
        if len(data) <= MAX_TEXT_FILE:
            findings += [f"HISTORY:{sha[:10]}:{f}" for f in scan_text(rel, data, denylist)]
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", action="store_true", help="also scan every blob reachable from HEAD (report only)")
    a = ap.parse_args(argv)
    files = [f for f in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8", "surrogateescape").split("\0") if f]
    denylist = load_denylist()
    findings = scan_tree(ROOT, files, denylist)
    deny_state = f"private deny-list: {len(denylist)} terms" if denylist else "private deny-list: NOT_CONFIGURED"
    if a.history:
        hist = sorted(set(scan_history(ROOT, denylist)))
        print(f"PUBLIC_REPOSITORY_HISTORY_SCAN: {len(hist)} findings (report only; cleaning history needs a deliberate rewrite)")
        for issue in hist:
            print(issue)
    if findings:
        print(f"PUBLIC_REPOSITORY_SAFETY_SCAN: FAILED ({deny_state})")
        for issue in sorted(set(findings)):
            print(issue)
        return 1
    print(f"PUBLIC_REPOSITORY_SAFETY_SCAN: PASS ({len(files)} tracked entries; {deny_state}; heuristic only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
