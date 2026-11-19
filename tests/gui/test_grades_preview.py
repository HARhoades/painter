"""Post grades, step 2: preview each file, change grades and comments, save back."""
import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from conftest import connect_window  # noqa: E402
from golden.scenarios import GRADES  # noqa: E402
from painter.services.grade_files import parse_grade_file  # noqa: E402

BLANK = GRADES + "\n[STUDENT]\nname=Poe, Pat\nid=503\ngrade=\ncomments=\n"


class Answers:
    """Stands in for the dialogs; records what was asked."""

    def __init__(self, save=True, unsaved="save", changed="cancel"):
        self.asked, self._save, self._unsaved, self._changed = [], save, unsaved, changed

    def save(self, parent, card):
        self.asked.append("save")
        return self._save

    def unsaved(self, parent, n):
        self.asked.append(("unsaved", n))
        return self._unsaved

    def changed_on_disk(self, parent, name):
        self.asked.append(("changed", name))
        return self._changed


@pytest.fixture
def preview(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    window.go("grades_pick")
    path = tmp_path / "A2-DATE.txt"
    path.write_text(BLANK, encoding="utf-8")
    pick = window.views["grades_pick"]
    pick.add([str(path)])
    pick.check()
    v = window.views["grades_preview"]
    assert window.current is v
    v.ask = Answers()
    v.path = path
    return v


def cards(v):
    return {c.entry.name: c for c in v.cards[0].students}


def test_file_details_and_one_card_per_student(preview):
    v = preview
    card = v.cards[0]
    text = " ".join(w.text() for w in card.meta_values.values())
    assert set(card.meta_values) >= {"Last changed", "Size", "Folder"}
    for want in ("DATE Scenario · ID 7001", "A2-8 · ID 12", "Smith", "2026",
                 str(v.path.parent)):
        assert want in text
    assert list(cards(v)) == ["Roe, Rick", "De La Cruz, Ana", "Poe, Pat"]   # opened: one file
    assert cards(v)["Poe, Pat"].property("state") == "missing"
    assert "No grade or comment" in cards(v)["Poe, Pat"].state.text()
    assert cards(v)["Roe, Rick"].property("state") == ""
    assert cards(v)["De La Cruz, Ana"].comment.toPlainText() == "Excused for\nthe field exercise."


def test_save_asks_then_rewrites_only_that_student(preview):
    v = preview
    pat = cards(v)["Poe, Pat"]
    pat.grade.setText("9")
    pat.comment.setPlainText("Good recovery.\nSee me about lab 4.")
    assert pat.property("state") == "changed" and v.cards[0].save_btn.isEnabled()
    before = v.path.read_text(encoding="utf-8")
    v.cards[0].save_btn.click()
    assert v.ask.asked == ["save"]
    after = v.path.read_text(encoding="utf-8")
    assert after.startswith(before.split("[STUDENT]\nname=Poe")[0])        # rest untouched
    s = {e.name: e for e in parse_grade_file(v.path).students}
    assert (s["Poe, Pat"].grade, s["Poe, Pat"].comments) == \
        ("9", "Good recovery.\nSee me about lab 4.")
    assert not v.dirty_cards() and "Saved A2-DATE.txt" in v.banner.title.text()
    assert cards(v)["Poe, Pat"].property("state") == ""                     # rebuilt from disk
    v.win.show()
    assert all(c.isVisibleTo(v) for c in v.cards[0].students)
    assert v.cards[0].meta_values["Assignment"].isVisibleTo(v)
    assert v.cards[0].n_badge.isVisibleTo(v) and not v.cards[0].chg_badge.isVisibleTo(v)


def test_saying_no_saves_nothing(preview):
    v = preview
    v.ask = Answers(save=False)
    cards(v)["Roe, Rick"].grade.setText("7")
    before = v.path.read_text(encoding="utf-8")
    v.cards[0].save_btn.click()
    assert v.path.read_text(encoding="utf-8") == before and v.dirty_cards()


def test_the_prompt_can_be_turned_off_in_settings(preview):
    v = preview
    v.session.settings.confirm_save = False
    cards(v)["Roe, Rick"].grade.setText("7")
    v.cards[0].save_btn.click()
    assert v.ask.asked == [] and not v.dirty_cards()
    assert {e.name: e.grade for e in parse_grade_file(v.path).students}["Roe, Rick"] == "7"


def test_lines_that_would_inject_data_block_saving(preview):
    v = preview
    c = cards(v)["Roe, Rick"]
    c.comment.setPlainText("Fine work.\ngrade=100")
    assert "starts with “grade=”" in c.problem.text()
    assert not v.cards[0].save_btn.isEnabled()
    assert not v.save(v.cards[0]) and "Can't save" in v.banner.title.text()


def test_basic_grade_checks_show_on_the_card(preview):
    c = cards(preview)["Roe, Rick"]
    c.grade.setText("9o")
    assert "mixes digits and letters" in c.problem.text()


def _changed_elsewhere(path):
    text = path.read_text(encoding="utf-8").replace("grade=8.5", "grade=6")
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 3_000_000_000))


