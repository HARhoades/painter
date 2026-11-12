"""One function per mode: turn the parsed flags into a request, call the
service with the console reporter, and return the exit code.

These keep the old (canvas, args) signatures, so the old script name can
keep exporting them under their old names.
"""
from __future__ import annotations

from pathlib import Path

from painter.canvas.client import Canvas
from painter.cli.console import ConsoleReporter
from painter.domain.selection import Selection
from painter.services.grade_files import GradeFilesRequest, make_grade_files
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
