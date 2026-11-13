"""Cache-first screens, the ↻ buttons, Select all, hover, and the Settings card."""
import json
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from conftest import connect_window  # noqa: E402


@pytest.fixture
def setup(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["download_setup"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("download_setup")
    v.folder.set_path(str(tmp_path / "out"))
    return v


def tick_all(v):
    v._select_all()


def api_calls(fake):
    return [c for c in fake.calls if c[0] == "GET"]


def test_lookup_writes_the_cache_and_tags_say_up_to_date(setup):
    v = setup
    cache = v.session.cache
    assert {"assignments", "rosters"} <= {k for k in ("assignments", "rosters")
                                          if cache.read(k, v.session.cache_key(100))}
    assert "Up to date" in v.a_tag.text.text() and "Up to date" in v.s_tag.text.text()


def test_cached_lists_show_at_once_then_are_confirmed(window, setup, qtbot, monkeypatch):
    v = setup
    window.go("home")
    v.loaded_for = None                                    # as after a restart
    old = datetime.now(timezone.utc) - timedelta(days=3)
    key = v.session.cache_key(100)
    for kind in ("assignments", "rosters"):
        e = v.session.cache.read(kind, key)
        v.session.cache.write(kind, key, e.data, old)
    started = []
    monkeypatch.setattr(v.lookup, "start", lambda *a, **k: started.append(a))
    window.go("download_setup")
    assert v.table.rowCount() == 2 and v.picker.roster is not None     # before any answer
    assert started, "a stale cache is checked with Canvas"
    assert "From" in v.a_tag.text.text() and "checking" in v.a_tag.text.text()
    assert not v.a_tag.button.isEnabled()                              # one check at a time


def test_a_fresh_cache_makes_no_request(window, setup, fake_canvas):
    window.go("home")
    v = setup
    v.loaded_for = None
    fake_canvas.calls.clear()
    window.go("download_setup")
    assert v.table.rowCount() == 2
    assert api_calls(fake_canvas) == []


def test_unreadable_cache_falls_back_to_asking_canvas(window, setup, qtbot):
    v = setup
    window.go("home")
    v.session.cache.path("assignments", v.session.cache_key(100)).write_text("{oops")
    v.loaded_for = None
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("download_setup")
    assert v.table.rowCount() == 2


def test_ticks_and_sections_survive_a_refresh(setup, qtbot):
    v = setup
    tick_all(v)
    v.picker.section_buttons[12].setChecked(True)
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        v.a_tag.refresh_requested.emit()
    assert len(v.chosen_assignments()) == 2
    assert v.picker.section_buttons[12].isChecked()


def test_a_ticked_assignment_that_disappears_blocks_start(setup, qtbot, fake_canvas):
    v = setup
    tick_all(v)
    v.picker.section_buttons[12].setChecked(True)
    fake_canvas.assignments = [a for a in fake_canvas.assignments if a["id"] != 7002]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        v.refresh_lists()
    assert 7002 in v.gone and "no longer lists" in v.missing()


def test_changing_choices_asks_canvas_nothing_once_counted(setup, qtbot, fake_canvas):
    v = setup
    tick_all(v)
    with qtbot.waitSignal(v.counter.finished, timeout=5000):
        v.picker.section_buttons[12].setChecked(True)
    qtbot.waitUntil(lambda: not v.counter.running and not v.count_timer.isActive(), timeout=5000)
    fake_canvas.calls.clear()
    v.picker.section_buttons[11].setChecked(True)
    v.picker.section_buttons[12].setChecked(False)
    v.picker.section_buttons[12].setChecked(True)
    qtbot.wait(400)
    assert api_calls(fake_canvas) == []
    assert v.count is not None and "file" in v.summary_text.text()


def test_count_refresh_button_asks_again_and_updates_the_tag(setup, qtbot, fake_canvas):
    v = setup
    tick_all(v)
    v.picker.section_buttons[12].setChecked(True)
    qtbot.waitUntil(lambda: "Up to date" in v.c_tag.text.text(), timeout=5000)
    fake_canvas.calls.clear()
    with qtbot.waitSignal(v.counter.finished, timeout=5000):
        v.c_tag.refresh_requested.emit()
    assert api_calls(fake_canvas), "the ↻ button forces a real query"
    assert "Up to date" in v.c_tag.text.text()


def test_cache_files_hold_no_scores_grades_or_comments(setup, qtbot):
    v = setup
    tick_all(v)
    v.picker.section_buttons[12].setChecked(True)
    qtbot.waitUntil(lambda: "Up to date" in v.c_tag.text.text(), timeout=5000)
    files = v.session.cache.files()
    assert len(files) == 3
    for f in files:
        blob = f.read_text(encoding="utf-8").lower()
        for word in ("score", "grade", "comment", "token"):
            assert word not in blob.replace("grading_type", ""), (f.name, word)


def test_rosters_are_their_own_file_and_folder(setup):
    v = setup
    root = v.session.cache.root
    assert (root / "rosters").is_dir() and (root / "assignments").is_dir()
    roster_file = next((root / "rosters").glob("*.json"))
    assert "Jane Doe" in roster_file.read_text(encoding="utf-8")
    assert "Jane Doe" not in next((root / "assignments").glob("*.json")).read_text(encoding="utf-8")


def test_home_tag_tracks_the_course_list(window, qtbot):
    connect_window(window, qtbot)
    home = window.views["home"]
    assert "Up to date" in home.tag.text.text()
    assert not home.tag.button.isVisibleTo(home)                # Home has its own Refresh link


# ---- Select all ----
def test_select_all_sections_toggles(setup):
    p = setup.picker
    assert p.all_btn.text() == "Select all"
    p.all_btn.click()
    assert all(b.isChecked() for b in p.section_buttons.values())
    assert p.all_btn.text() == "Clear all"
    p.all_btn.click()
    assert not any(b.isChecked() for b in p.section_buttons.values())
    assert p.all_btn.text() == "Select all"
    p.section_buttons[11].setChecked(True)
    assert p.all_btn.text() == "Select all"
    p.all_btn.click()
    assert all(b.isChecked() for b in p.section_buttons.values())
    assert p.student_ids() == {501, 502, 503}


# ---- hover ----
def test_beige_buttons_have_hover_rules(painter_qapp):
    qss = painter_qapp.styleSheet()
    for sel in ("QPushButton:hover", 'QPushButton[role="primary"]:hover',
                'QPushButton[role="link"]:hover'):
        assert sel in qss, sel


def test_hover_changes_a_buttons_colour(window, setup, qtbot):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    window.show()
    window.go("download_setup")
    chip = next(iter(setup.picker.section_buttons.values()))
    y = chip.height() // 2

    def paint():
        return chip.grab().toImage().pixelColor(6, y).name()

    QTest.mouseMove(window, QPoint(1, 1))                # somewhere else first
    qtbot.wait(30)
    before = paint()
    QTest.mouseMove(chip, QPoint(6, y))
    qtbot.waitUntil(lambda: chip.underMouse(), timeout=2000)
    assert paint() != before


# ---- Settings card ----
def test_settings_can_clear_saved_data(window, setup, monkeypatch):
    c = window.views["connect"]
    window.go("connect")
    assert setup.session.cache.files() and c.clear_btn.isEnabled()
    assert "Grades and comments are never kept" in c.data_note.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    c.clear_data()
    assert setup.session.cache.files()                       # No means no
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    c.clear_data()
    assert setup.session.cache.files() == [] and not c.clear_btn.isEnabled()


def test_nothing_in_the_cache_is_secret(setup):
    for f in setup.session.cache.files():
        json.loads(f.read_text(encoding="utf-8"))            # plain readable JSON
        assert "test-token" not in f.read_text(encoding="utf-8")
