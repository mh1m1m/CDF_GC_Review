#!/usr/bin/env python3
"""Build the chat kit (``cdf-chat-kit-<version>.zip``) from this repository.

The repository is the single source of truth: the kit is the engine package ``cdf_gco_crms`` and the public files
under ``shared/``, both taken from ``git ls-files`` (an untracked or ignored file never enters the kit), plus the kit
scripts and guides under ``kit/``. The kit's own comment rules and stage packets are the engine's
(``cdf_gco_crms.comments``, ``cdf_gco_crms.protocol.stage_packets``).

Brand assets (the dashboard guide icons and the CDF wordmark) are institutional (C5) and are not in the repository.
They enter the kit only from a private folder given with ``--brand-dir`` (laid out as ``icons/*.png`` and
``brand/*.png``). Without it the kit is built without them, the dashboard writer skips the missing pictures, and the
manifest lists them as missing.

The zip is deterministic: sorted entries, fixed timestamps, so the same commit gives the same bytes.
``--selftest`` unpacks the built zip into a temporary folder and runs ``python cdfkit.py selftest`` there, from the
kit alone, the way a chat sandbox would. ``--recalc`` adds the independent LibreOffice recalculation to the self-test
(10.4A.15); it needs ``soffice`` on PATH and fails the run without it, so a pass with ``--recalc`` proves LibreOffice ran.

Usage:
    python tools/build_chat_kit.py --out dist [--brand-dir PRIVATE/brand-assets] [--selftest [--recalc]]
Return codes: 0 built (and self-test PASS), 1 self-test FAIL, 2 input error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess  # nosec B404 - fixed git and python commands, no shell
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT_DIR = ROOT / "kit"
TOP = "cdf-chat-kit"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
KIT_FILES = ("cdfkit.py", "kit_stages.py", "kit_selftest.py", "AGENT-GUIDE.md", "requirements.txt")
KIT_DIRS = ("prompts", "examples")
SKIP = re.compile(r"(^|/)(__pycache__|\.pytest_cache)(/|$)|\.pyc$")


def in_git_checkout() -> bool:
    try:
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT,  # nosec B603 B607
                           capture_output=True, text=True)
    except OSError:   # git itself is not installed (the LibreOffice CI container)
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _git_files(*paths: str) -> list[str]:
    """Tracked files under ``paths``. Outside a git checkout (a ``git archive`` export, as in the LibreOffice CI
    container) every file there is a tracked file, so the folder itself is listed."""
    if not in_git_checkout():
        found = (f.relative_to(ROOT).as_posix() for p in paths for f in (ROOT / p).rglob("*") if f.is_file())
        return sorted(p for p in found if not SKIP.search(p))
    out = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=ROOT, check=True,  # nosec B603 B607
                         capture_output=True).stdout.decode("utf-8")
    return sorted(p for p in out.split("\0") if p and not SKIP.search(p))


def _commit() -> str:
    if not in_git_checkout():
        return "unknown (no git checkout)"
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)  # nosec B603 B607
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "cdf_gco_crms", "shared", "kit"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()  # nosec B603 B607
    return (r.stdout.strip() or "unknown") + ("+uncommitted" if dirty else "")


def kit_version() -> str:
    m = re.search(r'^KIT_VERSION = "([^"]+)"', (KIT_DIR / "cdfkit.py").read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("kit/cdfkit.py has no KIT_VERSION")
    return m.group(1)


def protocol_version() -> str:
    m = re.search(r'^PROTOCOL_VERSION = "([^"]+)"', (ROOT / "cdf_gco_crms/__init__.py").read_text(encoding="utf-8"),
                  re.M)
    return m.group(1) if m else "unknown"


def collect(brand_dir: Path | None) -> tuple[dict[str, Path], list[str]]:
    """Archive path -> source file, and the brand assets the kit is built without."""
    files: dict[str, Path] = {}
    for rel in _git_files("cdf_gco_crms", "shared"):
        files[rel] = ROOT / rel
    for name in KIT_FILES:
        files[name] = KIT_DIR / name
    for d in KIT_DIRS:
        for rel in _git_files(f"kit/{d}"):
            files[rel[len("kit/"):]] = ROOT / rel
    expected = [f"shared/icons/{n}" for n in _expected_icons()] + ["shared/brand/cdf-wordmark-on-light.png"]
    if brand_dir:
        for sub in ("icons", "brand"):
            for f in sorted((brand_dir / sub).glob("*.png")):
                files[f"shared/{sub}/{f.name}"] = f
    missing = [e for e in expected if e not in files]
    return files, missing


def _expected_icons() -> list[str]:
    """Icon files the dashboard asks for: ``<key>-ink.png`` and ``<key>-white.png`` per guide icon, and the hub."""
    sys.path.insert(0, str(ROOT))
    from cdf_gco_crms.config import design_tokens as T
    return sorted({f"{k}-{v}.png" for k in T.ICONS for v in ("ink", "white")} | {"gauge-hub.png"})


def build(out: Path, brand_dir: Path | None) -> tuple[Path, dict]:
    version = kit_version()
    files, missing = collect(brand_dir)
    for arc, src in files.items():
        if not src.is_file():
            raise SystemExit(f"missing source file for {arc}: {src}")
    manifest = {"kit_version": version, "protocol": protocol_version(), "built_from": _commit(),
                "files": {arc: hashlib.sha256(src.read_bytes()).hexdigest() for arc, src in sorted(files.items())},
                "brand_assets_missing": missing,
                "brand_note": ("institutional brand assets (C5) are not in the public repository; supply them with "
                               "--brand-dir from the private store") if missing else "brand assets supplied"}
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / f"{TOP}-{version}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, src in sorted(files.items()):
            info = zipfile.ZipInfo(f"{TOP}/{arc}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, src.read_bytes())
        info = zipfile.ZipInfo(f"{TOP}/KIT-MANIFEST.json", FIXED_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
    manifest["zip"] = str(zpath)
    manifest["zip_sha256"] = hashlib.sha256(zpath.read_bytes()).hexdigest()
    return zpath, manifest


def libreoffice() -> str | None:
    """``soffice --version`` when LibreOffice is installed, else None."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=120)  # nosec B603
    return r.stdout.strip() or exe


