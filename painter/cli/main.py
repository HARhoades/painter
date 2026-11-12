"""Command line front end: argument parsing and dispatch."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

import requests

from painter.canvas.client import Canvas, check_base_url
from painter.cli.console import ConsoleReporter
from painter.errors import CanvasHTTPError, PainterError
from painter.events import emit
from painter.config import LEGACY_BROWSER_PROFILE, TOKEN_ENV, default_browser_profile
from painter.services.grade_files import make_grade_files
from painter.services.grading import post_grades
from painter.services.organize import organize_submissions
from painter.services.quiz_export import export_quiz
from painter.services.quiz_uploads import browser_quiz_uploads
from painter.services.roster_export import export_roster_csv
from painter.services.submissions import run_download


# Exit status when Canvas could not be used at all (bad token, no permission,
# missing item, Canvas down). 1-3 are already taken by individual modes.
EXIT_CANVAS_ERROR = 4


def main() -> int:
    """Run the command line; Canvas errors become one line and exit code 4."""
    try:
        return _main()
    except CanvasHTTPError as exc:
        print(f"Error: {exc.hint or 'Canvas returned an error.'}\n  ({exc})",
              file=sys.stderr)
        return EXIT_CANVAS_ERROR
    except PainterError as exc:
        # Same as the SystemExit(message) these used to be: message on
        # stderr, exit status 1.
        emit(exc.notes, ConsoleReporter())
        raise SystemExit(str(exc)) from None
    except requests.ConnectionError as exc:
        print(f"Error: could not reach Canvas ({exc}).", file=sys.stderr)
        return EXIT_CANVAS_ERROR


def _main() -> int:
    p = argparse.ArgumentParser(
        description="Bulk-download Canvas submissions, or bulk-post grades and comments.")
    p.add_argument("--base-url",
                   help="e.g. https://yourschool.instructure.com "
                        "(not needed with --organize)")
    p.add_argument("--course", type=int,
                   help="Course ID (optional with --post-grades: taken from the section)")
    p.add_argument("--assignment", type=int, action="append",
                   help="Assignment ID (repeatable). Default: all assignments.")
    p.add_argument("--out", default="./submissions", help="Output directory")
    p.add_argument("--student", action="append", metavar="SPEC",
                   help="Canvas ID, SIS ID, login, or name fragment (repeatable). "
                        "Default: all students.")
    p.add_argument("--section", action="append", metavar="SPEC",
                   help="Section ID, SIS section ID, or name fragment (repeatable). "
                        "Combined with --student as a union.")
    p.add_argument("--by-section", action="store_true",
                   help="Nest output folders under section name")
    p.add_argument("--flat", action="store_true",
                   help="Don't create a folder per student; save files directly "
                        "in the assignment folder (or the section folder with "
                        "--by-section), prefixed with the student's name and ID")
    p.add_argument("--list-assignments", action="store_true",
                   help="Print assignment IDs and exit")
    p.add_argument("--list-students", action="store_true",
                   help="Print the course roster and exit. Honours --section, "
                        "--student and --assignment.")
    p.add_argument("--list-sections", action="store_true",
                   help="Print the course sections and exit")
    p.add_argument("--tz", metavar="ZONE",
                   help="IANA zone for displaying times, e.g. America/New_York. "
                        "Canvas returns UTC; without this, UTC is written.")
    p.add_argument("--no-xlsx", action="store_true",
                   help="Skip the Excel run log")
    p.add_argument("--log-dir", metavar="DIR",
                   help="Where to write the Excel log (default: --out)")
    p.add_argument("--no-extract", action="store_true",
                   help="Download archives but leave them zipped")
    p.add_argument("--history", action="store_true",
                   help="Also fetch superseded resubmissions")
    g = p.add_argument_group("posting grades and comments")
    g.add_argument("--post-grades", action="append", metavar="FILE",
                   help="Grade file to post via the bulk update_grades endpoint "
                        "(repeatable). See the module docstring for the format.")
    g.add_argument("--dry-run", action="store_true",
                   help="With --post-grades: check files against Canvas and show "
                        "the plan, but post nothing. With --organize: show "
                        "where everything would go, change nothing. With "
                        "--export-quiz: fetch the quiz and show how each item "
                        "converts and where files would go, but write nothing "
                        "and start no report or export job.")
    g.add_argument("--yes", action="store_true",
                   help="With --post-grades: skip the confirmation prompt")
    g.add_argument("--allow-duplicate-comments", action="store_true",
                   help="Post a comment even if the same text is already on the "
                        "submission")
    g2 = p.add_argument_group("creating grade files")
    g2.add_argument("--make-grade-files", action="store_true",
                    help="Write a blank grade file per --section (default: every "
                         "section), with each student's name and Canvas ID filled in")
    g2.add_argument("--assignment-label", metavar="NAME",
                    help="Assignment part of the filename. Default: the first word "
                         "of the Canvas assignment name. Required without --assignment.")
    g2.add_argument("--ay", metavar="YY",
                    help="Academic year for the filename. Default: read from the "
                         "course's term name.")
    g2.add_argument("--term", metavar="N",
                    help="Semester for the filename. Default: read from the "
                         "course's term name.")
    g2.add_argument("--grade-file-dir", default=".", metavar="DIR",
                    help="Where to write the grade files (default: current directory)")
    g2.add_argument("--force", action="store_true",
                    help="Overwrite grade files that already exist")
    g3 = p.add_argument_group("exporting the roster")
    g3.add_argument("--roster-csv", metavar="FILE",
                    help="Write a CSV of students (name, Canvas ID, first/last "
                         "name, instructor, section, section ID), sorted by last "
                         "name, and exit. Honours --section, --student and "
                         "--assignment.")
    g4 = p.add_argument_group("sorting submissions into section folders")
    g4.add_argument("--organize", metavar="DIR",
                    help="Folder of student sub-folders (or an --out folder of "
                         "assignment folders) to sort into one folder per section, "
                         "using --roster. Works offline.")
    g4.add_argument("--roster", metavar="FILE",
                    help="With --organize: a CSV written by --roster-csv")
    g4.add_argument("--organize-to", metavar="DIR",
                    help="With --organize: copy into this folder instead of "
                         "moving in place")
    g5 = p.add_argument_group("exporting quiz questions and answers")
    g5.add_argument("--export-quiz", action="store_true",
                    help="Download one New Quiz's student answers plus its "
                         "content (--assignment is the quiz's assignment ID) into "
                         "its folder under --out. --section/--student choose whose "
                         "answers are kept; --by-section writes one folder per "
                         "section, each with a copy of the quiz content.")
    g5.add_argument("--no-answers", action="store_true",
                    help="With --export-quiz: export the quiz content only, "
                         "without student answers")
    g5.add_argument("--quiz-uploads", action="store_true",
                    help="With --export-quiz (New Quizzes): also download the "
                         "files students uploaded to File Upload questions, "
                         "found as links in the student analysis report, into "
                         "<Quiz>_uploads/<Student>/. Best effort: New Quizzes "
                         "has no API for these files.")
    g6 = p.add_argument_group("New Quiz file uploads through the browser (Playwright)")
    g6.add_argument("--browser-uploads", action="store_true",
                    help="Download a New Quiz's File Upload answers by opening each "
                         "submitted student in SpeedGrader in a browser. Needs "
                         "--assignment; honours --section/--student/--by-section.")
    g6.add_argument("--browser-profile", metavar="DIR",
                    help="Browser profile folder that keeps you signed in between "
                         f"runs (default {default_browser_profile()}, a local "
                         "folder that is not synced to OneDrive). Keep it private.")
    g6.add_argument("--browser-channel", default="chrome",
                    choices=["chrome", "msedge", "chromium"],
                    help="Installed Chrome (default), Edge, or Playwright's own Chromium")
    g6.add_argument("--connect-browser", metavar="URL",
                    help="Use a Chrome/Edge you started yourself with "
                         "--remote-debugging-port, e.g. http://localhost:9222, "
                         "instead of launching one. Use this if sign-in (e.g. "
                         "CAC) hangs in the browser the script starts.")
    g6.add_argument("--signin-timeout", type=float, default=600, metavar="SECONDS",
                    help="How long to wait for you to sign in (default 600)")
    g6.add_argument("--headless", action="store_true",
                    help="Hide the browser window (only once the profile is signed in)")
    g6.add_argument("--page-timeout", type=float, default=45, metavar="SECONDS",
                    help="How long to wait for each student's quiz to load (default 45)")
    g6.add_argument("--delay", type=float, default=1.0, metavar="SECONDS",
                    help="Pause between students (default 1)")
    g6.add_argument("--limit", type=int, metavar="N",
                    help="Only the first N students (alphabetical) -- for a trial run")
    g5.add_argument("--no-course-export", action="store_true",
                    help="With --export-quiz: skip the Common Cartridge course "
                         "export attempt (the slowest, heaviest part)")
    g5.add_argument("--export-timeout", type=float, default=900, metavar="SECONDS",
                    help="With --export-quiz: how long to wait for each Canvas "
                         "report or export job (default 900). A rerun resumes a "
                         "job that timed out.")
    args = p.parse_args()
    if args.browser_profile is None:
        args.browser_profile = str(default_browser_profile())
        if args.browser_uploads and Path(LEGACY_BROWSER_PROFILE).is_dir():
            print(f"note: ./{LEGACY_BROWSER_PROFILE} (the old default) is no longer "
                  f"used; the profile now lives in {args.browser_profile}. It holds "
                  "a signed-in Canvas session: delete it, or move it there to stay "
                  "signed in, especially if this folder is synced to OneDrive.",
                  file=sys.stderr)
    modes = [m for m, on in (("--post-grades", args.post_grades),
                             ("--make-grade-files", args.make_grade_files),
                             ("--roster-csv", args.roster_csv),
                             ("--organize", args.organize),
                             ("--export-quiz", args.export_quiz),
                             ("--browser-uploads", args.browser_uploads)) if on]
    if len(modes) > 1:
        p.error(" and ".join(modes) + " cannot be combined")
    if args.organize:
        if not args.roster:
            p.error("--organize needs --roster FILE (make one with --roster-csv)")
        return organize_submissions(args)
    if args.quiz_uploads and (not args.export_quiz or args.no_answers):
        p.error("--quiz-uploads needs --export-quiz (and the answers report, "
                "so not --no-answers)")
    if (args.roster or args.organize_to) and not args.organize:
        p.error("--roster and --organize-to are only used with --organize")
    if not args.base_url:
        p.error("--base-url is required")
    try:
        args.base_url = check_base_url(args.base_url)
    except ValueError as exc:
        p.error(str(exc))
    if args.course is None and not args.post_grades:
        p.error("--course is required (it is optional only with --post-grades)")
    run_started = datetime.now()   # names the log file; local clock, not UTC

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"Set the {TOKEN_ENV} environment variable first.", file=sys.stderr)
        return 1

    canvas = Canvas(args.base_url, token)

    if args.post_grades:
        return post_grades(canvas, args, run_started)

    if args.make_grade_files:
        return make_grade_files(canvas, args)

    if args.roster_csv:
        return export_roster_csv(canvas, args)

    if args.export_quiz:
        return export_quiz(canvas, args)

    if args.browser_uploads:
        return browser_quiz_uploads(canvas, args)

    return run_download(canvas, args, run_started)
