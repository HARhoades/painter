"""How services report progress to whichever front end called them.

A service never prints. It is given a Reporter and calls:

  info(text)        a line for the user (the CLI prints it to stdout)
  warning(text)     a note, warning or problem (the CLI prints it to stderr)
  progress(d, t)    d of t items done in the current stage, for a progress bar
  event(e)          a typed event (below), for a GUI's status, tables and prompts
  cancelled()       polled between items and during waits; True means stop as
                    soon as it is safe, which the service does by raising
                    errors.Cancelled (with what it finished on .result)

The text is the same wording the command line has always printed, so the
CLI's output does not change; the CLI ignores progress() and event(). A GUI
runs a service in a worker thread with a QueueReporter and reads the queue
from its own thread.

Events:
  Stage(name, total, step, steps)   a stage starts: "Downloading DATE Scenario",
                                    with how many items it has, and which of
                                    how many stages it is
  StudentStart(name, files, ...)    a student's files begin: how many they have, and
                                    which student this is of how many
  ItemDone(kind, key, status, ...)  one file / grade / folder / upload / student
                                    finished; status as in the logs
  Waiting(reason, seconds, percent) a pause: rate limit, retry, a Canvas job
                                    still running (with its percent if known)
  ActionNeeded(message)             the user must do something, e.g. sign in
                                    in the browser window
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import functools
import inspect
from pathlib import Path
import queue
import threading
from typing import Protocol, Union


# ---- events --------------------------------------------------------------------
@dataclass(frozen=True)
class Stage:
    name: str
    total: int | None = None          # items in this stage, if known
    step: int | None = None           # this stage's number ...
    steps: int | None = None          # ... of how many


@dataclass(frozen=True)
class StudentStart:
    name: str
    files: int                         # files this student's submission has
    index: int = 0                     # this student's number in the stage ...
    total: int = 0                     # ... of how many students with files


@dataclass(frozen=True)
class ItemDone:
    kind: str                          # "file", "grade", "folder", "upload", "student"
    key: str                           # what it is: file name, student, folder
    status: str                        # "downloaded", "cached", "failed: ...", ...
    detail: str = ""
    path: Path | None = None


@dataclass(frozen=True)
class Waiting:
    reason: str
    seconds: float | None = None
    percent: float | None = None


@dataclass(frozen=True)
class ActionNeeded:
    message: str


Event = Union[Stage, StudentStart, ItemDone, Waiting, ActionNeeded]


# ---- reporters -----------------------------------------------------------------
class Reporter(Protocol):
    def info(self, text: str = "", end: str = "\n") -> None:
        """end="" continues the line (console only; others may ignore it)."""

    def warning(self, text: str) -> None: ...

    def progress(self, done: int, total: int, label: str = "") -> None: ...

    def event(self, e: Event) -> None: ...

    def cancelled(self) -> bool: ...


class NullReporter:
    """Discards everything; the default when a caller passes no reporter."""

    def info(self, text: str = "", end: str = "\n") -> None:
        pass

    def warning(self, text: str) -> None:
        pass

    def progress(self, done: int, total: int, label: str = "") -> None:
        pass

    def event(self, e: Event) -> None:
        pass

    def cancelled(self) -> bool:
        return False


class RecordingReporter:
    """Keeps everything, for tests: .lines holds ("info"|"warning", text),
    .events the typed events. cancel_after=n answers True from poll n+1 on."""

    def __init__(self, cancel_after: int | None = None):
        self.lines: list[tuple[str, str]] = []
        self.progress_events: list[tuple[int, int, str]] = []
        self.events: list[Event] = []
        self._cancel_after = cancel_after
        self._polls = 0

    def info(self, text: str = "", end: str = "\n") -> None:
        self.lines.append(("info", text))

    def warning(self, text: str) -> None:
        self.lines.append(("warning", text))

    def progress(self, done: int, total: int, label: str = "") -> None:
        self.progress_events.append((done, total, label))

    def event(self, e: Event) -> None:
        self.events.append(e)

    def cancelled(self) -> bool:
        self._polls += 1
        return self._cancel_after is not None and self._polls > self._cancel_after

    def text(self, kind: str | None = None) -> str:
        return "\n".join(t for k, t in self.lines if kind in (None, k))

    def of(self, kind: type) -> list:
        return [e for e in self.events if isinstance(e, kind)]


class QueueReporter:
    """Thread-safe: the service (worker thread) puts everything on .queue as
    ("info", text) / ("warning", text) / ("progress", (done, total, label)) /
    ("event", Event); the GUI thread reads it. cancel() asks the service to
    stop at its next safe point."""

    def __init__(self):
        self.queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()

    def info(self, text: str = "", end: str = "\n") -> None:
        self.queue.put(("info", text))

    def warning(self, text: str) -> None:
        self.queue.put(("warning", text))

    def progress(self, done: int, total: int, label: str = "") -> None:
        self.queue.put(("progress", (done, total, label)))

    def event(self, e: Event) -> None:
        self.queue.put(("event", e))

    def cancel(self) -> None:
        self._cancel.set()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def drain(self) -> list:
        """Everything queued so far, without blocking."""
        out = []
        while True:
            try:
                out.append(self.queue.get_nowait())
            except queue.Empty:
                return out


NULL = NullReporter()


# Foundations (canvas/, domain/, storage/) do not take a reporter; when they
# have something to say they return it as notes for the caller to emit.
Note = tuple[str, str]          # ("info" | "warning", text)


def emit(notes: list[Note], reporter: Reporter) -> None:
    for kind, text in notes:
        (reporter.warning if kind == "warning" else reporter.info)(text)


# ---- connecting a reporter to the Canvas client --------------------------------
@contextmanager
def watch(canvas, reporter: Reporter, cancellable: bool = True):
    """While a service runs: every pause the client makes (rate limit,
    retry, job polling) becomes a Waiting event, and, if cancellable, is
    cut short by reporter.cancelled(). Restores the client afterwards."""
    old = canvas.on_wait, canvas.should_stop

    def on_wait(reason, seconds, percent=None):
        reporter.event(Waiting(reason, seconds, percent))

    canvas.on_wait = on_wait
    canvas.should_stop = reporter.cancelled if cancellable else None
    try:
        yield
    finally:
        canvas.on_wait, canvas.should_stop = old


def watches_canvas(cancellable: bool = True):
    """Decorator for a service f(canvas, ..., reporter=NULL): runs it inside
    watch(canvas, reporter, cancellable)."""
    def deco(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kw):
            bound = sig.bind(*args, **kw)
            bound.apply_defaults()
            canvas = bound.arguments["canvas"]
            reporter = bound.arguments.get("reporter") or NULL
            with watch(canvas, reporter, cancellable):
                return fn(*args, **kw)
        return wrapper
    return deco
