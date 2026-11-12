"""Posting grades and comments: plan, post, verify."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import sys

import requests

from painter.canvas.client import Canvas
from painter.domain.matching import name_matches
from painter.domain.roster import Roster
from painter.services.grade_files import (
    GradeEntry, GradeFile, GradeFileError, parse_grade_file,
)


EXCUSED_WORDS = {"ex", "excused", "excuse"}


PASS_FAIL_WORDS = {"pass", "fail", "complete", "incomplete"}


@dataclass
class PlannedGrade:
    entry: GradeEntry
    user_id: int
    student: str
    fields: dict[str, str]     # what goes into grade_data[<user_id>]
    grade_before: str
    comment_skipped: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class GradePlan:
    source: GradeFile
    course_id: int
    assignment: dict
    section: dict | None
    items: list[PlannedGrade]
    notes: list[str] = field(default_factory=list)

    @property
    def to_send(self) -> list[PlannedGrade]:
        return [it for it in self.items if it.fields]


def resolve_grade_entry(roster: Roster, entry: GradeEntry,
                        section_id: int | None) -> dict:
    """Find the roster user a [STUDENT] block refers to, or raise LookupError."""
    def label(u: dict) -> str:
        return f"{u.get('sortable_name') or u.get('name')} ({u['id']})"

    if entry.id:
        hits = [u for u in roster.users.values()
                if entry.id in {str(u.get("id", "")),
                                str(u.get("sis_user_id") or ""),
                                str(u.get("login_id") or "")}]
        if not hits:
            raise LookupError(f"no student in the course has id {entry.id}")
        if len(hits) > 1:
            raise LookupError(f"id {entry.id} matches several students: "
                              + ", ".join(label(u) for u in hits))
        user = hits[0]
        if entry.name and not name_matches(entry.name, user):
            raise LookupError(f"id {entry.id} is {label(user)}, not {entry.name!r}")
        return user

    hits = [u for u in roster.users.values() if name_matches(entry.name, u)]
    if len(hits) > 1 and section_id:
        in_section = [u for u in hits
                      if section_id in roster.sections_of_user.get(u["id"], [])]
        if in_section:
            hits = in_section
    if not hits:
        raise LookupError(f"no student named {entry.name!r} in the course")
    if len(hits) > 1:
        raise LookupError(f"{entry.name!r} matches several students ("
                          + ", ".join(label(u) for u in hits) + "); add id=")
    return hits[0]


def grade_fields(entry: GradeEntry, assignment: dict) -> tuple[dict[str, str], list[str]]:
    """The grade_data fields for one student, checked against the grading type.

    Raises ValueError for a grade Canvas would reject or misread; returns
    warnings for grades that are legal but worth a second look.
    """
    fields: dict[str, str] = {}
    warnings: list[str] = []
    grade = entry.grade
    gtype = assignment.get("grading_type") or "points"

    if grade:
        if grade.casefold() in EXCUSED_WORDS:
            fields["excuse"] = "true"
        elif gtype == "not_graded":
            raise ValueError("the assignment is set to 'not graded', but a grade was given")
        elif gtype in ("points", "percent"):
            m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(%?)", grade)
            if not m:
                raise ValueError(f"grade {grade!r} is not a number "
                                 f"(the assignment is graded by {gtype})")
            value = float(m.group(1))
            pts = assignment.get("points_possible")
            if value < 0:
                warnings.append(f"grade {grade} is negative")
            elif gtype == "points" and not m.group(2) and pts is not None and value > pts:
                warnings.append(f"grade {grade} is above points possible ({pts:g})")
            elif (gtype == "percent" or m.group(2)) and value > 100:
                warnings.append(f"grade {grade} is above 100%")
            fields["posted_grade"] = m.group(1) + m.group(2)
        elif gtype == "pass_fail":
            if grade.casefold() not in PASS_FAIL_WORDS:
                raise ValueError(f"grade {grade!r} must be one of "
                                 + "/".join(sorted(PASS_FAIL_WORDS)))
            fields["posted_grade"] = grade.casefold()
        else:
            # letter_grade / gpa_scale: Canvas checks it against the grading scheme
            fields["posted_grade"] = grade

    if entry.comments:
        fields["text_comment"] = entry.comments
    return fields, warnings


def _norm_comment(text: str | None) -> str:
    return " ".join((text or "").split())


def _grade_before(sub: dict | None) -> str:
    if not sub:
        return ""
    if sub.get("excused"):
        return "EXCUSED"
    return str(sub.get("entered_grade") or sub.get("grade") or "")


def plan_grade_file(canvas: Canvas, gf: GradeFile, course_id: int | None,
                    rosters: dict[int, Roster],
                    allow_duplicate_comments: bool) -> tuple[GradePlan | None, list[str]]:
    """Resolve a parsed grade file against Canvas. Reads only; posts nothing."""
    errors: list[str] = []
    where = gf.path.name

    def err(msg: str, entry: GradeEntry | None = None) -> None:
        errors.append(f"{where}:{entry.line}: {msg}" if entry else f"{where}: {msg}")

    # Course: from --course, else from the section.
    if course_id is None:
        if gf.section_id is None:
            err("no [SECTION] id to find the course from; pass --course")
            return None, errors
        try:
            course_id = canvas.section(gf.section_id)["course_id"]
        except requests.HTTPError as exc:
            err(f"could not look up section {gf.section_id}: {exc}")
            return None, errors

    if course_id not in rosters:
        rosters[course_id] = Roster(canvas.sections(course_id),
                                    canvas.student_enrollments(course_id))
    roster = rosters[course_id]
    notes: list[str] = []

    section = None
    if gf.section_id is not None:
        section = roster.section_by_id.get(gf.section_id)
        if section is None:
            err(f"section {gf.section_id} is not in course {course_id}")
        elif gf.section_title and \
                gf.section_title.casefold() not in (section.get("name") or "").casefold():
            notes.append(f"file says section {gf.section_title!r}, "
                         f"Canvas calls it {section.get('name')!r}")

    try:
        assignment = canvas.assignment(course_id, gf.assignment_id)
    except requests.HTTPError as exc:
        err(f"assignment {gf.assignment_id} not found in course {course_id} ({exc})")
        return None, errors

    if gf.assignment_title and \
            gf.assignment_title.casefold() not in (assignment.get("name") or "").casefold():
        notes.append(f"file says assignment {gf.assignment_title!r}, "
                     f"Canvas calls it {assignment.get('name')!r}")
    if assignment.get("published") is False:
        err("the assignment is unpublished; Canvas will not accept grades for it")
    if assignment.get("post_manually"):
        notes.append("grades are posted manually for this assignment: students "
                     "will not see these grades or comments until you post them")
    if assignment.get("moderated_grading"):
        notes.append("moderated assignment: grades are saved as provisional grades")
    if assignment.get("anonymous_grading"):
        notes.append("anonymous grading is on for this assignment")
    if gf.blank_entries:
        notes.append(f"{gf.blank_entries} named student(s) have no grade or comment; skipped")

    existing = {s.get("user_id"): s
                for s in canvas.submissions_with_comments(course_id, gf.assignment_id)}

    items: list[PlannedGrade] = []
    seen: dict[int, int] = {}
    for entry in gf.entries:
        try:
            user = resolve_grade_entry(roster, entry, gf.section_id)
        except LookupError as exc:
            err(str(exc), entry)
            continue
        uid = user["id"]
        if uid in seen:
            err(f"{user.get('sortable_name')} is listed twice (also line {seen[uid]})", entry)
            continue
        seen[uid] = entry.line

        try:
            fields, warnings = grade_fields(entry, assignment)
        except ValueError as exc:
            err(str(exc), entry)
            continue

        sub = existing.get(uid)
        if sub is None:
            err(f"{user.get('sortable_name')} has no submission record for this "
                "assignment (not assigned to them?)", entry)
            continue

        if gf.section_id and section and \
                gf.section_id not in roster.sections_of_user.get(uid, []):
            warnings.append(f"not enrolled in section {section.get('name')}")

        skipped = False
        if "text_comment" in fields and not allow_duplicate_comments:
            posted = {_norm_comment(c.get("comment"))
                      for c in sub.get("submission_comments") or []}
            if _norm_comment(fields["text_comment"]) in posted:
                del fields["text_comment"]
                skipped = True

        before = _grade_before(sub)
        if before and "posted_grade" in fields and \
                before.casefold() != fields["posted_grade"].casefold():
            warnings.append(f"replaces existing grade {before}")

        items.append(PlannedGrade(entry=entry, user_id=uid,
                                  student=user.get("sortable_name") or user.get("name") or "",
                                  fields=fields, grade_before=before,
                                  comment_skipped=skipped, warnings=warnings))

    return GradePlan(source=gf, course_id=course_id, assignment=assignment,
                     section=section, items=items, notes=notes), errors


def _preview(text: str, width: int = 60) -> str:
    one_line = " ".join(text.split())
    return repr(one_line if len(one_line) <= width else one_line[:width - 1] + "…")


def print_grade_plan(plan: GradePlan) -> None:
    a, gf = plan.assignment, plan.source
    scale = a.get("grading_type") or ""
    if scale == "points" and a.get("points_possible") is not None:
        scale = f"points, out of {a['points_possible']:g}"
    print(f"\n{gf.path.name}  (course {plan.course_id})")
    print(f"  Assignment {a['id']}  {a.get('name', '')}  ({scale})")
    if plan.section:
        inst = f"  instructor {gf.instructor}" if gf.instructor else ""
        print(f"  Section    {plan.section['id']}  {plan.section.get('name', '')}{inst}")
    for note in plan.notes:
        print(f"  note: {note}")
    for it in plan.items:
        parts = []
        if "excuse" in it.fields:
            parts.append(f"grade {it.grade_before or '-'} -> EXCUSED")
        elif "posted_grade" in it.fields:
            parts.append(f"grade {it.grade_before or '-'} -> {it.fields['posted_grade']}")
        if "text_comment" in it.fields:
            parts.append(f"comment {_preview(it.fields['text_comment'])}")
        elif it.comment_skipped:
            parts.append("comment already on Canvas, not re-sent")
        if not it.fields:
            parts.append("(nothing to send)")
        print(f"    {it.student} ({it.user_id}):  " + "   ".join(parts))
        for w in it.warnings:
            print(f"      ! {w}")
    print(f"  {len(plan.to_send)} student(s) to update")


def verify_posted(it: PlannedGrade, sub: dict | None, gtype: str) -> list[str]:
    """Compare what Canvas now holds against what was sent."""
    if sub is None:
        return ["submission not found after posting"]
    problems = []
    f = it.fields
    if "excuse" in f and not sub.get("excused"):
        problems.append("not marked excused")
    if "posted_grade" in f:
        if sub.get("entered_grade") is None and sub.get("grade") is None:
            problems.append("no grade recorded")
        elif gtype == "points" and not f["posted_grade"].endswith("%"):
            # entered_score is before any late penalty; score is after it.
            got = sub.get("entered_score", sub.get("score"))
            if got is None or abs(float(got) - float(f["posted_grade"])) > 1e-6:
                problems.append(f"score is {got}, expected {f['posted_grade']}")
    if "text_comment" in f:
        posted = {_norm_comment(c.get("comment"))
                  for c in sub.get("submission_comments") or []}
        if _norm_comment(f["text_comment"]) not in posted:
            problems.append("comment not found")
    return problems


def post_grade_plan(canvas: Canvas, plan: GradePlan) -> list[dict]:
    """One bulk update_grades call for the file, then a read-back check."""
    a = plan.assignment
    to_send = plan.to_send
    print(f"\nPosting {len(to_send)} update(s) for {a.get('name')} "
          f"({plan.source.path.name})...")
    job_state, message = "", ""
    try:
        progress = canvas.bulk_update_grades(
            plan.course_id, a["id"], {it.user_id: it.fields for it in to_send})
        progress = canvas.wait_for_progress(progress)
        job_state = progress.get("workflow_state") or ""
        message = progress.get("message") or ""
    except requests.HTTPError as exc:
        job_state, message = "request failed", str(exc)

    if job_state == "completed":
        print("  Canvas job completed.")
    else:
        print(f"  ! Canvas job {job_state or 'did not finish'}"
              + (f": {message}" if message else "")
              + ". Checking what was saved anyway.")

    after = {s.get("user_id"): s
             for s in canvas.submissions_with_comments(plan.course_id, a["id"])}
    rows = []
    bad = 0
    for it in plan.items:
        sub = after.get(it.user_id)
        problems = verify_posted(it, sub, a.get("grading_type") or "points") \
            if it.fields else []
        if problems:
            bad += 1
            print(f"  ! {it.student} ({it.user_id}): " + "; ".join(problems))
        rows.append({
            "file": plan.source.path.name,
            "course_id": plan.course_id,
            "assignment_id": a["id"],
            "assignment": a.get("name", ""),
            "section": (plan.section or {}).get("name", ""),
            "user_id": it.user_id,
            "student": it.student,
            "grade_before": it.grade_before,
            "grade_sent": "EXCUSED" if "excuse" in it.fields
                          else it.fields.get("posted_grade", ""),
            "comment_sent": it.fields.get("text_comment", ""),
            "comment_skipped_duplicate": "yes" if it.comment_skipped else "",
            "job_state": job_state,
            "canvas_grade_after": _grade_before(sub),
            "canvas_score_after": (sub or {}).get("score", ""),
            "problems": "; ".join(problems),
        })
    if not bad:
        print(f"  Verified: all {len(to_send)} update(s) are on Canvas.")
    return rows


def post_grades(canvas: Canvas, args, run_started: datetime) -> int:
    """--post-grades: parse and check every file, show the plan, then post."""
    plans: list[GradePlan] = []
    errors: list[str] = []
    rosters: dict[int, Roster] = {}

    for name in args.post_grades:
        path = Path(name)
        try:
            gf = parse_grade_file(path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        except GradeFileError as exc:
            errors.append(str(exc))
            continue
        plan, errs = plan_grade_file(canvas, gf, args.course, rosters,
                                     args.allow_duplicate_comments)
        errors += errs
        if plan:
            plans.append(plan)

    for plan in plans:
        print_grade_plan(plan)

    if errors:
        print("\nErrors (nothing was posted):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    total = sum(len(p.to_send) for p in plans)
    if not total:
        print("\nNothing to post.")
        return 0
    if args.dry_run:
        print(f"\nDry run: {total} update(s) checked, nothing posted.")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("\nNot posting without confirmation; rerun with --yes.",
                  file=sys.stderr)
            return 1
        answer = input(f"\nPost {total} grade/comment update(s) to Canvas? [y/N] ")
        if answer.strip().casefold() not in ("y", "yes"):
            print("Cancelled; nothing posted.")
            return 0

    rows: list[dict] = []
    for plan in plans:
        if plan.to_send:
            rows += post_grade_plan(canvas, plan)

    log_dir = Path(args.log_dir) if args.log_dir else Path(args.post_grades[0]).parent
    log_path = log_dir / run_started.strftime("grade_post_log_%Y%m%d_%H%M%S.csv")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nLog: {log_path}")
    except OSError as exc:
        print(f"\nCould not write log {log_path}: {exc}", file=sys.stderr)

    failed = sum(1 for r in rows if r["problems"])
    if failed:
        print(f"{failed} update(s) could not be verified; see the log.", file=sys.stderr)
        return 1
    return 0
