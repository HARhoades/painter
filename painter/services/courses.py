"""Who is signed in and which courses they can work in."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from painter.canvas.client import Canvas
from painter.domain.duedates import parse_ts

ROLES = {"teacher": "Teacher", "ta": "TA"}


@dataclass
class CourseInfo:
    id: int
    name: str
    code: str
    term: str
    term_current: bool
    role: str                             # "Teacher" or "TA" (Teacher if both)
    sections: int
    students: int | None


def whoami(canvas: Canvas) -> str:
    me = canvas.self_user()
    return me.get("short_name") or me.get("name") or str(me.get("id", ""))


def _current(term: dict, now: datetime) -> bool:
    start, end = parse_ts(term.get("start_at")), parse_ts(term.get("end_at"))
    return (start is None or start <= now) and (end is None or now <= end)


def list_courses(canvas: Canvas, now: datetime | None = None) -> list[CourseInfo]:
    """Courses where the user teaches or assists; current term first, then by name."""
    now = now or datetime.now(timezone.utc)
    out = []
    for c in canvas.courses():
        roles = {(e.get("type") or "").lower() for e in c.get("enrollments") or []}
        roles = [ROLES[r] for r in ("teacher", "ta") if r in roles]
        if not roles:
            continue
        term = c.get("term") or {}
        out.append(CourseInfo(
            c["id"], c.get("name", ""), c.get("course_code", ""), term.get("name", ""),
            _current(term, now), roles[0], len(c.get("sections") or []),
            c.get("total_students")))
    out.sort(key=lambda x: (not x.term_current, x.name.lower()))
    return out
