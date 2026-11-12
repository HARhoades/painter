"""One function per mode: turn the parsed flags into a request, call the
service with the console reporter, and return the exit code.

These keep the old (canvas, args) signatures, so the old script name can
keep exporting them under their old names.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

from painter.canvas.client import Canvas
from painter.cli.console import ConsoleReporter, grade_plan_lines, organize_plan_lines
from painter.domain.duedates import parse_tz
from painter.domain.roster import Roster
from painter.domain.selection import Selection
from painter.events import emit
from painter.services.grade_files import GradeFilesRequest, make_grade_files
from painter.services.grading import plan_grades, post_grade_plans
from painter.services.organize import OrganizeRequest, execute_organize, plan_organize
from painter.services.quiz_export import QuizExportRequest, export_quiz as run_quiz_export
from painter.services.quiz_uploads import BrowserUploadsRequest, browser_quiz_uploads
from painter.services.roster_export import RosterExportRequest, export_roster_csv
from painter.services.submissions import (
    DownloadRequest, download_submissions, section_listing, student_listing,
)

CONSOLE = ConsoleReporter()


def selection_from(args) -> Selection:
    return Selection.of(getattr(args, "section", None), getattr(args, "student", None))


def select_students(roster: Roster, args) -> tuple[set[int] | None, set[int]]:
    """The old (roster, args) call, kept for the old script's imports.
    New code uses selection_from(args).resolve(roster)."""
    res = selection_from(args).resolve(roster)
    emit(res.notes, CONSOLE)
    return res.student_ids, res.section_ids


def roster_csv(canvas: Canvas, args) -> int:
    """--roster-csv"""
    export_roster_csv(canvas, RosterExportRequest(
        course_id=args.course, path=Path(args.roster_csv),
        selection=selection_from(args),
        assignment_ids=tuple(args.assignment or ())), CONSOLE)
    return 0


def grade_files(canvas: Canvas, args) -> int:
    """--make-grade-files"""
    make_grade_files(canvas, GradeFilesRequest(
        course_id=args.course, out_dir=Path(args.grade_file_dir),
        section_specs=tuple(args.section or ()),
        assignment_ids=tuple(args.assignment or ()), label=args.assignment_label,
        ay=args.ay, term=args.term, force=args.force), CONSOLE)
    return 0


def post_grades(canvas: Canvas, args, run_started: datetime) -> int:
    """--post-grades: check every file, show the plan, confirm, then post.

    Confirmation is the front end's job: the service only plans and posts.
    """
    plans = plan_grades(canvas, [Path(n) for n in args.post_grades], args.course,
                        args.allow_duplicate_comments)
    for plan in plans.plans:
        for line in grade_plan_lines(plan):
            print(line)

    if plans.errors:
        print("\nErrors (nothing was posted):", file=sys.stderr)
        for e in plans.errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    total = plans.total
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

    log_dir = Path(args.log_dir) if args.log_dir else Path(args.post_grades[0]).parent
    result = post_grade_plans(canvas, plans, log_dir, run_started, CONSOLE)
    return 1 if result.failed else 0


def organize(args) -> int:
    """--organize: show the plan; carry it out unless --dry-run."""
    plan = plan_organize(OrganizeRequest(
        src=Path(args.organize), roster_csv=Path(args.roster),
        section_specs=tuple(args.section or ()),
        dest=Path(args.organize_to) if args.organize_to else None))
    out, err = organize_plan_lines(plan, args.dry_run)
    for line in out:
        print(line)
    for line in err:
        print(line, file=sys.stderr)
    if not args.dry_run:
        execute_organize(plan, CONSOLE)
    return 0


def download(canvas: Canvas, args, run_started: datetime) -> int:
    """The default mode: --list-*, or download submission files."""
    parse_tz(args.tz)                       # an unknown zone fails before any request
    if args.list_sections or args.list_students:
        roster = Roster.load(canvas, args.course)
        if args.list_sections:
            for s in section_listing(roster):
                sis = s["sis_section_id"] or "-"
                print(f"{s['id']:>10}  {sis:<16}  {s['students']:>4} students  {s['name']}")
            return 0
        listing = student_listing(canvas, args.course, roster, selection_from(args),
                                  tuple(args.assignment or ()))
        emit(listing.notes, CONSOLE)
        for u in listing.users:
            sis = u.get("sis_user_id") or u.get("login_id") or "-"
            secs = "; ".join(roster.section_names(u["id"])) or "-"
            print(f"{u['id']:>10}  {sis:<16}  {u.get('sortable_name', ''):<32}  {secs}")
        print(f"{len(listing.users)} student(s)"
              + (f" of {listing.in_course} in the course" if listing.filtered else ""),
              file=sys.stderr)
        return 0
    if args.list_assignments:
        if args.student or args.section or args.by_section:
            Roster.load(canvas, args.course)  # kept: same requests as before
        for a in canvas.assignments(args.course):
            print(f"{a['id']:>10}  {a['name']}")
        return 0

    result = download_submissions(canvas, DownloadRequest(
        course_id=args.course, out_root=Path(args.out),
        assignment_ids=tuple(args.assignment or ()), selection=selection_from(args),
        by_section=args.by_section, flat=args.flat, extract=not args.no_extract,
        history=args.history, tz=args.tz, excel_log=not args.no_xlsx,
        log_dir=Path(args.log_dir) if args.log_dir else None,
        run_started=run_started), CONSOLE)
    # 1 = finished, but some files are missing (same meaning as --post-grades).
    return 1 if result.failures else 0


def export_quiz(canvas: Canvas, args) -> int:
    """--export-quiz; exit code = QuizExportResult.outcome (0-3)."""
    return run_quiz_export(canvas, QuizExportRequest(
        course_id=args.course, assignment_ids=tuple(args.assignment or ()),
        out_root=Path(args.out), selection=selection_from(args),
        by_section=args.by_section, answers=not args.no_answers,
        uploads=args.quiz_uploads, course_export=not args.no_course_export,
        timeout=args.export_timeout, dry_run=args.dry_run), CONSOLE).outcome


def browser_uploads(canvas: Canvas, args) -> int:
    """--browser-uploads; exit code = BrowserUploadsResult.outcome (0, 1, 3)."""
    return browser_quiz_uploads(canvas, BrowserUploadsRequest(
        course_id=args.course, assignment_ids=tuple(args.assignment or ()),
        out_root=Path(args.out), selection=selection_from(args),
        by_section=args.by_section, limit=args.limit, dry_run=args.dry_run,
        profile=Path(args.browser_profile), channel=args.browser_channel,
        connect_url=args.connect_browser, signin_timeout=args.signin_timeout,
        headless=args.headless, page_timeout=args.page_timeout,
        delay=args.delay), CONSOLE).outcome
