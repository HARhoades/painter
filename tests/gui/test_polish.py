"""Closing during a run, error wording, keyboard reach (phase 5, step 14)."""
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
import requests  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox, QPushButton  # noqa: E402

from conftest import connect_window  # noqa: E402
from painter.errors import (  # noqa: E402
    AuthFailed, CanvasUnavailable, Cancelled, Forbidden, InvalidInput, MissingDependency, NotFound,
)
from painter.gui.problems import describe  # noqa: E402


@pytest.mark.parametrize("exc, title", [
    (AuthFailed("401"), "Canvas didn't accept your token"),
    (Forbidden("403"), "Canvas says you don't have permission for this"),
    (NotFound("404"), "Canvas couldn't find that"),
    (CanvasUnavailable("503"), "Canvas can't be reached right now"),
    (requests.ConnectionError("dns"), "Canvas can't be reached right now"),
    (InvalidInput("--base-url must be https"), "That can't be used"),
    (MissingDependency("openpyxl"), "Something is missing on this computer"),
    (PermissionError("locked"), "A file couldn't be read or written"),
])
def test_every_error_type_has_words(exc, title):
    p = describe(exc)
    assert p.title == title and p.body
    assert "--base-url" not in p.body


def test_unknown_error_writes_a_crash_report(monkeypatch, tmp_path):
    monkeypatch.setattr("painter.crash.app_data_dir", lambda: tmp_path)
    p = describe(ZeroDivisionError("bad sum"))
    assert p.title == "Something unexpected went wrong" and p.details.exists()
    assert "ZeroDivisionError" in p.details.read_text(encoding="utf-8")
    assert describe(AuthFailed("x")).settings


def slow_download(gate):
    def run(canvas, req, reporter):
        gate.wait(5)
        raise Cancelled("stopped", None) if reporter.cancelled() else AssertionError
    return run


@pytest.mark.parametrize("answer", [QMessageBox.Yes, QMessageBox.No])
def test_closing_during_a_run_asks(window, qtbot, monkeypatch, answer):
    connect_window(window, qtbot)
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or answer)
    gate = threading.Event()
    window.runner.start(slow_download(gate))
    if answer == QMessageBox.Yes:
        threading.Timer(0.2, gate.set).start()
    closed = window.close()
    assert asked and "Stop it and close?" in asked[0]
    assert closed is (answer == QMessageBox.Yes)
    if answer == QMessageBox.No:
        assert window.runner.running
        gate.set()
        window.runner.wait(5)
    else:
        assert window.runner.reporter.cancelled() and not window.runner.running


def test_closing_while_posting_waits_for_the_file(window, qtbot, monkeypatch):
    connect_window(window, qtbot)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    gate = threading.Event()
    window.runner.start(lambda reporter: gate.wait(5), cancellable=False)
    threading.Timer(0.2, gate.set).start()
    assert window.close()
    assert "Grades are being posted" in asked[0] and not window.runner.reporter.cancelled()


def test_every_button_is_reachable_by_keyboard(window, qtbot):
    connect_window(window, qtbot)
    for view in window.views.values():
        for b in view.findChildren(QPushButton):
            assert b.focusPolicy() & Qt.TabFocus, (view.name, b.text())
