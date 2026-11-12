"""Run one service off the GUI thread and hand its output back in order.

The service runs on a plain worker thread with a QueueReporter. A QTimer on
the GUI thread drains the queue every 100 ms into Qt signals, so widgets
are only ever touched from the GUI thread. When the service returns, the
queue is drained one last time and exactly one of finished / cancelled /
failed is emitted.
"""
from __future__ import annotations

import inspect
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from painter.errors import Cancelled
from painter.events import QueueReporter


class TaskRunner(QObject):
    line = Signal(str, str)            # ("info" | "warning", text)
    progress = Signal(int, int, str)   # done, total, label
    event = Signal(object)             # Stage, ItemDone, Waiting, ActionNeeded
    finished = Signal(object)          # the service's return value
    cancelled = Signal(object)         # Cancelled.result: what was done before the stop
    failed = Signal(object)            # the exception
    busy = Signal(bool)                # True while running

    def __init__(self, parent: QObject | None = None, interval_ms: int = 100):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._drain)
        self._thread: threading.Thread | None = None
        self._outcome: tuple[str, object] | None = None
        self.reporter: QueueReporter | None = None
        self.cancellable = True

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self, fn, *args, cancellable: bool = True, **kwargs) -> None:
        """Run fn(*args, **kwargs) and, if fn takes one, reporter=<QueueReporter>."""
        if self.running:
            raise RuntimeError("a task is already running")
        self.reporter = QueueReporter()
        self.cancellable = cancellable
        self._outcome = None
        try:
            takes_reporter = "reporter" in inspect.signature(fn).parameters
        except (TypeError, ValueError):
            takes_reporter = False
        if takes_reporter:
            kwargs["reporter"] = self.reporter

        def run():
            try:
                self._outcome = ("finished", fn(*args, **kwargs))
            except Cancelled as exc:
                self._outcome = ("cancelled", exc.result)
            except BaseException as exc:          # delivered, never lost on the thread
                self._outcome = ("failed", exc)

        self._thread = threading.Thread(target=run, daemon=True, name="painter-task")
        self._thread.start()
        self._timer.start()
        self.busy.emit(True)

    def cancel(self) -> bool:
        """Ask the service to stop at its next safe point. False if it can't be."""
        if not self.running or not self.cancellable:
            return False
        self.reporter.cancel()
        return True

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the task ends and deliver its signals (tests, closing)."""
        if self._thread is not None:
            self._thread.join(timeout)
        self._drain()
        return not self.running

    def _drain(self) -> None:
        if self.reporter is None:
            return
        done = self._thread is not None and not self._thread.is_alive()
        for kind, payload in self.reporter.drain():
            if kind == "progress":
                self.progress.emit(*payload)
            elif kind == "event":
                self.event.emit(payload)
            else:
                self.line.emit(kind, payload)
        if done:
            self._timer.stop()
            self._thread = None
            outcome, value = self._outcome or ("failed", RuntimeError("task ended without a result"))
            self.busy.emit(False)
            getattr(self, outcome).emit(value)
