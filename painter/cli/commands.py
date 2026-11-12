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
from painter.domain.selection import Selection
from painter.services.grade_files import GradeFilesRequest, make_grade_files
from painter.services.grading import plan_grades, post_grade_plans
from painter.services.organize import OrganizeRequest, execute_organize, plan_organize
from painter.services.roster_export import RosterExportRequest, export_roster_csv

CONSOLE = ConsoleReporter()


def selection_from(args) -> Selection:
    return Selection.of(getattr(args, "section", None), getattr(args, "student", None))


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
