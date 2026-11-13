"""Turn any exception into words for the window: a title, a sentence, and
what kind of banner it is. Mirrors the command line's exit-status table."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from painter.crash import write_crash_report
from painter.errors import (
    AuthFailed, BrowserUnavailable, CanvasHTTPError, CanvasUnavailable, Forbidden,
    InvalidInput, MissingDependency, NotFound, PainterError, is_connection_error,
)


def short_reason(exc: BaseException) -> str:
    """One short line for a tag or tooltip; unlike describe(), writes nothing."""
    first = (str(exc).strip().splitlines() or [""])[0]
    return (first or type(exc).__name__)[:140]


@dataclass
class Problem:
    title: str
    body: str
    kind: str = "error"                   # banner kind
    settings: bool = False                # offer "Open settings"
    details: Path | None = None           # crash report, for "Copy details"


def _plain(text: str) -> str:
    """CLI wording -> window wording."""
    return (text.replace("--base-url must be", "The Canvas address must be")
                .replace("Check that CANVAS_API_TOKEN holds", "Check that you're using"))


def describe(exc: BaseException) -> Problem:
    if isinstance(exc, AuthFailed):
        return Problem("Canvas didn't accept your token",
                       "Make a new token in Canvas (Account › Settings › New access token) "
                       "and connect again.", settings=True)
    if isinstance(exc, Forbidden):
        return Problem("Canvas says you don't have permission for this",
                       "Your role in this course may not allow it (a TA's access can be "
                       "narrower than a teacher's).")
    if isinstance(exc, NotFound):
        return Problem("Canvas couldn't find that", "It may have been deleted or moved. "
                       "Refresh and try again.")
    if isinstance(exc, CanvasUnavailable) or is_connection_error(exc):
        return Problem("Canvas can't be reached right now",
                       "Check your connection, then try again.")
    if isinstance(exc, CanvasHTTPError):
        return Problem("Canvas returned an error", exc.hint or str(exc))
    if isinstance(exc, InvalidInput):
        return Problem("That can't be used", _plain(str(exc)))
    if isinstance(exc, (MissingDependency, BrowserUnavailable)):
        return Problem("Something is missing on this computer", str(exc))
    if isinstance(exc, OSError):
        return Problem("A file couldn't be read or written", str(exc))
    if isinstance(exc, PainterError):
        return Problem("That didn't work", str(exc))
    path = write_crash_report(exc, "painter-gui")
    return Problem("Something unexpected went wrong",
                   f"{type(exc).__name__}: {exc}", details=path)