def test_changed_on_disk_can_be_reloaded(preview):
    v = preview
    v.ask = Answers(changed="reload")
    cards(v)["Poe, Pat"].grade.setText("9")
    _changed_elsewhere(v.path)
    assert not v.save(v.cards[0])
    assert v.ask.asked == ["save", ("changed", "A2-DATE.txt")]
    assert cards(v)["Roe, Rick"].grade.text() == "6" and cards(v)["Poe, Pat"].grade.text() == ""


def test_changed_on_disk_can_be_overwritten(preview):
    v = preview
    v.ask = Answers(changed="overwrite")
    cards(v)["Poe, Pat"].grade.setText("9")
    _changed_elsewhere(v.path)
    assert v.save(v.cards[0])
    s = {e.name: e.grade for e in parse_grade_file(v.path).students}
    assert s["Poe, Pat"] == "9" and s["Roe, Rick"] == "6"     # their change is kept too


def test_changed_on_disk_cancel_keeps_the_edits(preview):
    v = preview
    cards(v)["Poe, Pat"].grade.setText("9")
    _changed_elsewhere(v.path)
    assert not v.save(v.cards[0]) and v.dirty_cards()


def test_unsaved_edits_are_saved_before_review_reads_the_files(window, preview, qtbot):
    v = preview
    cards(v)["Poe, Pat"].grade.setText("9")
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        v.check()
    assert v.ask.asked == [("unsaved", 1)]
    assert {e.name: e.grade for e in parse_grade_file(v.path).students}["Poe, Pat"] == "9"
    review = window.views["grades_review"]
    assert window.current is review
    read = review.plans.plans[0].source                     # Review read the file again
    assert {e.name: e.grade for e in read.students}["Poe, Pat"] == "9"


def test_unsaved_edits_can_be_discarded_or_kept(window, preview, qtbot):
    v = preview
    v.ask = Answers(unsaved="cancel")
    cards(v)["Poe, Pat"].grade.setText("9")
    v.check()
    assert window.current is v and v.dirty_cards() and not window.runner.running
    v.ask = Answers(unsaved="discard")
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        v.check()
    assert {e.name: e.grade for e in parse_grade_file(v.path).students}["Poe, Pat"] == ""


def test_without_the_prompt_unsaved_edits_just_save(window, preview, qtbot):
    v = preview
    v.session.settings.confirm_save = False
    cards(v)["Poe, Pat"].grade.setText("9")
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        v.check()
    assert v.ask.asked == []
    assert {e.name: e.grade for e in parse_grade_file(v.path).students}["Poe, Pat"] == "9"


def test_leaving_with_unsaved_edits_asks(window, preview):
    v = preview
    v.ask = Answers(unsaved="cancel")
    cards(v)["Poe, Pat"].grade.setText("9")
    window.go("home")
    assert window.current is v and window.nav["grades"].isChecked()
    v.ask = Answers(unsaved="discard")
    window.go("home")
    assert window.current is window.views["home"]


def test_back_from_review_shows_files_changed_since(window, preview, qtbot):
    v = preview
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        v.check()
    _changed_elsewhere(v.path)
    window.go("grades_preview")
    assert cards(v)["Roe, Rick"].grade.text() == "6"


def test_overlapping_files_are_flagged(window, preview, tmp_path):
    other = tmp_path / "A2-8-DATE.txt"
    other.write_text(GRADES, encoding="utf-8")
    window.go("grades_pick")
    pick = window.views["grades_pick"]
    pick.add([str(other)])
    assert pick.overlap.isVisibleTo(pick) and "A2-DATE.txt, A2-8-DATE.txt" in pick.overlap.text.text()
    pick.check()
    assert "later file's grade replaces" in preview.overlap.text.text()
    pick.remove(other)
    assert not pick.overlap.isVisibleTo(pick)


def test_many_files_start_folded(window, preview, tmp_path):
    other = tmp_path / "A1-DATE.txt"
    other.write_text(GRADES.replace("id=12", "id=11").replace("A2-8", "A1-8"), encoding="utf-8")
    window.go("grades_pick")
    window.views["grades_pick"].add([str(other)])
    window.views["grades_pick"].check()
    assert all(not c.open and not c.students for c in preview.cards)
    preview.cards[1].toggle.click()
    assert len(preview.cards[1].students) == 2


def test_closing_the_window_with_unsaved_edits_asks(window, preview):
    v = preview
    v.ask = Answers(unsaved="cancel")
    cards(v)["Poe, Pat"].grade.setText("9")
    window.show()
    assert not window.close() and window.isVisible() and v.dirty_cards()
    v.ask = Answers(unsaved="save")
    assert window.close()
    assert {e.name: e.grade for e in parse_grade_file(v.path).students}["Poe, Pat"] == "9"
