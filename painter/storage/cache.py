"""A small on-disk cache of things Painter last learned from Canvas.

It is a display aid: screens show these values at once and confirm them with
Canvas in the background. Losing, damaging or deleting any file only means the
screen waits for Canvas as it always did.

Layout: one folder per kind of data, one JSON file per key inside it.

    <root>/assignments/<key>.json   a course's assignment list
    <root>/rosters/<key>.json       sections and students (names: its own folder)
    <root>/filecounts/<key>.json    files per student per assignment

Adding a kind of data later, for example grade or comment files, is one entry
in KINDS: it gets its own folder, can be cleared on its own, and never mixes
with the others. Nothing of that sort is stored today; the grade and comment
flows do not import this module.

Each file holds {"schema", "fetched_at", "data"}. A file that is missing,
unreadable, from another schema or of an unknown shape reads as "not cached".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

from painter.storage.atomic import atomic_write

SCHEMA = 1


@dataclass(frozen=True)
class Kind:
    directory: str            # folder under the cache root
    students: bool            # holds names or ids of students


KINDS = {
    "assignments": Kind("assignments", students=False),
    "rosters": Kind("rosters", students=True),
    "filecounts": Kind("filecounts", students=True),
}


@dataclass(frozen=True)
class Entry:
    data: object
    fetched_at: datetime      # when Canvas last answered (timezone-aware, UTC)


def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("._") or "_"


class CacheStore:
    def __init__(self, root: Path | str, kinds: dict[str, Kind] | None = None):
        self.root = Path(root)
        self.kinds = dict(KINDS if kinds is None else kinds)

    def path(self, kind: str, key: str) -> Path:
        return self.root / self.kinds[kind].directory / f"{_safe(key)}.json"

    def read(self, kind: str, key: str) -> Entry | None:
        try:
            doc = json.loads(self.path(kind, key).read_text(encoding="utf-8"))
            if doc["schema"] != SCHEMA:
                return None
            at = datetime.fromisoformat(doc["fetched_at"])
            return Entry(doc["data"], at if at.tzinfo else at.replace(tzinfo=timezone.utc))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def write(self, kind: str, key: str, data: object, at: datetime | None = None) -> Entry:
        at = at or datetime.now(timezone.utc)
        doc = {"schema": SCHEMA, "fetched_at": at.isoformat(), "data": data}
        try:
            with atomic_write(self.path(kind, key), "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
        except OSError:
            pass                      # a cache that can't be written is just not there
        return Entry(data, at)

    def forget(self, kind: str, key: str) -> None:
        self.path(kind, key).unlink(missing_ok=True)

    def clear(self, kinds: list[str] | None = None) -> None:
        """Remove everything cached, or only the named kinds."""
        for name in (self.kinds if kinds is None else kinds):
            shutil.rmtree(self.root / self.kinds[name].directory, ignore_errors=True)

    def files(self) -> list[Path]:
        return [p for k in self.kinds.values()
                for p in sorted((self.root / k.directory).glob("*.json"))]

    def size(self) -> int:
        return sum(p.stat().st_size for p in self.files() if p.exists())
