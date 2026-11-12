"""Where a quiz export goes, whose answers it keeps, and matching report rows to students."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from painter.canvas.client import Canvas
from painter.domain.selection import Selection
from painter.events import NULL, Reporter, emit
from painter.domain.assignments import assignment_folder
from painter.domain.matching import _letters
from painter.domain.naming import slug
from painter.domain.roster import Roster, assigned_students


@dataclass
class QuizExportPlan:
    """Where a quiz export goes and whose answers it keeps."""
    dirs: list[Path]                        # every output folder
    selected: set[int] | None = None        # students to keep; None = everyone
    dir_of: dict[int, Path] | None = None   # with --by-section: student -> folder
    roster: Roster | None = None


def quiz_export_plan(canvas: Canvas, course_id: int, out_root: Path, assignment: dict,
                     selection: Selection = Selection(), by_section: bool = False,
                     reporter: Reporter = NULL) -> QuizExportPlan | None:
    """Apply --section/--student/--by-section to a quiz export.

    The filters pick whose answers are kept: selected students who are
    assigned the quiz. With --by-section each of their sections gets a folder
    holding that section's answers plus a copy of the quiz content. Returns
    None when no selected student is assigned the quiz.
    """
    adir, note = assignment_folder(Path(out_root), assignment)
    if note:
        reporter.warning(note)
    if not (selection.active or by_section):
        return QuizExportPlan([adir])
    roster = Roster.load(canvas, course_id)
    chosen_ = selection.resolve(roster)
    emit(chosen_.notes, reporter)
    student_ids, section_ids = chosen_.student_ids, chosen_.section_ids
    assigned = assigned_students(canvas, course_id, [assignment["id"]])
    chosen = assigned if student_ids is None else student_ids & assigned
    if student_ids is not None:
        reporter.info(f"{len(chosen)} of {len(student_ids)} selected student(s) are "
              "assigned this quiz.")
    if not chosen:
        return None
    selected = chosen if student_ids is not None else None
    if not by_section:
        return QuizExportPlan([adir], selected, None, roster)
    dir_of = {u: adir / slug((roster.primary_section(u, section_ids) or {}).get("name")
                             or "no-section", 40) for u in chosen}
    dirs = sorted(set(dir_of.values()), key=lambda d: d.name.casefold())
    return QuizExportPlan(dirs, selected, dir_of, roster)


def find_student_column(header: list[str], rows: list[list[str]],
                        roster: Roster) -> tuple[int, str, dict] | None:
    """Which report column identifies the student, judged by its values.

    Instructure does not document the report's columns, so this does not
    rely on header names: it picks the column whose values match the course
    roster best -- Canvas user IDs first, then SIS IDs, logins, and finally
    names. Returns (column index, what it matched, value -> user id).
    """
    users = roster.users.values()
    by_name: dict[str, set[int]] = {}
    for u in users:
        for n in (u.get("name"), u.get("sortable_name")):
            if _letters(n):
                by_name.setdefault(_letters(n), set()).add(u["id"])
    lookups = [
        ("Canvas user ID", {str(u["id"]): u["id"] for u in users}, str.strip),
        ("SIS user ID", {str(u["sis_user_id"]): u["id"] for u in users
                         if u.get("sis_user_id")}, str.strip),
        ("login", {str(u["login_id"]).casefold(): u["id"] for u in users
                   if u.get("login_id")}, lambda v: v.strip().casefold()),
        ("name", {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1},
         _letters),
    ]
    hinted = ("id", "user", "student", "name", "login", "sis")
    for kind, mapping, norm in lookups:
        best = None
        for c, head in enumerate(header):
            vals = [r[c] for r in rows if c < len(r) and r[c].strip()]
            if not vals:
                continue
            rate = sum(norm(v) in mapping for v in vals) / len(vals)
            score = (rate, any(h in head.casefold() for h in hinted))
            if rate >= 0.6 and (best is None or score > best[0]):
                best = (score, c)
        if best:
            c = best[1]
            return c, kind, {v: mapping[norm(v)] for v in
                             {r[c] for r in rows if c < len(r)} if norm(v) in mapping}
    return None
