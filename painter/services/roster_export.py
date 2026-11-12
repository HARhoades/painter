"""Roster CSV export."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from painter.canvas.client import Canvas
from painter.domain.roster import (
    Roster, section_instructors, split_name,
)
from painter.domain.selection import Selection
from painter.events import NULL, Reporter, emit
from painter.storage.tabular import write_csv


# --------------------------------------------------------------------------
# Exporting the roster to CSV
# --------------------------------------------------------------------------
ROSTER_CSV_COLUMNS = [
    "Student Full Name", "Student Canvas ID", "Student First Name",
    "Student Last Name", "Instructor Last Name", "Section Name",
    "Section Canvas ID",
]


@dataclass
class RosterExportRequest:
    course_id: int
    path: Path
    selection: Selection = field(default_factory=Selection)
    assignment_ids: tuple[int, ...] = ()     # keep only students who have these


@dataclass
class RosterExportResult:
    path: Path
    rows: list[dict]
    students: int
    extra_lines: int                          # students in more than one section
    sections_without_instructor: list[str]


def export_roster_csv(canvas: Canvas, req: RosterExportRequest,
                      reporter: Reporter = NULL) -> RosterExportResult:
    """One line per student (per section), sorted by last name."""
    roster = Roster.load(canvas, req.course_id)
    chosen = req.selection.resolve_assigned(canvas, roster, req.course_id,
                                            req.assignment_ids)
    emit(chosen.notes, reporter)
    student_ids, section_ids = chosen.student_ids, chosen.section_ids
    instructors = section_instructors(canvas, req.course_id)

    rows = []
    for uid, user in roster.users.items():
        if student_ids is not None and uid not in student_ids:
            continue
        first, last = split_name(user)
        full = " ".join(part for part in (first, last) if part)
        sids = roster.sections_of_user.get(uid, [])
        if section_ids:
            # A student added with --student may sit outside the selected
            # sections; keep their own sections rather than dropping them.
            sids = [s for s in sids if s in section_ids] or sids
        for sid in sids or [None]:
            section = roster.section_by_id.get(sid, {}) if sid is not None else {}
            rows.append({
                "Student Full Name": full,
                "Student Canvas ID": uid,
                "Student First Name": first,
                "Student Last Name": last,
                "Instructor Last Name": "; ".join(instructors.get(sid, [])),
                "Section Name": section.get("name", ""),
                "Section Canvas ID": sid if sid is not None else "",
            })

    rows.sort(key=lambda r: (r["Student Last Name"].casefold(),
                             r["Student First Name"].casefold(),
                             str(r["Student Canvas ID"]),
                             r["Section Name"].casefold()))

    path = write_csv(Path(req.path), ROSTER_CSV_COLUMNS, rows)

    students = len({r["Student Canvas ID"] for r in rows})
    extra = len(rows) - students
    reporter.info(f"{students} student(s), {len(rows)} line(s) -> {path}")
    if extra:
        reporter.warning(f"  note: {extra} extra line(s) for students in more than one "
                         "section; filter with --section to keep one")
    no_teacher = sorted({r["Section Name"] for r in rows
                         if not r["Instructor Last Name"]})
    if no_teacher:
        reporter.warning("  note: no instructor enrolled in: " + ", ".join(
            n or "(no section)" for n in no_teacher))
    return RosterExportResult(path, rows, students, extra, no_teacher)
