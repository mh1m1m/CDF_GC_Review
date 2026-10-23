"""Safe ingestion of OOXML packages supplied by a requester (15A.6, G-SUB-7; patch V712-005).

Every workbook or Word file that reaches the engine from outside is opened
through :func:`inspect_package` first. The checks fail closed: an unsafe or
malformed package is refused before any part of it is parsed, and nothing
is written. The policy is deliberately narrow:

* a real ZIP container with a ``[Content_Types].xml`` and the main part of
  the declared kind (``xl/workbook.xml`` or ``word/document.xml``);
* no absolute or traversing member names, no symlink-like or duplicate names;
* bounded member count, uncompressed size and compression ratio (zip bomb);
* no VBA project or OLE/ActiveX binaries (macro policy: refused);
* no external links or external data connections in a workbook (refused:
  the register must not pull values from outside the package);
* file extension consistent with the container (``.xlsm`` is refused).

Formula text in data cells is handled by the reader (kept as literal text and
flagged), not here.
"""
from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_MEMBERS = 4000
MAX_UNCOMPRESSED = 400 * 1024 * 1024       # 400 MB
MAX_MEMBER_UNCOMPRESSED = 200 * 1024 * 1024
MAX_RATIO = 400.0                          # uncompressed / compressed, over the whole package
ALLOWED_SUFFIX = {"xlsx": (".xlsx",), "docx": (".docx",)}
MAIN_PART = {"xlsx": "xl/workbook.xml", "docx": "word/document.xml"}
MACRO_PARTS = ("vbaproject.bin", "vbadata.xml", "/activex/", "/embeddings/", ".bin")
EXTERNAL_PARTS = ("xl/externallinks/", "xl/connections.xml", "xl/queryTables/".lower(), "customxml/".lower())


class IngestError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class IngestReport:
    path: str
    kind: str
    sha256: str
    members: int = 0
    uncompressed: int = 0
    compressed: int = 0
    findings: list[tuple[str, str]] = field(default_factory=list)      # (code, detail)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_package(path, kind: str = "xlsx", *, allow_external: bool = False) -> IngestReport:
    path = Path(path)
    if kind not in MAIN_PART:
        raise ValueError(kind)
    if not path.is_file():
        raise IngestError("NOT_A_FILE", str(path))
    rep = IngestReport(path=str(path), kind=kind, sha256=sha256_file(path))
    if path.suffix.lower() not in ALLOWED_SUFFIX[kind]:
        rep.findings.append(("BAD_EXTENSION", f"{path.suffix!r} is not accepted for a {kind} package"))
    if not zipfile.is_zipfile(path):
        rep.findings.append(("NOT_OOXML", "the file is not a ZIP container"))
        return rep
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            rep.members = len(infos)
            if rep.members > MAX_MEMBERS:
                rep.findings.append(("TOO_MANY_PARTS", f"{rep.members} members > {MAX_MEMBERS}"))
            names = [i.filename for i in infos]
            seen: set[str] = set()
            for i in infos:
                n = i.filename
                norm = n.replace("\\", "/")
                if norm.startswith("/") or norm[1:3] == ":/" or ".." in norm.split("/"):
                    rep.findings.append(("PATH_TRAVERSAL", n))
                if norm in seen:
                    rep.findings.append(("DUPLICATE_PART", n))
                seen.add(norm)
                if i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    rep.findings.append(("UNSUPPORTED_COMPRESSION", f"{n}: method {i.compress_type}"))
                if i.file_size > MAX_MEMBER_UNCOMPRESSED:
                    rep.findings.append(("PART_TOO_LARGE", f"{n}: {i.file_size} bytes"))
                rep.uncompressed += i.file_size
                rep.compressed += i.compress_size
                low = norm.lower()
                if any(m in low for m in MACRO_PARTS) and not low.endswith((".png", ".jpg", ".jpeg", ".emf", ".wmf")):
                    rep.findings.append(("MACRO_OR_BINARY_PART", n))
                if kind == "xlsx" and any(low.startswith(e) or e in low for e in EXTERNAL_PARTS):
                    (rep.warnings if allow_external else rep.findings).append(("EXTERNAL_LINK", n) if not allow_external else f"external part {n}")
            if rep.uncompressed > MAX_UNCOMPRESSED:
                rep.findings.append(("PACKAGE_TOO_LARGE", f"{rep.uncompressed} bytes uncompressed"))
            if rep.compressed and rep.uncompressed / max(rep.compressed, 1) > MAX_RATIO:
                rep.findings.append(("COMPRESSION_BOMB", f"ratio {rep.uncompressed / rep.compressed:.0f}"))
            if "[Content_Types].xml" not in names:
                rep.findings.append(("NO_CONTENT_TYPES", "[Content_Types].xml missing"))
            if MAIN_PART[kind] not in names:
                rep.findings.append(("NO_MAIN_PART", f"{MAIN_PART[kind]} missing"))
            # the content types must not declare a macro-enabled main document
            if "[Content_Types].xml" in names:
                ct = z.read("[Content_Types].xml")[:200000].decode("utf-8", "replace").lower()
                if "macroenabled" in ct or "vbaproject" in ct:
                    rep.findings.append(("MACRO_CONTENT_TYPE", "macro-enabled content type declared"))
            bad = z.testzip()
            if bad:
                rep.findings.append(("CORRUPT_PART", bad))
    except zipfile.BadZipFile as e:
        rep.findings.append(("BAD_ZIP", str(e)))
    except (RuntimeError, OSError, ValueError) as e:                 # encrypted or truncated containers
        rep.findings.append(("UNREADABLE", str(e)))
    return rep


def require_safe(path, kind: str = "xlsx", **kw) -> IngestReport:
    """Return the report of a safe package or raise :class:`IngestError` (fail closed)."""
    rep = inspect_package(path, kind, **kw)
    if not rep.ok:
        code, detail = rep.findings[0]
        raise IngestError(code, f"{Path(path).name}: {detail}" + (f" (+{len(rep.findings) - 1} more)" if len(rep.findings) > 1 else ""))
    return rep
