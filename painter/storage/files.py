"""Saving attachments and unpacking archives safely."""
from __future__ import annotations

from pathlib import Path
import tarfile
import zipfile

from painter.canvas.client import Canvas


ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"}


def download(canvas: Canvas, url: str, dest: Path,
             expected_size: int | None = None) -> bool:
    """Download a submission attachment. Returns True if newly downloaded.

    Canvas attachment URLs are pre-signed and redirect to blob storage, so
    the Bearer header is NOT sent (some backends reject it). Retries,
    throttling backoff and the .part-then-rename handling come from
    Canvas.fetch_file.
    """
    return canvas.fetch_file(url, dest, expected_size, auth=False)


def extract(archive: Path, dest: Path) -> bool:
    """Extract a zip/tar into dest, refusing any member that escapes dest."""
    dest.mkdir(parents=True, exist_ok=True)
    dest_res = dest.resolve()

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
                        print(f"      ! skipped unsafe path in archive: {name}")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as out:
                        out.write(src.read())
            return True

        if tarfile.is_tarfile(archive):
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    if not member.isreg():
                        continue
                    target = dest / member.name
                    if not is_inside(target):
                        print(f"      ! skipped unsafe path in archive: {member.name}")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tf.extractfile(member) as src, open(target, "wb") as out:
                        out.write(src.read())
            return True
    except Exception as exc:
        print(f"      ! could not extract {archive.name}: {exc}")
    return False
