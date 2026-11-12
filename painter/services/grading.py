"""Posting grades and comments: plan, post, verify."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re

import requests

from painter.canvas.client import Canvas
from painter.errors import Cancelled, InvalidInput, NotFound
from painter.events import NULL, Reporter
from painter.domain.matching import StudentMatcher, same_words
from painter.domain.roster import Roster
from painter.services.grade_files import (
    GradeEntry, GradeFile, GradeFileError, parse_grade_file,
)
from painter.storage.tabular import write_csv


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

    students = StudentMatcher(roster.users.values())
    if entry.id:
        hits = students.by_id(entry.id)
        if not hits:
            raise LookupError(f"no student in the course has id {entry.id}")
        if len(hits) > 1:
            raise LookupError(f"id {entry.id} matches several students: "
                              + ", ".join(label(u) for u in hits))
        user = hits[0]
        if entry.name and not same_words(entry.name, user):
            raise LookupError(f"id {entry.id} is {label(user)}, not {entry.name!r}")
        return user

    hits = students.by_words(entry.name)
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


def _same_grade(a: str, b: str) -> bool:
    """Do two grades mean the same thing? 9 and 9.0, or 90% and 90.00%,
    compare as numbers; letter grades and EXCUSED compare as text, ignoring
    case (review finding 17)."""
    a, b = (a or "").strip(), (b or "").strip()
    if a.endswith("%") == b.endswith("%"):
        try:
            return float(a.rstrip("%")) == float(b.rstrip("%"))
        except ValueError:
            pass
    return a.casefold() == b.casefold()


def _grade_before(sub: dict | None) -> str:
    if not sub:
        return ""
    if sub.get("excused"):
        return "EXCUSED"
    return str(sub.get("entered_grade") or sub.get("grade") or "")


class _Errors(list):
    """Problems in one grade file, as '<file>:<line>: message'."""

    def __init__(self, where: str):
        super().__init__()
        self.where = where

    def __call__(self, msg: str, entry: GradeEntry | None = None) -> None:
        self.append(f"{self.where}:{entry.line}: {msg}" if entry else f"{self.where}: {msg}")


def plan_grade_file(canvas: Canvas, gf: GradeFile, course_id: int | None,
                    rosters: dict[int, Roster],
                    allow_duplicate_comments: bool) -> tuple[GradePlan | None, list[str]]:
    """Resolve a parsed grade file against Canvas. Reads only; posts nothing."""
    err = _Errors(gf.path.name)
    course_id = _grade_file_course(canvas, gf, course_id, err)
    if course_id is None:
        return None, err

    if course_id not in rosters:
        rosters[course_id] = Roster.load(canvas, course_id)     # once per course
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
    except NotFound as exc:
        err(f"assignment {gf.assignment_id} not found in course {course_id} ({exc})")
        return None, err
    _check_assignment(gf, assignment, err, notes)

    existing = {s.get("user_id"): s
                for s in canvas.submissions_with_comments(course_id, gf.assignment_id)}
    items: list[PlannedGrade] = []
    seen: dict[int, int] = {}
    for entry in gf.entries:
        item = _plan_entry(entry, gf, roster, section, assignment, existing, seen,
                           allow_duplicate_comments, err)
        if item is not None:
            items.append(item)

    return GradePlan(source=gf, course_id=course_id, assignment=assignment,
                     section=section, items=items, notes=notes), err


def _grade_file_course(canvas: Canvas, gf: GradeFile, course_id: int | None,
                       err: _Errors) -> int | None:
    """The course: --course if given, else the one the file's section is in."""
    if course_id is not None:
        return course_id
    if gf.section_id is None:
        err("no [SECTION] id to find the course from; pass --course")
        return None
    try:
        return canvas.section(gf.section_id)["course_id"]
    except NotFound as exc:
        err(f"section {gf.section_id} not found ({exc})")
        return None


def _check_assignment(gf: GradeFile, assignment: dict, err: _Errors,
                      notes: list[str]) -> None:
    """Assignment settings that block posting (errors) or that the user
    should know about before posting (notes)."""
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


def _plan_entry(entry: GradeEntry, gf: GradeFile, roster: Roster, section: dict | None,
                assignment: dict, existing: dict, seen: dict[int, int],
                allow_duplicate_comments: bool, err: _Errors) -> PlannedGrade | None:
    """One [STUDENT] block: who it is, what to send, what to warn about.
    None (with an error recorded) if it cannot be posted."""
    try:
        user = resolve_grade_entry(roster, entry, gf.section_id)
    except LookupError as exc:
        err(str(exc), entry)
        return None
    uid = user["id"]
    if uid in seen:
        err(f"{user.get('sortable_name')} is listed twice (also line {seen[uid]})", entry)
        return None
    seen[uid] = entry.line

    try:
        fields, warnings = grade_fields(entry, assignment)
    except ValueError as exc:
        err(str(exc), entry)
        return None

    sub = existing.get(uid)
    if sub is None:
        err(f"{user.get('sortable_name')} has no submission record for this "
            "assignment (not assigned to them?)", entry)
        return None

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
            not _same_grade(before, fields["posted_grade"]):
        warnings.append(f"replaces existing grade {before}")

    return PlannedGrade(entry=entry, user_id=uid,
                        student=user.get("sortable_name") or user.get("name") or "",
                        fields=fields, grade_before=before,
                        comment_skipped=skipped, warnings=warnings)


