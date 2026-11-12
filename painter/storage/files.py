"""Saving attachments and unpacking archives safely."""
from __future__ import annotations

import bz2
import gzip
import lzma
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import tarfile
import zipfile

from painter.canvas.client import Canvas, FetchResult


ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"}


# Single-file compression (not a tar inside): suffix -> opener.
_COMPRESSED = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}


@dataclass
class ExtractResult:
    """Truthy when the archive was unpacked; notes are lines for the user."""
    ok: bool
    notes: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def download(canvas: Canvas, url: str, dest: Path,
             expected_size: int | None = None) -> FetchResult:
    """Download a submission attachment. Returns True if newly downloaded.

    Canvas attachment URLs are pre-signed and redirect to blob storage, so
    the Bearer header is NOT sent (some backends reject it). Retries,
    throttling backoff and the .part-then-rename handling come from
    Canvas.fetch_file.
    """
    return canvas.fetch_file(url, dest, expected_size, auth=False)


def extract(archive: Path, dest: Path) -> ExtractResult:
    """Extract a zip/tar into dest, refusing any member that escapes dest.

    A .gz/.bz2/.xz that is not a tar is decompressed to one file in dest.
    Members are streamed to disk, never read whole into memory (review
    finding 11).
    """
    dest.mkdir(parents=True, exist_ok=True)
    dest_res = dest.resolve()
    notes: list[str] = []

    def is_inside(target: Path) -> bool:
        try:
            target.resolve().relative_to(dest_res)
            return True
        except ValueError:
            return False

    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    name = member.filename
                    if name.startswith("__MACOSX/") or name.endswith("/"):
                        continue
                    target = dest / name
                    if not is_inside(target):
                        notes.append(f"      ! skipped unsafe path in archive: {name}")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out, 1 << 20)
            return ExtractResult(True, notes)

        if tarfile.is_tarfile(archive):
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    if not member.isreg():
                        continue
                    target = dest / member.name
                    if not is_inside(target):
                        notes.append(f"      ! skipped unsafe path in archive: {member.name}")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tf.extractfile(member) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out, 1 << 20)
            return ExtractResult(True, notes)

        opener = _COMPRESSED.get(archive.suffix.lower())
        if opener is not None:
            target = dest / (archive.stem or "file")
            tmp = target.with_name(target.name + ".part")
            with opener(archive, "rb") as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            tmp.replace(target)
            return ExtractResult(True, notes)
        notes.append(f"      ! {archive.name} is not a readable archive; left as is")
    except Exception as exc:
        notes.append(f"      ! could not extract {archive.name}: {exc}")
    return ExtractResult(False, notes)