def selftest(zpath: Path, recalc: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix="cdf-kit-") as tmp:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        kit = Path(tmp) / TOP
        r = subprocess.run([sys.executable, "cdfkit.py", "selftest", *(["--recalc"] if recalc else [])],  # nosec B603
                           cwd=kit,
                           capture_output=True, text=True, timeout=1800)
        try:
            rep = json.loads(r.stdout)
        except json.JSONDecodeError:
            rep = {"status": "FAIL", "detail": (r.stdout + r.stderr)[-4000:]}
        rep["rc"] = r.returncode
        return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="dist", help="output folder (default: dist)")
    ap.add_argument("--brand-dir", help="private folder with icons/*.png and brand/*.png (C5)")
    ap.add_argument("--selftest", action="store_true", help="unpack the built zip and run its self-test")
    ap.add_argument("--recalc", action="store_true",
                    help="with --selftest: include the LibreOffice recalculation; fails if LibreOffice is missing")
    a = ap.parse_args(argv)
    brand = Path(a.brand_dir).resolve() if a.brand_dir else None
    if brand and not brand.is_dir():
        print(json.dumps({"status": "FAIL", "detail": f"--brand-dir {brand} is not a folder"}))
        return 2
    zpath, manifest = build(Path(a.out).resolve(), brand)
    report = {"status": "BUILT", "zip": manifest["zip"], "zip_sha256": manifest["zip_sha256"],
              "kit_version": manifest["kit_version"], "protocol": manifest["protocol"],
              "built_from": manifest["built_from"], "files": len(manifest["files"]),
              "brand_assets_missing": len(manifest["brand_assets_missing"])}
    rc = 0
    if a.recalc and not a.selftest:
        print(json.dumps({"status": "FAIL", "detail": "--recalc needs --selftest"}))
        return 2
    if a.recalc:
        report["libreoffice"] = libreoffice()
        if not report["libreoffice"]:
            report["status"] = "FAIL"
            report["detail"] = "--recalc asked for, but LibreOffice (soffice) is not installed"
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 1
    if a.selftest:
        st = selftest(zpath, a.recalc)
        failed = [{"step": s.get("step"), "rc": s.get("rc"), "detail": s.get("detail"),
                   "gate_counts": s.get("gate_counts")} for s in st.get("steps", []) if not s.get("ok")]
        report["selftest"] = {"status": st.get("status"), "rc": st.get("rc"), "steps": len(st.get("steps", [])),
                              "recalc": a.recalc,
                              "failed": failed, **({"detail": st["detail"]} if "detail" in st else {})}
        rc = 0 if st.get("status") == "PASS" else 1
        report["status"] = "PASS" if rc == 0 else "FAIL"
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
