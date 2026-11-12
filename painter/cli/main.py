"""Command line: `painter <command> [options]`.

    painter list assignments | sections | students
    painter download
    painter roster FILE
    painter organize FOLDER --roster FILE
    painter grades new
    painter grades post FILE...
    painter quiz export
    painter quiz uploads

--base-url, --course and --tz may go before or after the command. Each
command accepts only its own options. docs/manual.md has the full manual.
"""
from __future__ import annotations

import argparse
import sys
import textwrap

from painter.cli import commands, exit_codes
from painter.config import default_browser_profile


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return its exit status (see cli/exit_codes.py)."""
    debug = "--debug" in (sys.argv[1:] if argv is None else argv)
    try:
        return _run(argv)
    except SystemExit:
        raise                                   # argparse usage errors: status 2
    except BaseException as exc:                # Ctrl+C included
        return exit_codes.for_exception(exc, debug)


def _run(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "run", None):
        parser.error("choose a command (see --help)")
    return args.run(args, args.parser_for_errors)


# ---- the parser ------------------------------------------------------------------
class _Once(argparse.Action):
    """A single-valued option given twice is an error, not 'last one wins'
    (`--assignment 1 --assignment 2` must not quietly use 2)."""

    def __call__(self, parser, namespace, values, option_string=None):
        seen = set(getattr(namespace, "_given_once", ()))
        if self.dest in seen:
            parser.error(f"{option_string} can be given only once")
        setattr(namespace, "_given_once", seen | {self.dest})
        setattr(namespace, self.dest, values)

def _global_options(p: argparse.ArgumentParser, suppress: bool) -> None:
    """--base-url, --course, --tz. On a command's parser they default to
    SUPPRESS, so a value given before the command is not overwritten."""
    d = (lambda v: argparse.SUPPRESS) if suppress else (lambda v: v)
    g = p.add_argument_group("Canvas")
    g.add_argument("--base-url", default=d(None),
                   help="e.g. https://yourschool.instructure.com")
    g.add_argument("--course", type=int, default=d(None), help="Course ID")
    g.add_argument("--tz", metavar="ZONE", default=d(None),
                   help="IANA zone for times shown and logged, e.g. America/New_York "
                        "(default: UTC, as Canvas returns them)")
    g.add_argument("--debug", action="store_true", default=d(False),
                   help="on an unexpected error, print the full traceback")


def _selection(p: argparse.ArgumentParser) -> None:
    p.add_argument("--section", action="append", metavar="SPEC",
                   help="Section ID, SIS section ID or name (repeatable). An exact "
                        "ID or name wins over a partial name.")
    p.add_argument("--student", action="append", metavar="SPEC",
                   help="Canvas ID, SIS ID, login or name (repeatable). With "
                        "--section, everyone in either is selected.")
    p.add_argument("--exclude", action="append", metavar="SPEC",
                   help="A student to leave out of the selection (repeatable): "
                        "Canvas ID, SIS ID, login or name. Alone, means everyone "
                        "except them.")


def _command(subs, name: str, run, help: str, description: str | None = None):
    p = subs.add_parser(name, help=help, description=description or help)
    _global_options(p, suppress=True)
    p.set_defaults(run=run, parser_for_errors=p)
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="painter",
        description="Canvas chores for instructors: download submissions, rosters, "
                    "grade files and grade posting, quiz export. "
                    "Token: the CANVAS_API_TOKEN environment variable.",
        epilog="`painter <command> --help` lists a command's options. "
               "Full manual: docs/manual.md.\n\nexit status:\n" + "\n".join(
                   textwrap.fill(what, 78, initial_indent=f"  {code:>3}  ",
                                 subsequent_indent=" " * 7)
                   for code, what in exit_codes.TABLE),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    _global_options(parser, suppress=False)
    subs = parser.add_subparsers(title="commands", metavar="<command>")

    _add_list(subs)
    _add_download(subs)
    _add_roster(subs)
    _add_organize(subs)
    _add_grades(subs)
    _add_quiz(subs)
    return parser


def _add_list(subs) -> None:
    lst = subs.add_parser("list", help="list assignments, sections or students",
                          description="List assignments, sections or students.")
    lsubs = lst.add_subparsers(title="what", metavar="<what>")
    lst.set_defaults(run=None)
    _command(lsubs, "assignments", commands.list_assignments, "assignment IDs and names")
    _command(lsubs, "sections", commands.list_sections,
             "section IDs, SIS IDs, sizes and names")
    p = _command(lsubs, "students", commands.list_students,
                 "the roster: IDs, SIS IDs or logins, names, sections")
    _selection(p)
    p.add_argument("--assignment", type=int, action="append", metavar="ID",
                   help="only students who have this assignment (repeatable)")


def _add_download(subs) -> None:
    p = _command(subs, "download", commands.download,
                 "download submission files (and unpack archives)",
                 "Download students' submission files into "
                 "<out>/<Assignment>_<id>/<Student>_<id>/, with manifest.csv and an "
                 "Excel log.")
    p.add_argument("--assignment", type=int, action="append", metavar="ID",
                   help="assignment ID (repeatable; default: every assignment)")
    _selection(p)
    p.add_argument("--out", default="./submissions", metavar="DIR",
                   help="output folder (default ./submissions)")
    p.add_argument("--by-section", action="store_true",
                   help="a folder per section inside each assignment folder")
    p.add_argument("--flat", action="store_true",
                   help="no folder per student: files go straight into the assignment "
                        "(or section) folder, prefixed with the student")
    p.add_argument("--no-extract", action="store_true", help="leave archives zipped")
    p.add_argument("--history", action="store_true",
                   help="also fetch earlier attempts (resubmissions)")
    p.add_argument("--no-xlsx", action="store_true", help="skip the Excel run log")
    p.add_argument("--log-dir", metavar="DIR", help="where the Excel log goes (default --out)")


def _add_roster(subs) -> None:
    p = _command(subs, "roster", commands.roster,
                 "write the roster as a CSV (for organize)",
                 "Write a CSV of students: name, Canvas ID, first/last name, instructor, "
                 "section, section ID, sorted by last name.")
    p.add_argument("file", metavar="FILE", help="the CSV to write")
    _selection(p)
    p.add_argument("--assignment", type=int, action="append", metavar="ID",
                   help="only students who have this assignment (repeatable)")


def _add_organize(subs) -> None:
    p = _command(subs, "organize", commands.organize,
                 "sort downloaded folders into section folders (offline)",
                 "Sort student folders (or an --out folder of assignment folders) into "
                 "one folder per section, using a roster CSV from `painter roster`. "
                 "Needs no Canvas access.")
    p.add_argument("folder", metavar="FOLDER", help="the folder to sort")
    p.add_argument("--roster", required=True, metavar="FILE",
                   help="a CSV written by `painter roster`")
    p.add_argument("--to", metavar="DIR",
                   help="copy into this folder instead of moving in place")
    p.add_argument("--section", action="append", metavar="SPEC",
                   help="only these sections (repeatable)")
    p.add_argument("--dry-run", action="store_true",
                   help="show where everything would go; change nothing")


def _add_grades(subs) -> None:
    grades = subs.add_parser("grades", help="make grade files, or post them",
                             description="Make blank grade files, or post filled-in ones.")
    gsubs = grades.add_subparsers(title="what", metavar="<what>")
    grades.set_defaults(run=None)
    p = _command(gsubs, "new", commands.grades_new,
                 "write a blank grade file per section",
                 "Write one grade file per section with each student's name and "
                 "Canvas ID filled in, ready for grades and comments.")
    p.add_argument("--assignment", type=int, metavar="ID", action=_Once,
                   help="fills in the assignment title and id (optional)")
    p.add_argument("--section", action="append", metavar="SPEC",
                   help="only these sections (repeatable; default: every section)")
    p.add_argument("--label", metavar="NAME",
                   help="assignment part of the file name (default: first word of "
                        "the assignment name; required without --assignment)")
    p.add_argument("--ay", metavar="YY", help="academic year (default: from the term name)")
    p.add_argument("--term", metavar="N", help="semester (default: from the term name)")
    p.add_argument("--dir", default=".", metavar="DIR",
                   help="where to write the files (default: current folder)")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p = _command(gsubs, "post", commands.grades_post,
                 "post grade files to Canvas (shows the plan, then asks)",
                 "Check grade files against Canvas, show what would change, ask, "
                 "post with one bulk request per file, then read back and verify. "
                 "--course is optional: it is found from the file's section.")
    p.add_argument("files", nargs="+", metavar="FILE", help="grade file(s)")
    p.add_argument("--dry-run", action="store_true",
                   help="check and show the plan; post nothing")
    p.add_argument("--yes", action="store_true", help="post without asking")
    p.add_argument("--allow-duplicate-comments", action="store_true",
                   help="post a comment even if the same text is already there")
    p.add_argument("--log-dir", metavar="DIR",
                   help="where the post log goes (default: the first file's folder)")


def _add_quiz(subs) -> None:
    quiz = subs.add_parser("quiz", help="export a quiz, or its file uploads",
                           description="Export a quiz, or fetch its File Upload answers.")
    qsubs = quiz.add_subparsers(title="what", metavar="<what>")
    quiz.set_defaults(run=None)
    p = _command(qsubs, "export", commands.quiz_export,
                 "a quiz's content and student answers",
                 "Export one quiz: New Quizzes as JSON + QTI with the student analysis "
                 "report; Classic Quizzes through Canvas's QTI export. Canvas jobs are "
                 "resumed, never started twice.")
    p.add_argument("--assignment", type=int, required=True, metavar="ID", action=_Once,
                   help="the quiz's assignment ID")
    _selection(p)
    p.add_argument("--by-section", action="store_true",
                   help="a folder per section, each with its own answers")
    p.add_argument("--out", default="./submissions", metavar="DIR",
                   help="output folder (default ./submissions)")
    p.add_argument("--no-answers", action="store_true", help="content only")
    p.add_argument("--uploads", action="store_true",
                   help="also download File Upload answers linked from the report")
    p.add_argument("--no-course-export", action="store_true",
                   help="skip the Common Cartridge course export (the slowest part)")
    p.add_argument("--timeout", type=float, default=900, metavar="SECONDS",
                   help="how long to wait for each Canvas job (default 900); a rerun "
                        "resumes a job that timed out")
    p.add_argument("--dry-run", action="store_true",
                   help="read the quiz and show the plan; write nothing, start no job")
    p = _command(qsubs, "uploads", commands.quiz_uploads,
                 "a New Quiz's File Upload answers, through the browser",
                 "Open each submitted student in SpeedGrader in a browser and save "
                 "their File Upload answers. Needs Playwright.")
    p.add_argument("--assignment", type=int, required=True, metavar="ID", action=_Once,
                   help="the New Quiz's assignment ID")
    _selection(p)
    p.add_argument("--by-section", action="store_true", help="a folder per section")
    p.add_argument("--out", default="./submissions", metavar="DIR",
                   help="output folder (default ./submissions)")
    p.add_argument("--profile", metavar="DIR",
                   help=f"browser profile that keeps you signed in (default "
                        f"{default_browser_profile()}, not synced). Keep it private.")
    p.add_argument("--channel", default="chrome", choices=["chrome", "msedge", "chromium"],
                   help="installed Chrome (default), Edge, or Playwright's Chromium")
    p.add_argument("--connect", metavar="URL",
                   help="use a browser you started with --remote-debugging-port, e.g. "
                        "http://localhost:9222 (if sign-in, e.g. CAC, hangs otherwise)")
    p.add_argument("--headless", action="store_true",
                   help="hide the window (only once the profile is signed in)")
    p.add_argument("--signin-timeout", type=float, default=600, metavar="SECONDS",
                   help="how long to wait for you to sign in (default 600)")
    p.add_argument("--page-timeout", type=float, default=45, metavar="SECONDS",
                   help="how long to wait for each student's quiz (default 45)")
    p.add_argument("--delay", type=float, default=1.0, metavar="SECONDS",
                   help="pause between students (default 1)")
    p.add_argument("--limit", type=int, metavar="N",
                   help="only the first N students (alphabetical), for a trial run")
    p.add_argument("--dry-run", action="store_true",
                   help="list who would be visited; open no browser")
