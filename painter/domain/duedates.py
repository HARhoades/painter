"""Canvas timestamps and effective due dates."""
from __future__ import annotations

from datetime import datetime


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
def parse_ts(value: str | None):
    """Canvas returns ISO 8601 in UTC, e.g. 2026-03-04T23:59:00Z."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_ts(value: str | None, tz=None) -> str:
    """Render a Canvas timestamp, optionally converted to a local zone."""
    dt = parse_ts(value)
    if dt is None:
        return ""
    if tz is not None:
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M")


def fmt_lateness(seconds) -> str:
    """seconds_late -> '2d 3h 14m'. Canvas reports 0 when on time."""
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return " ".join(p for p in (f"{d}d" if d else "", f"{h}h" if h else "",
                                f"{m}m" if m else "") if p) or "<1m"


class DueDates:
    """Effective due date per student for one assignment.

    Precedence follows Canvas: an ad-hoc (per-student) override beats a
    section override, which beats the base "Everyone" date. If a student sits
    in two overridden sections Canvas applies the most lenient date, so the
    latest of the candidates is used here.
    """

    def __init__(self, assignment: dict):
        self.base = assignment.get("due_at")
        self.by_section: dict[int, str | None] = {}
        self.by_user: dict[int, str | None] = {}

        for date in assignment.get("all_dates") or []:
            if date.get("base"):
                self.base = date.get("due_at")

        for ov in assignment.get("overrides") or []:
            due = ov.get("due_at")
            if "course_section_id" in ov and ov["course_section_id"]:
                self.by_section[ov["course_section_id"]] = due
            for uid in ov.get("student_ids") or []:
                self.by_user[uid] = due

    def effective(self, user_id: int, section_ids: list[int]) -> tuple[str | None, str]:
        """Returns (due_at, source-label)."""
        if user_id in self.by_user:
            return self.by_user[user_id], "student override"

        candidates = [(self.by_section[s], s) for s in section_ids
                      if s in self.by_section]
        if candidates:
            if any(due is None for due, _ in candidates):
                return None, "section override (no due date)"
            latest = max(candidates, key=lambda c: parse_ts(c[0]))
            label = "section override"
            if len(candidates) > 1:
                label += " (most lenient of %d)" % len(candidates)
            return latest[0], label

        return self.base, "everyone"


def parse_tz(name: str | None):
    """A tzinfo for an IANA zone name, or None for UTC as Canvas returns it.
    Raises errors.InvalidInput for an unknown name."""
    if not name:
        return None
    from painter.errors import InvalidInput
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception as exc:
        raise InvalidInput(f"Unknown timezone {name!r}: {exc}")
