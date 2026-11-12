"""Post again for the rows that didn't take (phase 5, step 5)."""
from datetime import datetime

from conftest import BASE
from golden.scenarios import GRADES
from painter.canvas.client import Canvas
from painter.services.grading import plan_grades, post_grade_plans, replan_failed


def test_replan_only_failed_rows_and_skip_what_landed(fake_canvas, tmp_path):
    p = tmp_path / "A2.txt"
    p.write_text(GRADES, encoding="utf-8")
    real = fake_canvas._apply_grades
    dropped = []

    def lose_ana_comment(aid, form):     # first post: Ana's excuse lands, her comment doesn't
        if not dropped:
            dropped.append(form.pop("grade_data[503][text_comment]", None))
        real(aid, form)
    fake_canvas._apply_grades = lose_ana_comment

    c = Canvas(BASE, "t")
    plans = plan_grades(c, [p])
    first = post_grade_plans(c, plans, tmp_path, datetime(2026, 1, 1))
    assert first.failed == 1 and dropped[0]

    again = replan_failed(c, plans, first)
    assert again.errors == [] and len(again.plans) == 1
    (item,) = again.plans[0].items
    assert item.user_id == 503 and "text_comment" in item.fields

    second = post_grade_plans(c, again, tmp_path, datetime(2026, 1, 1, 0, 1))
    assert second.failed == 0 and [r["user_id"] for r in second.rows] == [503]


def test_nothing_failed_means_nothing_to_replan(fake_canvas, tmp_path):
    p = tmp_path / "A2.txt"
    p.write_text(GRADES, encoding="utf-8")
    c = Canvas(BASE, "t")
    plans = plan_grades(c, [p])
    res = post_grade_plans(c, plans, tmp_path, datetime(2026, 1, 1))
    assert replan_failed(c, plans, res).plans == []
