"""How services report progress to whichever front end called them.

A service never prints. It is given a Reporter and calls:

  info(text)        a line for the user (the CLI prints it to stdout)
  warning(text)     a note, warning or problem (the CLI prints it to stderr)
  progress(d, t)    d of t items done, for a progress bar (the CLI ignores it)
  cancelled()       polled between items; True means stop as soon as it is
                    safe, which the service does by raising errors.Cancelled

The text is the same wording the command line has always printed, so the
CLI's output does not change. A GUI can show it in a log pane.
"""
from __future__ import annotations

from typing import Protocol


class Reporter(Protocol):
    def info(self, text: str = "", end: str = "\n") -> None:
        """end="" continues the line (console only; others may ignore it)."""

    def warning(self, text: str) -> None: ...

    def progress(self, done: int, total: int, label: str = "") -> None: ...

    def cancelled(self) -> bool: ...


class NullReporter:
    """Discards everything; the default when a caller passes no reporter."""

    def info(self, text: str = "", end: str = "\n") -> None:
        pass

    def warning(self, text: str) -> None:
        pass

    def progress(self, done: int, total: int, label: str = "") -> None:
        pass

    def cancelled(self) -> bool:
        return False


class RecordingReporter:
    """Keeps everything, for tests: .lines holds ("info"|"warning", text)."""

    def __init__(self, cancel_after: int | None = None):
        self.lines: list[tuple[str, str]] = []
        self.progress_events: list[tuple[int, int, str]] = []
        self._cancel_after = cancel_after
        self._polls = 0

    def info(self, text: str = "", end: str = "\n") -> None:
        self.lines.append(("info", text))

    def warning(self, text: str) -> None:
        self.lines.append(("warning", text))

    def progress(self, done: int, total: int, label: str = "") -> None:
        self.progress_events.append((done, total, label))

    def cancelled(self) -> bool:
        self._polls += 1
        return self._cancel_after is not None and self._polls > self._cancel_after

    def text(self, kind: str | None = None) -> str:
        return "\n".join(t for k, t in self.lines if kind in (None, k))


NULL = NullReporter()
