"""Roster CSV export."""
from __future__ import annotations

import csv
from pathlib import Path
import sys

from painter.canvas.client import Canvas
from painter.domain.selection import select_students
from painter.domain.roster import (
    Roster, assigned_students, section_instructors, split_name,
)


# --------------------------------------------------------------------------
# Exporting the roster to CSV
# --------------------------------------------------------------------------
ROSTER_CSV_COLUMNS = [
    "Student Full Name", "Student Canvas ID", "Student First Name",
    "Student Last Name", "Instructor Last Name", "Section Name",
    "Section Canvas ID",
]


def export_roster_csv(canvas: Canvas, args) -> int:
    """--roster-csv: one line per student (per section), sorted by last name."""
    roster = Roster(canvas.sections(args.course),
                    canvas.student_enrollments(args.course))
    student_ids, section_ids = select_students(roster, args)
    if args.assignment:
        assigned = assigned_students(canvas, args.course, args.assignment)
        student_ids = assigned if student_ids is None else student_ids & assigned
    instructors = section_instructors(canvas, args.course)

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

    path = Path(args.roster_csv)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=ROSTER_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    students = len({r["Student Canvas ID"] for r in rows})
    extra = len(rows) - students
    print(f"{students} student(s), {len(rows)} line(s) -> {path}")
    if extra:
        print(f"  note: {extra} extra line(s) for students in more than one "
              "section; filter with --section to keep one", file=sys.stderr)
    no_teacher = sorted({r["Section Name"] for r in rows
                         if not r["Instructor Last Name"]})
    if no_teacher:
        print("  note: no instructor enrolled in: " + ", ".join(
            n or "(no section)" for n in no_teacher), file=sys.stderr)
    return 0
