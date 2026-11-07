"""LibreOffice headless engine: formula recalculation and PDF rendering (directive §11.1, Art. 16).

Recalculation runs a Basic macro that calls ``calculateAll()`` and stores the
file, so the values read back afterwards were computed by the spreadsheet
engine, not taken from cached values. The engine is a stand-in for Microsoft
Excel: results prove the formulas evaluate in an independent engine; they do
not prove Excel's behaviour (recorded as a limitation, G-DASH-13).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
Sub RecalculateAndSave()
  ThisComponent.calculateAll()
  ThisComponent.store()
  ThisComponent.close(True)
End Sub
</script:module>"""

@dataclass
class LOResult:
    ok: bool
    message: str
    version: str = ""


def available() -> bool:
    return shutil.which("soffice") is not None


def version() -> str:
    try:
        out = subprocess.run(["soffice", "--version"], capture_output=True, text=True, timeout=60)
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _env() -> dict:
    """Headless environment. LibreOffice needs AF_UNIX sockets; where a sandbox blocks them the
    run fails with an explicit message rather than a silent partial result."""
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    return env


def sockets_ok() -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.close()
        return True
    except OSError:
        return False


def _profile(tmpdir: str, with_macro: bool) -> str:
    url = Path(tmpdir).as_uri()
    subprocess.run(["soffice", "--headless", "--terminate_after_init", f"-env:UserInstallation={url}"],
                   capture_output=True, timeout=120, env=_env())
    if with_macro:
        d = Path(tmpdir) / "user" / "basic" / "Standard"
        if not d.exists():
            raise RuntimeError("LibreOffice profile not created")
        (d / "Module1.xba").write_text(MACRO)
    return url


def recalc(path, timeout: int = 180) -> LOResult:
    """Recalculate in place (call on a copy)."""
    if not available():
        return LOResult(False, "soffice not available")
    if not sockets_ok():
        return LOResult(False, "AF_UNIX sockets blocked; LibreOffice cannot run here")
    path = str(Path(path).resolve())
    before = os.stat(path).st_mtime_ns
    with tempfile.TemporaryDirectory(prefix="crms-lo-") as tmp:
        url = _profile(tmp, True)
        cmd = ["soffice", "--headless", "--norestore", f"-env:UserInstallation={url}",
               "vnd.sun.star.script:Standard.Module1.RecalculateAndSave?language=Basic&location=application", path]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_env())
        except subprocess.TimeoutExpired:
            return LOResult(False, "timeout")
        if r.returncode != 0:
            return LOResult(False, (r.stderr or "")[-500:])
    if os.stat(path).st_mtime_ns == before:
        return LOResult(False, "file not rewritten; nothing recalculated")
    return LOResult(True, "recalculated", version())


def to_pdf(path, outdir, timeout: int = 240) -> Path | None:
    if not available():
        return None
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="crms-lo-") as tmp:
        url = _profile(tmp, False)
        subprocess.run(["soffice", "--headless", "--norestore", f"-env:UserInstallation={url}", "--convert-to", "pdf",
                        "--outdir", str(outdir), str(path)], capture_output=True, timeout=timeout, env=_env())
    pdf = outdir / (Path(path).stem + ".pdf")
    return pdf if pdf.exists() else None
