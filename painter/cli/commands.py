"""One function per command: check the options, build the request, call the
service with the console reporter, and return the exit status."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys

from painter.canvas.client import Canvas, check_base_url
from painter.cli import exit_codes
from painter.cli.console import ConsoleReporter, grade_plan_lines, organize_plan_lines
from painter.config import LEGACY_BROWSER_PROFILE, TOKEN_ENV, default_browser_profile
from painter.domain.duedates import parse_tz
from painter.domain.roster import Roster
from painter.domain.selection import Selection
from painter.events import emit
from painter.services.grade_files import GradeFilesRequest, make_grade_files
from painter.services.grading import plan_grades, post_grade_plans
from painter.services.organize import OrganizeRequest, execute_organize, plan_organize
from painter.services.quiz_export import QuizExportRequest, export_quiz
from painter.services.quiz_uploads import BrowserUploadsRequest, browser_quiz_uploads
from painter.services.roster_export import RosterExportRequest, export_roster_csv
from painter.services.submissions import (
    DownloadRequest, download_submissions, section_listing, student_listing,
)

CONSOLE = ConsoleReporter()


def selection_from(args) -> Selection:
    return Selection.of(getattr(args, "section", None), getattr(args, "student", None),
                        getattr(args, "exclude", None))


def select_students(roster: Roster, args) -> tuple[set[int] | None, set[int]]:
    """The old (roster, args) call. New code uses selection_from(args).resolve(roster)."""
    res = selection_from(args).resolve(roster)
    emit(res.notes, CONSOLE)
    return res.student_ids, res.section_ids


def connect(args, parser, need_course: bool = True) -> Canvas:
    """The Canvas client for a command, after checking --base-url, --course
    and the token. A missing option is a usage error (status 2); a missing
    token is local setup (status 5)."""
    if not args.base_url:
        parser.error("--base-url is required")
    try:
        args.base_url = check_base_url(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))
    if need_course and args.course is None:
        parser.error("--course is required")
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"Set the {TOKEN_ENV} environment variable first.", file=sys.stderr)
        raise SystemExit(exit_codes.SETUP)
    return Canvas(args.base_url, token)


# ---- list --------------------------------------------------------------------------
def list_assignments(args, parser) -> int:
    canvas = connect(args, parser)
    for a in canvas.assignments(args.course):
        print(f"{a['id']:>10}  {a['name']}")
    return exit_codes.OK


def list_sections(args, parser) -> int:
    canvas = connect(args, parser)
    for s in section_listing(Roster.load(canvas, args.course)):
        sis = s["sis_section_id"] or "-"
        print(f"{s['id']:>10}  {sis:<16}  {s['students']:>4} students  {s['name']}")
    return exit_codes.OK


def list_students(args, parser) -> int:
    canvas = connect(args, parser)
    roster = Roster.load(canvas, args.course)
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
    return exit_codes.OK


# ---- download, roster, organize ----------------------------------------------------
def download(args, parser) -> int:
    canvas = connect(args, parser)
    parse_tz(args.tz)                       # an unknown zone fails before any request
    req = DownloadRequest(
        course_id=args.course, out_root=Path(args.out),
        assignment_ids=tuple(args.assignment or ()), selection=selection_from(args),
        by_section=args.by_section, flat=args.flat, extract=not args.no_extract,
        history=args.history, tz=args.tz, excel_log=not args.no_xlsx,
        log_dir=Path(args.log_dir) if args.log_dir else None,
        run_started=datetime.now())
    with CONSOLE.stoppable():
        result = download_submissions(canvas, req, CONSOLE)
    return exit_codes.PROBLEMS if result.failures else exit_codes.OK


def roster(args, parser) -> int:
    canvas = connect(args, parser)
    req = RosterExportRequest(
        course_id=args.course, path=Path(args.file), selection=selection_from(args),
        assignment_ids=tuple(args.assignment or ()))
    with CONSOLE.stoppable():
        export_roster_csv(canvas, req, CONSOLE)
    return exit_codes.OK


def organize(args, parser) -> int:
    """Show the plan; carry it out unless --dry-run. No Canvas access."""
    plan = plan_organize(OrganizeRequest(
        src=Path(args.folder), roster_csv=Path(args.roster),
        section_specs=tuple(args.section or ()),
        dest=Path(args.to) if args.to else None))
    out, err = organize_plan_lines(plan, args.dry_run)
    for line in out:
        print(line)
    for line in err:
        print(line, file=sys.stderr)
    if not args.dry_run:
        with CONSOLE.stoppable():
            execute_organize(plan, CONSOLE)
    return exit_codes.OK


# ---- grades ------------------------------------------------------------------------
def grades_new(args, parser) -> int:
    canvas = connect(args, parser)
    req = GradeFilesRequest(
        course_id=args.course, out_dir=Path(args.dir),
        section_specs=tuple(args.section or ()),
        assignment_ids=(args.assignment,) if args.assignment else (),
        label=args.label, ay=args.ay, term=args.term, force=args.force)
    with CONSOLE.stoppable():
        make_grade_files(canvas, req, CONSOLE)
    return exit_codes.OK


def grades_post(args, parser) -> int:
    """Check every file, show the plan, confirm, then post. Confirming is the
    front end's job: the service only plans and posts."""
    canvas = connect(args, parser, need_course=False)
    run_started = datetime.now()
    with CONSOLE.stoppable():
        plans = plan_grades(canvas, [Path(n) for n in args.files], args.course,
                            args.allow_duplicate_comments)
    for plan in plans.plans:
        for line in grade_plan_lines(plan):
            print(line)

    if plans.errors:
        print("\nErrors (nothing was posted):", file=sys.stderr)
        for e in plans.errors:
            print(f"  {e}", file=sys.stderr)
        return exit_codes.BAD_INPUT

    total = plans.total
    if not total:
        print("\nNothing to post.")
        return exit_codes.OK
    if args.dry_run:
        print(f"\nDry run: {total} update(s) checked, nothing posted.")
        return exit_codes.OK
    if not args.yes:
        if not sys.stdin.isatty():
            print("\nNot posting without confirmation; rerun with --yes.",
                  file=sys.stderr)
            return exit_codes.BAD_INPUT
        answer = input(f"\nPost {total} grade/comment update(s) to Canvas? [y/N] ")
        if answer.strip().casefold() not in ("y", "yes"):
            print("Cancelled; nothing posted.")
            return exit_codes.OK

    log_dir = Path(args.log_dir) if args.log_dir else Path(args.files[0]).parent
    with CONSOLE.stoppable():         # stops only between grade files, never mid-post
        result = post_grade_plans(canvas, plans, log_dir, run_started, CONSOLE)
    return exit_codes.PROBLEMS if result.failed else exit_codes.OK


