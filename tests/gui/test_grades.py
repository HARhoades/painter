"""Grades: pick, review, confirm, result, post again (phase 5, steps 12-13)."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from conftest import connect_window  # noqa: E402
from golden.scenarios import GRADES  # noqa: E402


@pytest.fixture
def pick(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    window.go("grades_pick")
    return window.views["grades_pick"]


def gfile(tmp_path, text=GRADES, name="A2-DATE_Grading-27-1.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def check(window, pick, qtbot):
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        pick.check()
    return window.views["grades_review"]


def test_unreadable_file_blocks_checking(pick, tmp_path):
    good = gfile(tmp_path)
    bad = gfile(tmp_path, GRADES.replace("grade=8.5", "grade=8.5\ngrade=9"), "A3.txt")
    pick.add([str(good), str(bad)])
    assert pick.count.text() == "2 files"
    pick.check()
    assert "Remove or fix A3.txt first" in pick.banner.text.text()
    pick.remove(bad)
    assert pick.missing() == ""


def test_review_shows_a_card_per_file_and_warnings(window, pick, qtbot, tmp_path):
    pick.add([str(gfile(tmp_path))])
    review = check(window, pick, qtbot)
    assert window.current is review and review.cards.count() == 1
    assert review.post_btn.text() == "Post 2 updates…" and review.post_btn.isVisibleTo(review)
    card = review.cards.itemAt(0).widget()
    texts = [w.text() for row in card.rows for w in row]
    assert "Already on Canvas, not re-sent" in texts           # Rick's comment is there already
    assert any("EXCUSED" in t for t in texts)


def test_errors_block_posting(window, pick, qtbot, tmp_path):
    pick.add([str(gfile(tmp_path, GRADES.replace("id=502", "id=999")))])
    review = check(window, pick, qtbot)
    assert "error" in review.errors.title.text() and not review.post_btn.isVisibleTo(review)
    review.post()
    assert window.current is review


def test_confirm_post_verify(window, pick, qtbot, tmp_path, courses):
    pick.add([str(gfile(tmp_path))])
    review = check(window, pick, qtbot)
    seen = []
    review.confirm = lambda parent, plans: seen.append(plans.total) or True
    result = window.views["grades_result"]
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        review.post()
    assert seen == [2] and window.current is result
    assert result.h1.text() == "2 of 2 updates are on Canvas"
    assert result.banner.title.text() == "Every update is on Canvas"
    assert list(tmp_path.glob("grade_post_log_*.csv"))
    assert courses.posted_forms


def test_cancelled_confirm_posts_nothing(window, pick, qtbot, tmp_path, courses):
    pick.add([str(gfile(tmp_path))])
    review = check(window, pick, qtbot)
    review.confirm = lambda parent, plans: False
    review.post()
    assert window.current is review and not courses.posted_forms


def test_post_again_only_the_failed_row(window, pick, qtbot, tmp_path, courses):
    real, dropped = courses._apply_grades, []

    def lose_ana_comment(aid, form):
        if not dropped:
            dropped.append(form.pop("grade_data[503][text_comment]", None))
        real(aid, form)
    courses._apply_grades = lose_ana_comment
    pick.add([str(gfile(tmp_path))])
    review = check(window, pick, qtbot)
    review.confirm = lambda parent, plans: True
    result = window.views["grades_result"]
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        review.post()
    assert result.h1.text() == "1 of 2 updates are on Canvas"
    assert "1 update failed" in result.banner.title.text()
    asked = []
    result.confirm = lambda parent, plans: asked.append([i.user_id for p in plans.plans
                                                         for i in p.to_send]) or True
    with qtbot.waitSignal(window.runner.finished, timeout=5000):      # the re-plan
        result.post_again(None)
    qtbot.waitUntil(lambda: not window.runner.running and result._phase is None, timeout=5000)
    assert asked == [[503]]
    assert result.h1.text() == "1 of 1 update is on Canvas"
    assert len(courses.posted_forms) == 2
