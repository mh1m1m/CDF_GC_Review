"""Untrusted OOXML archive admission checks used by private offline importers.

Never unzip to the filesystem. Reject traversal names, encrypted members,
zip bombs, oversized decompressed content and unusually large entry counts.
"""
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .store import CalibrationError

MAX_FILES = 2400
MAX_UNCOMPRESSED_BYTES = 110 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 40 * 1024 * 1024
MAX_RATIO = 250


def check_ooxml_zip(path: str | Path, *, max_compressed: int):
    p=Path(path)
    if p.is_symlink() or not p.is_file():
        raise CalibrationError("UNSAFE_INPUT_PATH")
    if not (0 < p.stat().st_size <= max_compressed):
        raise CalibrationError("OOXML_COMPRESSED_SIZE_OUT_OF_RANGE")
    with p.open("rb") as handle:
        if handle.read(4)!=b"PK\x03\x04":
            raise CalibrationError("OOXML_INVALID_PACKAGE_SIGNATURE")
    try:
        with ZipFile(p) as z:
            entries=z.infolist()
            if len(entries)>MAX_FILES:
                raise CalibrationError("OOXML_TOO_MANY_PARTS")
            if not any(x.filename=="[Content_Types].xml" for x in entries):
                raise CalibrationError("OOXML_CONTENT_TYPES_MISSING")
            total=0
            for entry in entries:
                name=entry.filename.replace("\\","/")
                if name.startswith("/") or "/../" in "/"+name+"/" or ":" in name.split("/")[0] or "\x00" in name:
                    raise CalibrationError("OOXML_UNSAFE_MEMBER_PATH")
                if entry.flag_bits & 1:
                    raise CalibrationError("OOXML_ENCRYPTED_MEMBER_DISALLOWED")
                if entry.file_size>MAX_SINGLE_FILE_BYTES:
                    raise CalibrationError("OOXML_OVERSIZE_PART")
                total+=entry.file_size
                if total>MAX_UNCOMPRESSED_BYTES:
                    raise CalibrationError("OOXML_DECOMPRESSION_LIMIT")
                if entry.file_size>1024*1024 and entry.file_size/max(entry.compress_size,1)>MAX_RATIO:
                    raise CalibrationError("OOXML_EXCESSIVE_COMPRESSION_RATIO")
    except BadZipFile as exc:
        raise CalibrationError("OOXML_INVALID_ZIP") from exc
