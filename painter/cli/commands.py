"""One function per command: check the options, build the request, call the
service with the console reporter, and return the exit code."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys

from painter.canvas.client import Canvas, check_base_url
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
    return Selection.of(getattr(args, "section", None), getattr(args, "student", None))


def select_students(roster: Roster, args) -> tuple[set[int] | None, set[int]]:
    """The old (roster, args) call, kept for the old script's imports.
    New code uses selection_from(args).resolve(roster)."""
    res = selection_from(args).resolve(roster)
    emit(res.notes, CONSOLE)
    return res.student_ids, res.section_ids


def connect(args, parser, need_course: bool = True) -> Canvas:
    """The Canvas client for a command, after checking --base-url, --course
    and the token. Exits like any usage error (status 2) if one is missing,
    or with status 1 if the token is not set."""
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
        raise SystemExit(1)
    return Canvas(args.base_url, token)


# ---- list --------------------------------------------------------------------------
def list_assignments(args, parser) -> int:
    canvas = connect(args, parser)
    for a in canvas.assignments(args.course):
        print(f"{a['id']:>10}  {a['name']}")
    return 0


def list_sections(args, parser) -> int:
    canvas = connect(args, parser)
    for s in section_listing(Roster.load(canvas, args.course)):
        sis = s["sis_section_id"] or "-"
        print(f"{s['id']:>10}  {sis:<16}  {s['students']:>4} students  {s['name']}")
    return 0


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
    return 0


# ---- download, roster, organize ----------------------------------------------------
def download(args, parser) -> int:
    canvas = connect(args, parser)
    parse_tz(args.tz)                       # an unknown zone fails before any request
    result = download_submissions(canvas, DownloadRequest(
        course_id=args.course, out_root=Path(args.out),
        assignment_ids=tuple(args.assignment or ()), selection=selection_from(args),
        by_section=args.by_section, flat=args.flat, extract=not args.no_extract,
        history=args.history, tz=args.tz, excel_log=not args.no_xlsx,
        log_dir=Path(args.log_dir) if args.log_dir else None,
        run_started=datetime.now()), CONSOLE)
    # 1 = finished, but some files are missing (same meaning as grades post).
    return 1 if result.failures else 0


def roster(args, parser) -> int:
    canvas = connect(args, parser)
    export_roster_csv(canvas, RosterExportRequest(
        course_id=args.course, path=Path(args.file), selection=selection_from(args),
        assignment_ids=tuple(args.assignment or ())), CONSOLE)
    return 0


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
        execute_organize(plan, CONSOLE)
    return 0


# ---- grades ------------------------------------------------------------------------
def grades_new(args, parser) -> int:
    canvas = connect(args, parser)
    make_grade_files(canvas, GradeFilesRequest(
        course_id=args.course, out_dir=Path(args.dir),
        section_specs=tuple(args.section or ()),
        assignment_ids=(args.assignment,) if args.assignment else (),
        label=args.label, ay=args.ay, term=args.term, force=args.force), CONSOLE)
    return 0


def grades_post(args, parser) -> int:
    """Check every file, show the plan, confirm, then post. Confirming is the
    front end's job: the service only plans and posts."""
    canvas = connect(args, parser, need_course=False)
    run_started = datetime.now()
    plans = plan_grades(canvas, [Path(n) for n in args.files], args.course,
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

    log_dir = Path(args.log_dir) if args.log_dir else Path(args.files[0]).parent
    result = post_grade_plans(canvas, plans, log_dir, run_started, CONSOLE)
    return 1 if result.failed else 0


# ---- quiz --------------------------------------------------------------------------
def quiz_export(args, parser) -> int:
    """Exit code = QuizExportResult.outcome (0-3)."""
    if args.uploads and args.no_answers:
        parser.error("--uploads needs the answers report, so not --no-answers")
    canvas = connect(args, parser)
    return export_quiz(canvas, QuizExportRequest(
        course_id=args.course, assignment_ids=(args.assignment,),
        out_root=Path(args.out), selection=selection_from(args),
        by_section=args.by_section, answers=not args.no_answers,
        uploads=args.uploads, course_export=not args.no_course_export,
        timeout=args.timeout, dry_run=args.dry_run), CONSOLE).outcome


def quiz_uploads(args, parser) -> int:
    """Exit code = BrowserUploadsResult.outcome (0, 1, 3)."""
    canvas = connect(args, parser)
    if args.profile is None:
        args.profile = str(default_browser_profile())
        if Path(LEGACY_BROWSER_PROFILE).is_dir():
            print(f"note: ./{LEGACY_BROWSER_PROFILE} (the old default) is no longer "
                  f"used; the profile now lives in {args.profile}. It holds "
                  "a signed-in Canvas session: delete it, or move it there to stay "
                  "signed in, especially if this folder is synced to OneDrive.",
                  file=sys.stderr)
    return browser_quiz_uploads(canvas, BrowserUploadsRequest(
        course_id=args.course, assignment_ids=(args.assignment,),
        out_root=Path(args.out), selection=selection_from(args),
        by_section=args.by_section, limit=args.limit, dry_run=args.dry_run,
        profile=Path(args.profile), channel=args.channel,
        connect_url=args.connect, signin_timeout=args.signin_timeout,
        headless=args.headless, page_timeout=args.page_timeout,
        delay=args.delay), CONSOLE).outcome
