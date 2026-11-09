"""The chat kit is built from the repository (tools/build_chat_kit.py) and its checks are the engine's v7.15 rules.

The kit's own end-to-end self-test runs in CI (.github/workflows/chat-kit.yml) from the built zip with only
kit/requirements.txt installed; these tests cover the build and the wiring and stay fast.
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_chat_kit as B  # noqa: E402


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("kit")
    zpath, manifest = B.build(out, None)
    return zpath, manifest


def _names(zpath):
    with zipfile.ZipFile(zpath) as z:
        return z.namelist()


def test_kit_carries_scripts_engine_and_manifest(built):
    zpath, manifest = built
    names = _names(zpath)
    top = B.TOP + "/"
    for f in ("cdfkit.py", "kit_stages.py", "kit_selftest.py", "AGENT-GUIDE.md", "requirements.txt",
              "examples/draft-round1.example.json", "cdf_gco_crms/comments/v715.py",
              "cdf_gco_crms/protocol/stage_packets.py", "cdf_gco_crms/documents/ingest.py", "KIT-MANIFEST.json"):
        assert top + f in names, f
    assert manifest["protocol"] == "7.15" and manifest["kit_version"] == B.kit_version()
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


@pytest.mark.skipif(not B.in_git_checkout(), reason="needs a git checkout to list tracked files (a git archive "
                    "export has only tracked files)")
def test_only_tracked_engine_files_enter_the_kit(built):
    zpath, _ = built
    tracked = set(subprocess.run(["git", "ls-files", "cdf_gco_crms", "shared"], cwd=ROOT, capture_output=True,
                                 text=True, check=True).stdout.split())
    shipped = {n[len(B.TOP) + 1:] for n in _names(zpath)}
    engine = {n for n in shipped if n.startswith(("cdf_gco_crms/", "shared/"))}
    assert engine and engine <= tracked
    assert not any(n.startswith("shared/brand/") for n in shipped)   # C5: no brand asset without --brand-dir


def test_missing_brand_assets_are_listed_and_a_brand_dir_supplies_them(built, tmp_path):
    _, manifest = built
    assert "shared/brand/cdf-wordmark-on-light.png" in manifest["brand_assets_missing"]
    assert "shared/icons/palm-ink.png" in manifest["brand_assets_missing"]
    brand = tmp_path / "private"
    (brand / "icons").mkdir(parents=True)
    (brand / "brand").mkdir()
    (brand / "icons" / "palm-ink.png").write_bytes(b"\x89PNG test")
    (brand / "brand" / "cdf-wordmark-on-light.png").write_bytes(b"\x89PNG test")
    zpath, m2 = B.build(tmp_path / "out", brand)
    names = _names(zpath)
    assert B.TOP + "/shared/icons/palm-ink.png" in names
    assert "shared/icons/palm-ink.png" not in m2["brand_assets_missing"]
    assert "shared/brand/cdf-wordmark-on-light.png" not in m2["brand_assets_missing"]


def test_build_is_deterministic(built, tmp_path):
    zpath, _ = built
    again, _ = B.build(tmp_path, None)
    assert hashlib.sha256(zpath.read_bytes()).digest() == hashlib.sha256(again.read_bytes()).digest()


def test_manifest_digests_match_the_zip(built):
    zpath, _ = built
    with zipfile.ZipFile(zpath) as z:
        manifest = json.loads(z.read(B.TOP + "/KIT-MANIFEST.json"))
        for arc, digest in manifest["files"].items():
            assert hashlib.sha256(z.read(f"{B.TOP}/{arc}")).hexdigest() == digest, arc


def _cdfkit():
    spec = importlib.util.spec_from_file_location("cdfkit_under_test", ROOT / "kit" / "cdfkit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _example():
    return json.loads((ROOT / "kit/examples/draft-round1.example.json").read_text(encoding="utf-8"))


def test_kit_check_applies_the_engine_v715_rules():
    K = _cdfkit()
    from cdf_gco_crms.comments import compose_comment
    from cdf_gco_crms.model.entities import plain_text
    d = _example()
    assert K.run_check(d, None)["status"] == "PASS"
    o = d["observations"][0]
    assert plain_text(K.compose_comment(o)) == plain_text(compose_comment(o))     # one composer
    q = dict(o, form="F6", recommendation="هل التجديد التلقائي مقبول للإدارة؟")
    probs = K.field_checks(q, 0, None, 1)
    assert any(p.startswith("07.4A(d)") for p in probs)
    # 00.2 carve-out: a review under an earlier version keeps the earlier comment rules
    assert not any(p.startswith("07.4A") for p in K.field_checks(q, 0, None, 1, protocol="7.14"))
    unseen = dict(o, depends_on_unseen="سياسة الإفصاح")
    assert any(p.startswith("G-SUB-12") for p in K.field_checks(unseen, 0, None, 1))


def test_detector_does_not_count_the_fixed_labels_as_repetition():
    K = _cdfkit()
    det = {x["metric"]: x for x in K.detector(_example()["observations"])}
    p2 = det["P2 connective repetition"]
    assert p2["result"] == "PASS", p2["items"]
    assert "P14 reason sentences and 07.2 ceilings" in det


def test_recalc_needs_libreoffice_and_the_selftest(tmp_path, monkeypatch, capsys):
    """--recalc must prove LibreOffice ran: without soffice the run fails instead of passing silently."""
    assert B.main(["--out", str(tmp_path), "--recalc"]) == 2
    monkeypatch.setattr(B.shutil, "which", lambda name: None)
    assert B.main(["--out", str(tmp_path), "--selftest", "--recalc"]) == 1
    assert "LibreOffice (soffice) is not installed" in capsys.readouterr().out
