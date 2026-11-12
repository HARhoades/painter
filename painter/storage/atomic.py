"""Write a file so that it is either complete or not there at all."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_write(path: Path, mode: str = "w", **open_kwargs):
    """Open <path>.part for writing; rename it to path only if the block ends
    without an exception, otherwise delete it. An interrupted run never leaves
    a truncated file under the real name. Parent folders are created.

        with atomic_write(dest, "w", newline="", encoding="utf-8-sig") as fh:
            ...
    """
    if "w" not in mode:
        raise ValueError("atomic_write is for writing; mode must contain 'w'")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    fh = open(tmp, mode, **open_kwargs)
    try:
        yield fh
    except BaseException:
        fh.close()
        tmp.unlink(missing_ok=True)
        raise
    fh.close()
    tmp.replace(path)
