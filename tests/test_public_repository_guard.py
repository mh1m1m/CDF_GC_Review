"""Content-aware public repository guard (audit C1–C4 follow-up), on a throwaway git repository."""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / "tools/mat_dna/public_repository_guard.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

# Assembled at run time so this file never contains a literal match for the rules it tests.
FAKE_ID = "0AbCdEfGhIjKlMnOpQrStUvWxYz123"
DRIVE = "https://drive." + "google.com/file/d/" + FAKE_ID + "/view"
DOCS = "https://docs." + "google.com/document/d/" + FAKE_ID + "/edit"
KUNYA_TEXT = "التأكيد من قبل " + "الأخ " + "أبو " + "فهد"


def _repo(tmp_path, files: dict[str, str]):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-qm", "c"], check=True)
    return sorted(files)


def test_drive_links_and_kunya_references_are_findings(tmp_path):
    files = _repo(tmp_path, {
        "a.json": '{"source": "' + DRIVE + '"}',
        "b.tsx": "<p>" + KUNYA_TEXT + "</p>",
        "ok.py": 'PLACEHOLDER = "الأخ فلان"  # fictional, no kunya',
    })
    findings = G.scan_tree(tmp_path, files, [])
    assert "SHAREABLE_DRIVE_LINK:a.json" in findings and "PERSONAL_REFERENCE:b.tsx" in findings
    assert not [f for f in findings if f.endswith(":ok.py")]


def test_private_denylist_matches_spelling_variants_and_never_prints_the_term(tmp_path):
    files = _repo(tmp_path, {"c.md": "ملاحظات المراجع المستعار إبراهيم الفلاني على الملف"})
    deny = G.load_denylist({"CDF_PRIVATE_DENYLIST_TERMS": "# comment\nابراهيم الفلانى\nxy"}, root=tmp_path)
    assert deny == [G.fold("ابراهيم الفلانى")], "comments and too-short terms are ignored"
    findings = G.scan_tree(tmp_path, files, deny)
    assert findings == ["PRIVATE_DENYLIST_TERM:c.md:#1"], "hamza and alef-maqsura variants still match"
    assert "الفلان" not in " ".join(findings), "the finding names the term index, never the term"


def test_history_scan_finds_content_removed_from_the_tip(tmp_path):
    _repo(tmp_path, {"d.json": '{"url": "' + DOCS + '"}'})
    (tmp_path / "d.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-qam", "remove"], check=True)
    assert G.scan_tree(tmp_path, ["d.json"], []) == []
    assert any(f.endswith("SHAREABLE_DRIVE_LINK:d.json") for f in G.scan_history(tmp_path, []))


def test_current_public_tree_passes_the_public_rules():
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    findings = [f for f in G.scan_tree(ROOT, [f for f in files if f], []) if not f.startswith("PRIVATE_DENYLIST")]
    assert findings == []
