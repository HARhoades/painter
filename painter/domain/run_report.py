"""What a download found, per student and per assignment, from the manifest rows.

The rows are the ones written to manifest.csv and the Excel log (one per file).
This turns them into what an instructor scans for: who was late and by how
long, who resubmitted, how many submitted. Scores are not used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

_PART = re.compile(r"(\d+)\s*([dhm])")


def late_minutes(late_by: str) -> int:
    """'2d 3h 14m' -> minutes ('<1m' is 0, '' is 0)."""
    unit = {"d": 1440, "h": 60, "m": 1}
    if (late_by or "").startswith("<"):
        return 0
    return sum(int(n) * unit[u] for n, u in _PART.findall(late_by or ""))


@dataclass
class StudentLine:
    """One student's submission to one assignment."""
    assignment: str
    assignment_id: int
    student: str
    user_id: int
    section: str
    submitted_at: str = ""
    attempts: int = 0          # Canvas's attempt number: how many times they submitted
    late: bool = False
    late_by: str = ""
    excused: bool = False
    files: int = 0
    failed: int = 0

    @property
    def late_minutes(self) -> int:
        return late_minutes(self.late_by)


@dataclass
class AssignmentLine:
    assignment: str
    assignment_id: int
    students: int = 0
    files: int = 0
    late: int = 0
    resubmitted: int = 0
    excused: int = 0
    failed: int = 0
    latest_late: str = ""      # the longest late-by, as written


@dataclass
class RunReport:
    students: list[StudentLine] = field(default_factory=list)
    assignments: list[AssignmentLine] = field(default_factory=list)

    @property
    def late(self) -> list[StudentLine]:
        return sorted((s for s in self.students if s.late),
                      key=lambda s: -s.late_minutes)


def _attempt(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_report(rows: list[dict]) -> RunReport:
    """Group the per-file rows by assignment and student."""
    lines: dict[tuple, StudentLine] = {}
    for r in rows:
        key = (r.get("assignment_id"), r.get("user_id"))
        line = lines.get(key)
        if line is None:
            line = lines[key] = StudentLine(
                r.get("assignment", ""), r.get("assignment_id"), r.get("student", ""),
                r.get("user_id"), r.get("section", ""))
        attempt = _attempt(r.get("attempt"))
        if attempt >= line.attempts:     # the latest attempt decides the dates
            line.attempts = attempt
            line.submitted_at = r.get("submitted_at", "") or line.submitted_at
            line.late = bool(r.get("late")) or bool(r.get("late_by"))
            line.late_by = r.get("late_by", "") or ""
            line.excused = r.get("late_policy_status") == "excused"
        line.files += 1
        line.failed += str(r.get("status", "")).startswith("failed")
    report = RunReport(sorted(lines.values(), key=lambda s: (s.assignment, s.student)))
    per: dict = {}
    for s in report.students:
        a = per.setdefault(s.assignment_id, AssignmentLine(s.assignment, s.assignment_id))
        a.students += 1
        a.files += s.files
        a.late += s.late
        a.resubmitted += s.attempts > 1
        a.excused += s.excused
        a.failed += s.failed
        if s.late and s.late_minutes >= late_minutes(a.latest_late):
            a.latest_late = s.late_by
    report.assignments = sorted(per.values(), key=lambda a: a.assignment)
    return report
