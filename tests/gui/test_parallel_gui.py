"""Phase 7 in the window: the worker-count setting and one bar per assignment."""
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from conftest import connect_window  # noqa: E402
from painter.config import DEFAULT_WORKERS, load_settings  # noqa: E402
from painter.errors import Cancelled  # noqa: E402
from painter.events import AssignmentProgress, ItemDone, Stage  # noqa: E402
from painter.gui.views.download_run import assignment_caption  # noqa: E402
from painter.services.submissions import DownloadResult  # noqa: E402


@pytest.fixture
def setup(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["download_setup"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("download_setup")
    v.folder.set_path(str(tmp_path / "out"))
    return v


def tick(v, *aids):
    for r in range(v.table.rowCount()):
        it = v.table.item(r, 0)
        if it.data(Qt.UserRole) in aids:
            it.setCheckState(Qt.Checked)


def test_settings_card_is_folded_and_saves_at_once(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.go("connect")
    card = window.views["connect"].download_prefs
    assert card.workers.value() == DEFAULT_WORKERS == 4
    assert card.box.isHidden()                             # under "Advanced"
    card.fold.setChecked(True)
    assert not card.box.isHidden()
    card.workers.setValue(2)
    assert window.session.settings.download_workers == 2
    assert load_settings(tmp_path / "settings.json").download_workers == 2
    assert card.workers.maximum() == 8 and card.workers.minimum() == 1


def test_request_takes_the_setting_at_the_time_of_download(window, setup):
    tick(setup, 7001)
    assert setup.request().workers == 4
    window.session.settings.download_workers = 1
    assert setup.request().workers == 1


def test_real_download_shows_a_bar_per_assignment(window, setup, qtbot):
    tick(setup, 7001, 7002)
    setup.picker.section_buttons[11].setChecked(True)
    setup.picker.section_buttons[12].setChecked(True)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.finished, timeout=10000):
        setup.start()
        assert not window.settings_btn.isEnabled()         # no Settings while running
    rows = run.assignments
    assert set(rows.rows) == {7001, 7002}
    assert rows.caption(7001) == "✓  2 files"
    assert rows.caption(7002) == "no files"
    assert rows.bar(7001).value() == rows.bar(7001).maximum() == 2
    assert run.h1.text() == "Downloading 2 assignments · 4 at a time"
    assert run.student_bar.isHidden()                       # several students at once


def test_rows_follow_each_state_and_a_stop(window, setup, qtbot, monkeypatch):
    gate = threading.Event()

    def fake_download(canvas, req, reporter):
        reporter.event(Stage("Downloading 3 assignments · 4 at a time"))
        for aid in (1, 2, 3):
            reporter.event(AssignmentProgress(aid, f"A{aid}", "waiting"))
        reporter.event(AssignmentProgress(1, "A1", "downloading", 3, 10, 1))
        reporter.event(AssignmentProgress(2, "A2", "listing"))
        reporter.event(ItemDone("file", "x.pdf", "downloaded", "Doe, Jane"))
        gate.wait(5)
        reporter.event(AssignmentProgress(1, "A1", "stopped", 3, 10, 1))
        reporter.event(AssignmentProgress(2, "A2", "stopped"))
        reporter.event(AssignmentProgress(3, "A3", "stopped"))
        raise Cancelled("stopped", DownloadResult([], 1, []))
    monkeypatch.setattr("painter.gui.views.download_run.download_submissions", fake_download)
    tick(setup, 7001)
    setup.picker.section_buttons[11].setChecked(True)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.cancelled, timeout=5000):
        setup.start()
        qtbot.waitUntil(lambda: 2 in run.assignments.rows and
                        run.assignments.caption(2) == "listing submissions…", timeout=3000)
        assert run.assignments.caption(1) == "3 of 10 files · 1 failed"
        assert run.assignments.caption(3) == "waiting"
        assert run.assignments.bar(2).maximum() == 0         # busy while listing
        assert run.assignments.rows[1][2].property("tone") == "bad"
        run.stop()
        gate.set()
    # the done screen took over; the rows kept their final words
    assert run.assignments.caption(1) == "stopped at 3 of 10 · 1 failed"
    assert run.assignments.caption(2) == "stopped before it started"


def test_captions():
    c = lambda **kw: assignment_caption(AssignmentProgress(1, "A", **kw))
    assert c(state="done", done=5, total=5) == "✓  5 files"
    assert c(state="done", done=1, total=1) == "✓  1 file"
    assert c(state="done", done=5, total=5, failed=2) == "3 of 5 · 2 failed"
    assert c(state="downloading", done=0, total=4) == "0 of 4 files"
