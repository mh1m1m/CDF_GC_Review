#!/usr/bin/env python3
"""Clean smoke test of the packaged source (V712-060): extract 02_ENGINE from the RC zip into an empty directory and
run, with the interpreter given on the command line (a clean virtual environment), the CLI help, the environment
check and the fast regression groups (titles, security, protocol). Writes the result next to the zip."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "dist" / "CDF-GCO-CRMS-v7.12-PRODUCTION-RC-COMPLETE.zip"


def main(python: str) -> int:
    out = {"zip": str(ZIP), "python": python, "steps": []}
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(ZIP) as z:
            members = [n for n in z.namelist() if "/02_ENGINE/" in n]
            z.extractall(td, members)
        eng = next(Path(td).rglob("02_ENGINE"))
        steps = [
            ("cli-help", [python, "main.py", "--help"]),
            ("environment", [python, "-c", "import sys; sys.path.insert(0,'.'); from cdf_gco_crms.config import environment as E; "
                                           "import json; print(json.dumps(E.check()))"]),
            ("pytest-fast", [python, "-m", "pytest", "tests/test_titles.py", "tests/test_security.py", "tests/test_protocol.py",
                             "tests/test_brand.py", "-q", "-p", "no:cacheprovider"]),
        ]
        ok = True
        for name, cmd in steps:
            r = subprocess.run(cmd, cwd=str(eng), capture_output=True, text=True, timeout=1800)
            out["steps"].append({"step": name, "rc": r.returncode, "tail": (r.stdout + r.stderr)[-400:]})
            ok &= r.returncode == 0
    out["ok"] = ok
    (ZIP.with_name("RC-SMOKE-TEST.json")).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": ok, "steps": [(s["step"], s["rc"]) for s in out["steps"]]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else sys.executable))
