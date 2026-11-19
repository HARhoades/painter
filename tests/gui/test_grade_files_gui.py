"""0% at the start, the Details panel, Make grade files, and Post grades listing them."""
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from conftest import connect_window  # noqa: E402
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


# ---- progress ----
def test_bar_shows_zero_before_anything_is_known(window, setup, qtbot, monkeypatch):
    from painter.events import Stage
    from painter.gui.views.download_run import overall_fraction
    assert overall_fraction(0, 0, 0, None, 1, 1, 0) == (0.0, None)
    gate = threading.Event()

    def slow(canvas, req, reporter):
        reporter.event(Stage("Reading assignments", None, 1, 1))
        gate.wait(5)
        return DownloadResult([], 0, [])
    monkeypatch.setattr("painter.gui.views.download_run.download_submissions", slow)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.finished, timeout=8000):
        window.go("download_run", request=setup.request(), expected=None)
        qtbot.waitUntil(lambda: run.h1.text() == "Reading assignments", timeout=3000)
        assert run.overall.value() == 0
        gate.set()


# ---- Details panel ----
def test_details_panel_lists_lateness_and_attempts(window, setup, qtbot):
    v = setup
    v._select_all()
    v.picker.all_btn.click()
    with qtbot.waitSignal(window.runner.finished, timeout=10000):
        v.start()
    done = window.views["download_done"]
    d = done.details
    assert d.isVisibleTo(done) and not d.box.isVisibleTo(done)          # folded at first
    assert "1 late (longest 1d)" in d.line.text()
    assert "1 submitted more than once" in d.line.text()
    d.fold.setChecked(True)
    assert d.box.isVisibleTo(done)
    t = d.by_student
    assert t.item(0, 0).text() == "Roe, Rick" and t.item(0, 5).text() == "+1d"
    assert t.item(0, 4).text() == "2"
    d.late_only.setChecked(True)
    shown = [r for r in range(t.rowCount()) if not t.isRowHidden(r)]
    assert [t.item(r, 0).text() for r in shown] == ["Roe, Rick"]
    heads = [t.horizontalHeaderItem(c).text() for c in range(t.columnCount())]
    assert not any("score" in h.lower() or "grade" in h.lower() for h in heads)


# ---- Make grade files ----
@pytest.fixture
def make(window, qtbot):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["grade_files_make"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("grade_files_make")
    return v


def test_make_is_in_the_sidebar_now(window):
    from painter.gui.app import LATER
    assert "Make grade files" not in LATER and "gradefiles" in window.nav


def test_make_one_file_per_section_per_assignment(window, make, qtbot, tmp_path):
    v = make
    assert v.folder() == tmp_path / "grade-files" / "AI105-27-1"
    assert not v.make_btn.isEnabled() and v.missing() == "Pick at least one assignment."
    v.a_all.click()
    v.s_all.click()
    assert v.summary.text().startswith("4 files") and v.a_all.text() == "Clear all"
    with qtbot.waitSignal(v.maker.finished, timeout=5000):
        v.make()
    files = sorted(p.name for p in v.folder().glob("*.txt"))
    assert len(files) == 4
    assert "4 grade files made" in v.done.title.text() and v.post_btn.isVisibleTo(v)
    with qtbot.waitSignal(v.maker.finished, timeout=5000):
        v.make()                                           # again: nothing overwritten
    assert "0 grade files made" in v.done.title.text() and "4 already there" in v.done.text.text()


def test_make_uses_the_cache_and_keeps_choices(window, make, qtbot, fake_canvas):
    v = make
    v.s_all.click()
    window.go("home")
    fake_canvas.calls.clear()
    window.go("grade_files_make")                          # fresh: shown from memory
    assert v.table.rowCount() == 2 and len(v.chosen_sections()) == 2
    assert [c for c in fake_canvas.calls if c[0] == "GET"] == []
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        v.tag.refresh_requested.emit()
    assert len(v.chosen_sections()) == 2 and "Up to date" in v.tag.text.text()


# ---- Post grades lists them ----
def test_post_grades_lists_saved_files_and_ticks_add_them(window, make, qtbot):
    v = make
    v.a_all.click()
    v.s_all.click()
    with qtbot.waitSignal(v.maker.finished, timeout=5000):
        v.make()
    (v.session.grades_root / "Old-course").mkdir()
    (v.session.grades_root / "Old-course" / "broken.txt").write_text("[NOPE]\n")
    v.post_btn.click()
    pick = window.views["grades_pick"]
    assert window.current is pick
    assert len(pick.saved) == 5 and "Saved grade files  ·  5" == pick.saved_head.text()
    broken = next(b for p, b in pick.saved.items() if p.name == "broken.txt")
    assert not broken.isEnabled()
    first = next(p for p in pick.saved if p.parent == v.folder())
    pick.saved[first].setChecked(True)
    assert first in pick.files and pick.count.text() == "1 file"
    pick.remove(first)
    assert not pick.saved[first].isChecked() and not pick.files
    grid_text = [pick.saved_grid.itemAt(i).widget().text() for i in range(pick.saved_grid.count())]
    assert grid_text[0] == "<b>This course</b>"
    assert any("0 of 1 filled in" in t for t in grid_text)


def test_a_filled_file_from_the_folder_can_be_checked(window, make, qtbot):
    v = make
    item = v.table.item(0, 0)
    item.setCheckState(Qt.Checked)
    v.section_buttons[12].setChecked(True)
    with qtbot.waitSignal(v.maker.finished, timeout=5000):
        v.make()
    path = next(v.folder().glob("*.txt"))
    text = path.read_text(encoding="utf-8").replace("grade=", "grade=8", 1)
    path.write_text(text, encoding="utf-8")
    window.go("grades_pick")
    pick = window.views["grades_pick"]
    pick.saved[path].setChecked(True)
    assert pick.missing() == ""
    pick.check()
    preview = window.views["grades_preview"]
    assert window.current is preview and len(preview.cards) == 1
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        preview.check()
    assert window.current is window.views["grades_review"]


def test_grade_files_folder_is_ignored_by_git():
    from painter import config
    assert "grade-files" in config.IGNORED_DIRS
    assert not config.exposed_in_repo(config.default_grades_root() / "AI105" / "x.txt")
