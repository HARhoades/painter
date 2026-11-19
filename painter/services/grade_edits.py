"""Editing a grade file in place: only the grade= and comments= lines of the
students that changed are rewritten; every other byte of the file stays as it was."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from painter.services.grade_files import (
    GRADE_FILE_KEYS, GradeEntry, GradeFile, GradeFileError, grade_file_from_blocks,
    parse_grade_file, read_blocks_text,
)
from painter.storage.atomic import atomic_write

INDENT = "    "            # continuation lines of a comment
BOM = "﻿"

# A comment line that would be read back as something else: a block header, or
# a key of a [STUDENT] block (which would end the comment and change that field).
_HEADER = re.compile(r"^\s*\[\s*[A-Za-z]+\s*\]\s*$")
_KEY = re.compile(r"^\s*(" + "|".join(GRADE_FILE_KEYS["STUDENT"]) + r")\s*=", re.I)


class EditRefused(ValueError):
    """A value that can't be written safely; the message says why, in words."""


class FileChanged(Exception):
    """The file changed on disk after it was read (another program saved it)."""

    def __init__(self, path: Path):
        super().__init__(f"{path.name} changed on disk after Painter read it.")
        self.path = path


@dataclass(frozen=True)
class Stamp:
    """What a file looked like when it was read: enough to notice a change."""
    mtime_ns: int
    size: int

    @classmethod
    def of(cls, path: Path) -> "Stamp":
        st = Path(path).stat()
        return cls(st.st_mtime_ns, st.st_size)


@dataclass
class Edit:
    """New values for one student, found by GradeEntry.key."""
    key: str
    grade: str
    comments: str


def refusal(grade: str, comments: str) -> str:
    """Why these values can't go into a grade file, or "" when they can."""
    if "\n" in grade or "\r" in grade:
        return "A grade must fit on one line."
    for n, line in enumerate(comments.strip().splitlines()[1:], start=2):
        if _HEADER.match(line):
            return (f"Comment line {n} looks like a block header ({line.strip()}); "
                    "the file would read it as a new block. Reword that line.")
        if _KEY.match(line):
            word = _KEY.match(line).group(1).lower()
            return (f"Comment line {n} starts with “{word}=”; the file would read it as the "
                    f"student's {word}. Reword that line, e.g. add a word before it.")
    return ""


def grade_warnings(grade: str) -> list[str]:
    """Basic checks of a grade, without asking Canvas (Review checks it properly)."""
    g = grade.strip()
    if not g:
        return []
    out = []
    number = g[:-1].strip() if g.endswith("%") else g
    try:
        value = float(number)
    except ValueError:
        value = None
        if g.endswith("%"):
            out.append(f"“{g}” isn't a percentage.")
        elif any(c.isdigit() for c in g) and not re.fullmatch(r"[A-Fa-f][+-]?", g):
            out.append(f"“{g}” mixes digits and letters.")
    if value is not None and value < 0:
        out.append("The grade is negative.")
    if " " in g:
        out.append("The grade has a space in it.")
    return out


def _value_lines(key: str, value: str, newline: str) -> list[str]:
    if key == "grade":
        return [f"grade={value.strip()}{newline}"]
    parts = [ln.strip() for ln in value.strip().splitlines()] or [""]
    return [f"comments={parts[0]}{newline}"] + [
        (f"{INDENT}{ln}" if ln else "") + newline for ln in parts[1:]]


def _apply(lines: list[str], block: dict, edit: Edit, newline: str) -> None:
    """Rewrite one student's grade= and comments= lines in `lines` (0-based list,
    1-based spans). The later field is done first, so the earlier span still holds."""
    spans = block["_spans"]
    jobs = [(k, spans.get(k)) for k in ("grade", "comments")]
    jobs.sort(key=lambda kv: kv[1][0] if kv[1] else 10**9, reverse=True)
    for key, span in jobs:
        new = _value_lines(key, getattr(edit, key), newline)
        if span:
            lines[span[0] - 1:span[1]] = new
        else:                                   # a field that wasn't in the block yet
            lines[block["_end"]:block["_end"]] = new


def _student_blocks(path: Path, blocks: list[dict]) -> dict[str, dict]:
    """[STUDENT] blocks by key; two blocks for one student is refused."""
    out: dict[str, dict] = {}
    for b in blocks:
        if b["_kind"] != "STUDENT" or not ((b.get("name") or "").strip()
                                           or (b.get("id") or "").strip()):
            continue
        key = GradeEntry(b["_line"], (b.get("name") or "").strip(),
                         (b.get("id") or "").strip(), "", "").key
        if key in out:
            raise GradeFileError(path, b["_line"], "the same student appears twice")
        out[key] = b
    return out


def edited_text(path: Path, text: str, edits: list[Edit]) -> str:
    """The file's text with the edits made. Raises EditRefused or GradeFileError."""
    for e in edits:
        why = refusal(e.grade, e.comments)
        if why:
            raise EditRefused(why)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    by_key = _student_blocks(path, read_blocks_text(path, text))
    for e in sorted(edits, key=lambda e: -by_key[e.key]["_line"] if e.key in by_key else 0):
        if e.key not in by_key:
            raise EditRefused(f"{e.key.split(':', 1)[1]} is no longer in {path.name}.")
        _apply(lines, by_key[e.key], e, newline)
    return "".join(lines)


def save_edits(path: Path, edits: list[Edit], expected: Stamp | None) -> GradeFile:
    """Write the edits into the file and return it as read back from disk.

    expected: the file's Stamp when it was read; a different one now raises
    FileChanged and writes nothing. None overwrites whatever is there (the
    edited students' grades and comments win; the rest of the file is kept).
    The new text is parsed and checked before it replaces the file, and the
    write is flushed to disk before this returns.
    """
    path = Path(path)
    if expected is not None and Stamp.of(path) != expected:
        raise FileChanged(path)
    raw = path.read_bytes().decode("utf-8")
    bom = raw.startswith(BOM)
    text = raw[1:] if bom else raw
    new = edited_text(path, text, edits)
    check = grade_file_from_blocks(path, read_blocks_text(path, new))
    got = {s.key: s for s in check.students}
    for e in edits:
        s = got.get(e.key)
        if s is None or s.grade != e.grade.strip() or s.comments != _norm(e.comments):
            raise EditRefused(f"The change for {e.key.split(':', 1)[1]} wouldn't read back "
                              "the same, so nothing was saved.")
    with atomic_write(path, "w", durable=True, encoding="utf-8", newline="") as fh:
        fh.write((BOM if bom else "") + new)
    return parse_grade_file(path)


def _norm(comments: str) -> str:
    """Comments as the parser returns them: lines stripped, ends trimmed."""
    return "\n".join(ln.strip() for ln in comments.strip().splitlines()).strip()