# ---- quiz --------------------------------------------------------------------------
def quiz_export(args, parser) -> int:
    """Exit status from QuizExportResult.outcome (see exit_codes.QUIZ_EXPORT)."""
    if args.uploads and args.no_answers:
        parser.error("--uploads needs the answers report, so not --no-answers")
    canvas = connect(args, parser)
    req = QuizExportRequest(
        course_id=args.course, assignment_ids=(args.assignment,),
        out_root=Path(args.out), selection=selection_from(args),
        by_section=args.by_section, answers=not args.no_answers,
        uploads=args.uploads, course_export=not args.no_course_export,
        timeout=args.timeout, dry_run=args.dry_run)
    with CONSOLE.stoppable():
        result = export_quiz(canvas, req, CONSOLE)
    return exit_codes.QUIZ_EXPORT[result.outcome]


def quiz_uploads(args, parser) -> int:
    """Exit status from BrowserUploadsResult.outcome (see exit_codes.QUIZ_UPLOADS)."""
    canvas = connect(args, parser)
    if args.profile is None:
        args.profile = str(default_browser_profile())
        if Path(LEGACY_BROWSER_PROFILE).is_dir():
            print(f"note: ./{LEGACY_BROWSER_PROFILE} (the old default) is no longer "
                  f"used; the profile now lives in {args.profile}. It holds "
                  "a signed-in Canvas session: delete it, or move it there to stay "
                  "signed in, especially if this folder is synced to OneDrive.",
                  file=sys.stderr)
    req = BrowserUploadsRequest(
        course_id=args.course, assignment_ids=(args.assignment,),
        out_root=Path(args.out), selection=selection_from(args),
        by_section=args.by_section, limit=args.limit, dry_run=args.dry_run,
        profile=Path(args.profile), channel=args.channel,
        connect_url=args.connect, signin_timeout=args.signin_timeout,
        headless=args.headless, page_timeout=args.page_timeout, delay=args.delay)
    with CONSOLE.stoppable():
        result = browser_quiz_uploads(canvas, req, CONSOLE)
    return exit_codes.QUIZ_UPLOADS[result.outcome]
