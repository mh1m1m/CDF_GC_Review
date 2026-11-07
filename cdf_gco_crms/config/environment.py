"""Runtime environment policy of the v7.12 engine (patch V712-007).

Everything an independent clean-room run needs to know is declared here and
read from here: schema identifiers, directory layout, logging and time-zone
policy, and the error-recovery rules. Nothing is read from the user's
environment except an optional output root.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import ENGINE_VERSION, PROTOCOL_VERSION, WORKBOOK_SCHEMA

PYTHON_MIN = (3, 11)
TIMEZONE = "Asia/Riyadh"                      # dates are recorded as supplied (ISO), never generated from the clock
LOG_POLICY = ("no requester-facing artifact carries internal reasoning, reviewer identities or evidence ledgers "
              "(15A, 19A.11); audit logs are kept under build/ and the package's 09_EVIDENCE folder")
ERROR_RECOVERY = ("fail closed: an unsafe or malformed input stops before any part is parsed; an output is written "
                  "to a temporary file and renamed into place only when complete (atomic); the input is never "
                  "overwritten")

ROOT = Path(__file__).resolve().parents[2]
PATHS = {
    "root": ROOT,
    "sources": ROOT / "sources",
    "build": Path(os.environ.get("CRMS_BUILD_DIR", ROOT / "build")),
    "deliverables": ROOT / "deliverables",
    "dist": ROOT / "dist",
    "assets": ROOT / "assets",
}
PINNED = {"openpyxl": "3.1.5", "python-docx": "1.2.0", "lxml": "6.1.3", "pillow": "12.3.0", "pytest": "9.1.1",
          "cryptography": "50.0.1", "pypdf": "6.17.0"}


def describe() -> dict:
    import importlib.metadata as md
    installed = {}
    for dist in PINNED:
        try:
            installed[dist] = md.version(dist)
        except md.PackageNotFoundError:
            installed[dist] = None
    return {
        "engine": ENGINE_VERSION, "protocol": PROTOCOL_VERSION, "workbook_schema": WORKBOOK_SCHEMA,
        "python": sys.version.split()[0], "python_ok": sys.version_info >= PYTHON_MIN,
        "timezone": TIMEZONE, "log_policy": LOG_POLICY, "error_recovery": ERROR_RECOVERY,
        "paths": {k: str(v) for k, v in PATHS.items()},
        "pinned": PINNED, "installed": installed,
        "pins_match": all(installed.get(k) == v for k, v in PINNED.items()),
    }


def check() -> list[str]:
    """Problems that stop a clean-room run; an empty list means the environment is as declared."""
    d = describe()
    out = []
    if not d["python_ok"]:
        out.append(f"python {d['python']} < {'.'.join(map(str, PYTHON_MIN))}")
    for k, v in PINNED.items():
        if d["installed"].get(k) is None:
            out.append(f"{k} not installed")
        elif d["installed"][k] != v:
            out.append(f"{k} {d['installed'][k]} != pinned {v}")
    return out
