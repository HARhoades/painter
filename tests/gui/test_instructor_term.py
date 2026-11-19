"""Sections by instructor; academic year and semester for grade files."""
import json

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from conftest import connect_window  # noqa: E402
from painter.gui.section_filter import NOBODY, instructor_names  # noqa: E402


def test_instructor_names_sorted_with_no_instructor_last():
    assert instructor_names({1: ["Smith"], 2: ["rhoades", "Smith"]}, [1, 2, 3]) == \
        ["rhoades", "Smith", NOBODY]
    assert instructor_names({}, [1, 2]) == []                 # nothing known: no filter


@pytest.fixture
def make(window, qtbot):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["grade_files_make"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("grade_files_make")
    return v


@pytest.fixture
def setup(window, qtbot):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["download_setup"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("download_setup")
    return v


def test_download_filter_and_select_one_instructors_sections(setup):
    p = setup.picker
    assert p.who.combo.isVisibleTo(setup)
    assert [p.who.combo.itemText(i) for i in range(p.who.combo.count())] == \
        ["All instructors", "Rhoades", "Smith"]
    p.who.choose("Smith")
    assert p.section_buttons[12].isVisibleTo(p) and not p.section_buttons[11].isVisibleTo(p)
    assert p.all_btn.text() == "Select all for Smith"
    p.all_btn.click()
    assert p.chosen_sections() == [12] and p.all_btn.text() == "Clear all for Smith"
    p.who.choose("Rhoades")
    assert "1 chosen section not shown" == p.who.note.text()
    p.all_btn.click()
    assert sorted(p.chosen_sections()) == [11, 12]
    assert p.who.note.text() == "1 chosen section not shown"        # Smith's, still chosen
    p.who.choose(None)
    assert p.all_btn.text() == "Clear all"


def test_instructors_are_cached_with_the_roster(setup):
    s = setup.session
    data = s.cache.read("rosters", s.cache_key(100)).data
    assert data["instructors"] == {"11": ["Rhoades"], "12": ["Smith"]}


def test_no_filter_when_canvas_wont_list_instructors(window, qtbot, monkeypatch):
    from painter.errors import CanvasHTTPError

    def refuse(canvas, course_id):
        raise CanvasHTTPError("403 Forbidden")
    monkeypatch.setattr("painter.gui.views.download_setup.section_instructors", refuse)
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["download_setup"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("download_setup")
    assert v.picker.roster is not None and not v.picker.who.combo.isVisibleTo(v)
    assert v.picker.who.search.isVisibleTo(v)                  # search still there
    assert v.picker.all_btn.text() == "Select all"


def test_make_filters_by_instructor(make):
    v = make
    v.who.choose("Rhoades")
    v.s_all.click()
    assert v.chosen_sections() == [11]
    assert "Rhoades" in v.section_buttons[11].text()


def test_term_comes_from_the_course_name(make):
    v = make
    assert (v.ay.text(), v.term.text()) == ("27", "1") and v.term_ok()
    assert "From the course term “AY27-1”" in v.term_note.text()
    assert "A1-DATE_Grading-27-1.txt" in v.term_note.text()


def test_term_is_required_when_the_name_says_nothing(window, make, qtbot, monkeypatch):
    v = make
    course = v.session.course
    from dataclasses import replace
    monkeypatch.setattr(v.session, "course", replace(course, term="Fall 2026"))
    v.enter()
    assert v.ay.text() == "" and not v.term_ok()
    assert "can't read these" in v.term_note.text() and "--ay 27 --term 1" in v.term_note.text()
    v.a_all.click()
    v.s_all.click()
    assert not v.make_btn.isEnabled()
    assert v.missing().startswith("Enter the academic year")
    v.ay.setText("28")
    v.ay.textEdited.emit("28")
    v.term.setText("2")
    v.term.textEdited.emit("2")
    assert v.term_ok() and v.make_btn.isEnabled()
    saved = json.loads(v.session.settings_path.read_text())["course_terms"]
    assert saved == {"100": {"ay": "28", "term": "2"}}
    v.ay.setText("")
    v.enter()                                              # remembered for this course
    assert (v.ay.text(), v.term.text()) == ("28", "2")
    with qtbot.waitSignal(v.maker.finished, timeout=5000):
        v.make()
    names = sorted(p.name for p in v.folder().glob("*.txt"))
    assert names and all(n.endswith("_Grading-28-2.txt") for n in names)


def test_typed_term_overrides_the_name(make):
    v = make
    v.term.setText("2")
    v.term.textEdited.emit("2")
    assert "Typed in for this course" in v.term_note.text()
    v.enter()
    assert v.term.text() == "2"


def test_a_disabled_main_button_looks_disabled(make, qtbot):
    v = make
    v.show()
    assert not v.make_btn.isEnabled()                      # nothing chosen yet
    off = v.make_btn.grab().toImage().pixelColor(6, v.make_btn.height() // 2).name()
    v.a_all.click()
    v.s_all.click()
    assert v.make_btn.isEnabled()
    on = v.make_btn.grab().toImage().pixelColor(6, v.make_btn.height() // 2).name()
    assert off != on
