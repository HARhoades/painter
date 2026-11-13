"""Download: choose, run, finish (phase 5, steps 10-11)."""
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from conftest import connect_window  # noqa: E402
from painter.errors import Cancelled  # noqa: E402
from painter.events import ItemDone  # noqa: E402
from painter.services.submissions import DownloadResult  # noqa: E402


@pytest.fixture
def setup(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)            # AI105
    v = window.views["download_setup"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("download_setup")
    v.folder.set_path(str(tmp_path / "out"))
    return v


def tick(v, aid):
    for r in range(v.table.rowCount()):
        it = v.table.item(r, 0)
        if it.data(Qt.UserRole) == aid:
            it.setCheckState(Qt.Checked)


def test_setup_lists_assignments_and_sections(setup):
    v = setup
    assert v.table.rowCount() == 2
    assert sorted(b._label for b in v.picker.section_buttons.values()) == ["A1-8  (1)", "A2-8  (2)"]
    assert v.missing() == "Pick at least one assignment."


def test_count_runs_in_the_background(setup, qtbot):
    v = setup
    v.picker.section_buttons[12].setChecked(True)          # A2-8: Rick and Ana
    with qtbot.waitSignal(v.counter.finished, timeout=5000):
        tick(v, 7001)
    assert v.count.files == 1 and "1</b> file" in v.summary_text.text()
    assert v.table.item(0, 2).text() == "1 submitted"


def test_leave_one_out_and_add_one_by_name(setup):
    v, p = setup, setup.picker
    p.section_buttons[12].setChecked(True)
    p.fold.setChecked(True)
    names = [p.people.itemAt(i).widget() for i in range(p.people.count())]
    ana = next(b for b in names if "De La Cruz" in b.text())
    ana.setChecked(True)
    assert ana.text().startswith("✕") and "1 left out" in p.fold.text()
    p.search.setText("jdoe2")
    p._add_typed()
    sel = p.selection()
    assert sel.sections == ("12",) and sel.students == ("501",) and sel.exclude == ("503",)
    assert p.student_ids() == {501, 502}


def test_request_carries_the_options(setup):
    v = setup
    tick(v, 7001)
    v.picker.section_buttons[11].setChecked(True)
    v.flat.setChecked(True)
    v.keep_archives.setChecked(True)
    req = v.request()
    assert req.flat and not req.extract and req.assignment_ids == (7001,)
    assert req.tz == "America/New_York"


def test_full_download_then_done_screen(window, setup, qtbot, tmp_path):
    v = setup
    tick(v, 7001)
    v.picker.section_buttons[11].setChecked(True)
    v.picker.section_buttons[12].setChecked(True)
    with qtbot.waitSignal(window.runner.finished, timeout=10000):
        v.start()
        assert window.current is window.views["download_run"]
        assert not window.nav["grades"].isEnabled()
    done = window.views["download_done"]
    assert window.current is done
    assert done.h1.text() == "Finished"
    assert (tmp_path / "out" / "manifest.csv").exists()
    run = window.views["download_run"]
    assert run.table.rowCount() == 2 and "2 downloaded" in run.files_head.text()
    assert window.nav["grades"].isEnabled()
    assert window.session.settings.options["flat"] is False


def test_failed_file_is_listed(window, setup, courses, qtbot):
    del courses.file_bodies["/f/1"]                        # Jane's essay: 404
    v = setup
    tick(v, 7001)
    v.picker.section_buttons[11].setChecked(True)
    v.picker.section_buttons[12].setChecked(True)
    with qtbot.waitSignal(window.runner.finished, timeout=10000):
        v.start()
    done = window.views["download_done"]
    assert done.h1.text() == "Finished, with 1 file to look at"
    assert done.problems.isVisible() or not done.problems.isHidden()
    assert done.again.text() == "↻  Try the 1 again"


def test_stop_shows_what_was_done(window, setup, qtbot, monkeypatch):
    gate = threading.Event()

    def fake_download(canvas, req, reporter):
        reporter.event(ItemDone("file", "essay.pdf", "downloaded", "Doe, Jane"))
        gate.wait(5)
        assert reporter.cancelled()
        raise Cancelled("stopped", DownloadResult(
            [{"status": "downloaded", "user_id": 501, "assignment_id": 7001}], 0, []))
    monkeypatch.setattr("painter.gui.views.download_run.download_submissions", fake_download)
    v = setup
    tick(v, 7001)
    v.picker.section_buttons[11].setChecked(True)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.cancelled, timeout=5000):
        v.start()
        run.stop()
        assert run.stop_btn.text() == "Stopping after this file…"
        gate.set()
    done = window.views["download_done"]
    assert done.h1.text() == "Stopped: 1 file downloaded before you stopped"