def _preview(text: str, width: int = 60) -> str:
    one_line = " ".join(text.split())
    return repr(one_line if len(one_line) <= width else one_line[:width - 1] + "…")


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


def post_grade_plan(canvas: Canvas, plan: GradePlan,
                    reporter: Reporter = NULL) -> list[dict]:
    """One bulk update_grades call for the file, then a read-back check."""
    a = plan.assignment
    to_send = plan.to_send
    reporter.info(f"\nPosting {len(to_send)} update(s) for {a.get('name')} "
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
        reporter.info("  Canvas job completed.")
    else:
        reporter.info(f"  ! Canvas job {job_state or 'did not finish'}"
                      + (f": {message}" if message else "")
                      + ". Checking what was saved anyway.")

    after = {s.get("user_id"): s
             for s in canvas.submissions_with_comments(plan.course_id, a["id"])}
    rows = []
    bad = 0
    for n, it in enumerate(plan.items, start=1):
        reporter.progress(n, len(plan.items), it.student)
        sub = after.get(it.user_id)
        problems = verify_posted(it, sub, a.get("grading_type") or "points") \
            if it.fields else []
        if problems:
            bad += 1
            reporter.info(f"  ! {it.student} ({it.user_id}): " + "; ".join(problems))
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
        reporter.info(f"  Verified: all {len(to_send)} update(s) are on Canvas.")
    return rows


@dataclass
class GradePlanSet:
    """Every grade file checked against Canvas. Nothing has been posted."""
    plans: list[GradePlan]
    errors: list[str]                 # any error means nothing may be posted

    @property
    def total(self) -> int:
        return sum(len(p.to_send) for p in self.plans)


def plan_grades(canvas: Canvas, paths: list[Path], course_id: int | None = None,
                allow_duplicate_comments: bool = False) -> GradePlanSet:
    """Parse and check every grade file. Reads only; posts nothing.

    A front end shows the plans (and errors), asks for confirmation, and
    then calls post_grade_plans(). course_id None means each file's section
    says which course it is in.
    """
    plans: list[GradePlan] = []
    errors: list[str] = []
    rosters: dict[int, Roster] = {}
    for path in paths:
        path = Path(path)
        try:
            gf = parse_grade_file(path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        except GradeFileError as exc:
            errors.append(str(exc))
            continue
        plan, errs = plan_grade_file(canvas, gf, course_id, rosters,
                                     allow_duplicate_comments)
        errors += errs
        if plan:
            plans.append(plan)
    return GradePlanSet(plans, errors)


@dataclass
class PostResult:
    rows: list[dict]                  # one per student, also written to the log
    log_path: Path | None             # None if the log could not be written
    failed: int                       # updates Canvas does not show afterwards


def post_grade_plans(canvas: Canvas, plans: GradePlanSet, log_dir: Path,
                     run_started: datetime, reporter: Reporter = NULL) -> PostResult:
    """Post every plan, verify each against Canvas, write the CSV log.

    Refuses a plan set that has errors: the caller must not get this far.
    """
    if plans.errors:
        raise InvalidInput("grade files have errors; nothing was posted")
    rows: list[dict] = []
    stopped_before = None
    for plan in plans.plans:
        if reporter.cancelled():
            stopped_before = plan.source.path.name
            break
        if plan.to_send:
            rows += post_grade_plan(canvas, plan, reporter)

    # The log is written whenever anything was posted, including when the
    # caller cancelled part-way: it is the record of what changed on Canvas.
    log_path = _write_post_log(rows, Path(log_dir), run_started, reporter) if rows else None

    failed = sum(1 for r in rows if r["problems"])
    if failed:
        reporter.warning(f"{failed} update(s) could not be verified; see the log.")
    result = PostResult(rows, log_path, failed)
    if stopped_before is not None:
        raise Cancelled(f"stopped before posting {stopped_before}; "
                        f"{len(rows)} student row(s) posted earlier are in the log",
                        result)
    return result


def _write_post_log(rows: list[dict], log_dir: Path, run_started: datetime,
                    reporter: Reporter) -> Path | None:
    log_path = log_dir / run_started.strftime("grade_post_log_%Y%m%d_%H%M%S.csv")
    try:
        write_csv(log_path, list(rows[0].keys()), rows)
        reporter.info(f"\nLog: {log_path}")
        return log_path
    except OSError as exc:
        reporter.warning(f"\nCould not write log {log_path}: {exc}")
        return None
