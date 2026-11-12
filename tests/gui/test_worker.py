"""TaskRunner: a service off the GUI thread, its output back in order (phase 5, step 7)."""
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from painter.errors import Cancelled  # noqa: E402
from painter.events import ItemDone, Stage  # noqa: E402
from painter.gui.worker import TaskRunner  # noqa: E402


def service(n, reporter):
    reporter.event(Stage("Counting", total=n))
    for i in range(n):
        reporter.info(f"item {i}")
        reporter.progress(i + 1, n, f"item {i}")
        reporter.event(ItemDone("file", f"f{i}", "downloaded"))
    reporter.warning("done with a note")
    return n * 10


def record(runner):
    got = []
    runner.line.connect(lambda k, t: got.append(("line", k, t)))
    runner.progress.connect(lambda d, t, label: got.append(("progress", d, t)))
    runner.event.connect(lambda e: got.append(("event", e)))
    for name in ("finished", "cancelled", "failed"):
        getattr(runner, name).connect(lambda v, name=name: got.append((name, v)))
    return got


def test_everything_arrives_in_order_then_finished(qtbot):
    r = TaskRunner()
    got = record(r)
    with qtbot.waitSignal(r.finished, timeout=5000):
        r.start(service, 2)
    assert got[0] == ("event", Stage("Counting", total=2))
    assert got[1:4] == [("line", "info", "item 0"), ("progress", 1, 2),
                        ("event", ItemDone("file", "f0", "downloaded"))]
    assert got[-2] == ("line", "warning", "done with a note")
    assert got[-1] == ("finished", 20)
    assert not r.running


def test_cancel_delivers_the_partial_result(qtbot):
    gate = threading.Event()

    def slow(reporter):
        gate.wait(5)
        if reporter.cancelled():
            raise Cancelled("stopped", {"done": 1})
        return "not stopped"

    r = TaskRunner()
    with qtbot.waitSignal(r.cancelled, timeout=5000) as sig:
        r.start(slow)
        assert r.cancel()
        gate.set()
    assert sig.args == [{"done": 1}]


def test_an_exception_reaches_failed(qtbot):
    def boom():
        raise ZeroDivisionError("bad sum")
    r = TaskRunner()
    with qtbot.waitSignal(r.failed, timeout=5000) as sig:
        r.start(boom)               # no reporter parameter: none passed
    assert isinstance(sig.args[0], ZeroDivisionError)


def test_not_cancellable_ignores_cancel_and_one_task_at_a_time(qtbot):
    gate = threading.Event()
    r = TaskRunner()
    with qtbot.waitSignal(r.finished, timeout=5000):
        r.start(lambda reporter: gate.wait(5) and "posted", cancellable=False)
        assert not r.cancel() and not r.reporter.cancelled()
        with pytest.raises(RuntimeError):
            r.start(service, 1)
        gate.set()


def test_busy_signal(qtbot):
    r = TaskRunner()
    states = []
    r.busy.connect(states.append)
    with qtbot.waitSignal(r.finished, timeout=5000):
        r.start(service, 1)
    assert states == [True, False]
