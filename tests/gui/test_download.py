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


def test_setup_fits_a_narrow_window(window, setup, qtbot):
    """Section chips and names wrap; nothing forces the page wider than the window."""
    from PySide6.QtWidgets import QBoxLayout
    v = setup
    v.picker.section_buttons[11].setChecked(True)
    v.picker.section_buttons[12].setChecked(True)
    v.picker.fold.setChecked(True)
    window.resize(1000, 800)
    window.show()
    qtbot.waitExposed(window)
    assert v.cols.direction() == QBoxLayout.TopToBottom          # view is under 900 px
    inner = v.area.widget()
    assert inner.minimumSizeHint().width() <= v.area.viewport().width()
    for layout in (v.picker.chips, v.picker.people):
        assert layout.minimumSize().width() < 400
    window.resize(1500, 900)
    qtbot.wait(50)
    assert v.cols.direction() == QBoxLayout.LeftToRight


def test_one_bordered_bar_fills_with_progress(window, setup, qtbot, monkeypatch):
    """One overall bar (a border, filled by percent) plus a small per-student bar."""
    from painter.events import Stage, StudentStart
    from painter.gui.views.download_run import PERMILLE, overall_fraction

    def fake_download(canvas, req, reporter):
        reporter.event(Stage("Downloading A", total=4, step=1, steps=1))
        reporter.event(StudentStart("Doe, Jane", 2, 1, 2))
        for n in (1, 2):
            reporter.event(ItemDone("file", f"f{n}.pdf", "downloaded", "Doe, Jane"))
        return DownloadResult([], 0, [])
    monkeypatch.setattr("painter.gui.views.download_run.download_submissions", fake_download)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        window.go("download_run", request=setup.request(), expected=4)
    qtbot.wait(50)
    assert run.student_bar.maximum() == 2 and run.student_bar.value() == 2
    assert run.student_text.text().startswith("Doe, Jane") and "2 of 2 files" in run.student_text.text()
    assert run.overall.value() == PERMILLE // 2 and run.overall.format() == "%p%"
    assert run.big.text() == "2" and run.of.text() == "of about 4 files"
    # the estimate grows when Canvas has more than counted; stage-only when no count
    assert overall_fraction(6, 0, 8, 4, 1, 1, 6) == (0.75, 8)
    assert overall_fraction(3, 0, 4, None, 2, 4, 3) == (0.4375, None)


def test_folder_per_section_is_a_layout_option_on_by_default(setup):
    v = setup
    assert v.by_section.isChecked() and v.by_section.parent() is v.flat.parent()
    assert v.layout_preview.text() == "Assignment › Section › Student › files"
    v.flat.setChecked(True)
    assert v.layout_preview.text().startswith("Assignment › Section › files")
    v.by_section.setChecked(False)
    assert v.layout_preview.text().startswith("Assignment › files")
    assert not v.request().by_section and v.request().flat
    assert all(w is not v.by_section for w in v.more_box.findChildren(type(v.by_section)))
