"""Search bars over every selection list; choosing where grade files go."""
import json

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from conftest import connect_window  # noqa: E402
from painter.gui.widgets import words_match  # noqa: E402


def test_words_match_any_order_any_case():
    assert words_match("scen date", "DATE Scenario")
    assert words_match("", "anything") and words_match("  ", None)
    assert not words_match("quiz", "DATE Scenario", "2026-09-01")
    assert words_match("smith a2", "A2-8", "Smith")


@pytest.fixture
def setup(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["download_setup"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("download_setup")
    v.folder.set_path(str(tmp_path / "out"))
    return v


@pytest.fixture
def make(window, qtbot):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["grade_files_make"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("grade_files_make")
    return v


def shown_rows(table):
    return [table.item(r, 0).text() for r in range(table.rowCount()) if not table.isRowHidden(r)]


# ---- Download: assignments, sections, students ----
def test_download_assignment_search_and_select_all_shown(setup):
    v = setup
    v.a_search.setText("date")
    assert shown_rows(v.table) == ["DATE Scenario"]
    assert v.a_all.text() == "Select all shown"
    v._select_all()
    assert v.chosen_assignments() == (7001,)
    v.a_search.setText("nothing like this")
    assert v.a_note.text() == "No matches"
    v.a_search.setText("refl")
    assert v.a_note.text() == "1 chosen not shown"
    QTest.keyClick(v.a_search, Qt.Key_Escape)
    assert v.a_search.text() == "" and len(shown_rows(v.table)) == 2


def test_section_search_by_name_or_instructor(setup):
    p = setup.picker
    p.who.search.setText("a2")
    assert p.section_buttons[12].isVisibleTo(p) and not p.section_buttons[11].isVisibleTo(p)
    assert p.all_btn.text() == "Select all shown"
    p.all_btn.click()
    assert p.chosen_sections() == [12]
    p.who.search.setText("rhoades")                      # instructor names match too
    assert p.section_buttons[11].isVisibleTo(p)
    assert p.who.note.text() == "1 chosen section not shown"
    p.who.search.setText("zzz")
    assert p.who.note.text() == "No sections match" and not p.all_btn.isEnabled()


def test_student_search_inside_choose_individuals(setup, qtbot):
    p = setup.picker
    p.section_buttons[12].setChecked(True)
    p.fold.setChecked(True)
    assert p.people_search.isVisibleTo(p)
    p.people_search.setText("ana")
    names = [b.text() for b in p.people_buttons.values() if b.isVisibleTo(p)]
    assert len(names) == 1 and "Ana" in names[0]
    assert p.people_note.text() == "1 shown"
    p.people_search.setText("503")                      # by Canvas ID too
    assert sum(b.isVisibleTo(p) for b in p.people_buttons.values()) == 1
    p.people_search.setText("nobody")
    assert p.people_note.text() == "No students match"


# ---- Make grade files: search and folder ----
def test_make_search_assignments_and_sections(make):
    v = make
    v.a_search.setText("refl")
    assert shown_rows(v.table) == ["Reflection"] and v.a_all.text() == "Select all shown"
    v.a_all.click()
    assert v.chosen_assignments() == [7002]
    v.who.search.setText("a1")
    v.s_all.click()
    assert v.chosen_sections() == [11]


def test_choose_where_grade_files_go(window, make, qtbot, tmp_path):
    v = make
    assert v.folder() == v.default_folder() and not v.reset_btn.isVisibleTo(v)
    mine = tmp_path / "My grading"
    v.where.set_path(str(mine))
    assert not v.reset_btn.isHidden() and "Your folder" in v.where_note.text()
    saved = json.loads(v.session.settings_path.read_text())["course_folders"]
    assert saved == {"100": str(mine)}
    v.a_all.click()
    v.s_all.click()
    with qtbot.waitSignal(v.maker.finished, timeout=5000):
        v.make()
    assert len(list(mine.glob("*.txt"))) == 4
    window.go("home")
    window.go("grade_files_make")                        # remembered for the course
    assert v.folder() == mine
    window.go("grades_pick")
    pick = window.views["grades_pick"]
    assert len(pick.saved) == 4 and all(p.parent == mine for p in pick.saved)
    assert pick.saved_groups and "This course" in pick.saved_groups
    window.go("grade_files_make")
    v.reset_btn.click()
    assert v.folder() == v.default_folder()
    assert json.loads(v.session.settings_path.read_text())["course_folders"] == {}


def test_a_blank_folder_blocks_make(make):
    v = make
    v.a_all.click()
    v.s_all.click()
    v.where.set_path("")
    assert not v.make_btn.isEnabled() and v.missing() == "Choose a folder for the grade files."


def test_folder_inside_the_repo_warns(make):
    from painter.config import project_root
    root = project_root()
    if root is None:
        pytest.skip("not running from a checkout")
    make.where.set_path(str(root / "painter"))
    assert "could be committed" in make.where_note.text()


# ---- Post grades: search the saved files ----
def test_post_grades_search(window, make, qtbot):
    v = make
    v.a_all.click()
    v.s_all.click()
    with qtbot.waitSignal(v.maker.finished, timeout=5000):
        v.make()
    window.go("grades_pick")
    pick = window.views["grades_pick"]
    assert pick.saved_search.isVisibleTo(pick)
    pick.saved_search.setText("reflection a2")
    shown = [p for p, b in pick.saved.items() if b.isVisibleTo(pick)]
    assert len(shown) == 1 and "A2" in shown[0].name
    pick.saved[shown[0]].setChecked(True)
    pick.saved_search.setText("date")
    assert pick.saved_match.text() == "1 ticked file not shown"
    pick.saved_search.setText("zzz")
    assert pick.saved_match.text() == "No files match"
    assert not pick.saved_groups["This course"].isVisibleTo(pick)
