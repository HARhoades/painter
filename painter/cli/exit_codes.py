"""The command line's exit status: one table for every command."""
from __future__ import annotations

from datetime import datetime
import sys
import traceback

import requests

from painter.config import app_data_dir
from painter.errors import (
    BrowserUnavailable, Cancelled, CanvasHTTPError, InvalidInput, MissingDependency,
    PainterError,
)
from painter.services import quiz_export, quiz_uploads

OK = 0              # done (also: dry run, nothing to post, answering no)
PROBLEMS = 1        # finished, but something failed; the output says what
BAD_INPUT = 2       # wrong options, no match for a spec, grade-file errors
NOTHING = 3         # nothing matched: no selected student has the quiz
CANVAS = 4          # Canvas could not be used: token, permission, not found, down
SETUP = 5           # local setup: token not set, package or browser missing, disk
UNKNOWN = 6         # failed, cause unknown (a crash report is written)
INTERRUPTED = 130   # Ctrl+C

TABLE = [
    (OK, "done (also a dry run, nothing to post, or answering no at the prompt)"),
    (PROBLEMS, "finished with problems: some files failed, grades not verified, "
               "quiz answers missing or the course export unfinished"),
    (BAD_INPUT, "bad input: wrong or misplaced options, a --section/--student/"
                "--assignment that matches nothing, errors in a grade file"),
    (NOTHING, "nothing matched: none of the selected students has the quiz"),
    (CANVAS, "Canvas could not be used: bad token, no permission, not found, "
             "down or unreachable"),
    (SETUP, "local setup: CANVAS_API_TOKEN not set, a package (openpyxl, "
            "playwright) or the browser missing, a file that can't be written"),
    (UNKNOWN, "failed, cause unknown: a crash report is saved and its path printed"),
    (INTERRUPTED, "interrupted with Ctrl+C"),
]

QUIZ_EXPORT = {quiz_export.EXPORTED: OK, quiz_export.NOTHING_SELECTED: NOTHING,
               quiz_export.COURSE_EXPORT_INCOMPLETE: PROBLEMS,
               quiz_export.ANSWERS_MISSING: PROBLEMS}

QUIZ_UPLOADS = {quiz_uploads.UPLOADS_DONE: OK, quiz_uploads.NO_STUDENTS: NOTHING,
                quiz_uploads.UPLOADS_WITH_PROBLEMS: PROBLEMS}


def for_exception(exc: BaseException, debug: bool = False) -> int:
    """Say what went wrong, in one line where possible, and pick the status."""
    from painter.cli.console import ConsoleReporter
    from painter.events import emit
    if isinstance(exc, PainterError):
        emit(exc.notes, ConsoleReporter())
    if isinstance(exc, CanvasHTTPError):
        _err(f"Error: {exc.hint or 'Canvas returned an error.'}\n  ({exc})")
        return CANVAS
    if isinstance(exc, requests.ConnectionError):
        _err(f"Error: could not reach Canvas ({exc}).")
        return CANVAS
    if isinstance(exc, Cancelled):
        _err(f"Stopped: {exc}")
        return INTERRUPTED
    if isinstance(exc, KeyboardInterrupt):
        _err("Interrupted.")
        return INTERRUPTED
    if isinstance(exc, InvalidInput):
        _err(str(exc))
        return BAD_INPUT
    if isinstance(exc, (MissingDependency, BrowserUnavailable)):
        _err(str(exc))
        return SETUP
    if isinstance(exc, OSError):
        _err(f"Error: {exc}")
        return SETUP
    if isinstance(exc, PainterError):
        _err(str(exc))
        return PROBLEMS
    return _crash(exc, debug)


def _crash(exc: BaseException, debug: bool) -> int:
    """Failed for a reason the tool doesn't recognise: one line, and the full
    traceback in a crash report (or on screen with --debug)."""
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if debug:
        _err(text.rstrip())
        return UNKNOWN
    path = None
    try:
        logs = app_data_dir() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / f"crash_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path.write_text(f"painter {' '.join(sys.argv[1:])}\n\n{text}", encoding="utf-8")
    except OSError:
        path = None
    _err(f"Error: unexpected problem ({type(exc).__name__}: {exc}).")
    _err(f"  Details: {path}" if path else "  Run again with --debug to see the details.")
    return UNKNOWN


def _err(text: str) -> None:
    print(text, file=sys.stderr)
