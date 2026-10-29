"""ZIP helpers used by the web UI."""

import io
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Union


def make_zip_bytes(folder: Path) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(folder).as_posix())
    return bio.getvalue()


def safe_extract_zip(src: Union[str, Path, BinaryIO], dest: Path) -> None:
    """Extract a ZIP, rejecting entries that would escape ``dest`` ("Zip Slip")."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            name = PurePosixPath(info.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or ":" in info.filename:
                raise ValueError(f"unsafe path in ZIP: {info.filename}")
        zf.extractall(dest)
