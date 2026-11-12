"""Services called directly, as a GUI would: request in, result out,
messages through a RecordingReporter, nothing printed."""
from __future__ import annotations

import pytest

from painter.canvas.client import Canvas
from painter.domain.selection import Selection
from painter.events import RecordingReporter
from conftest import BASE


@pytest.fixture
def canvas(fake_canvas):
    return Canvas(BASE, "t")


def test_roster_export(canvas, tmp_path, capsys):
    from painter.services.roster_export import RosterExportRequest, export_roster_csv
    rep = RecordingReporter()
    res = export_roster_csv(canvas, RosterExportRequest(
        100, tmp_path / "r.csv", Selection.of(["A2"])), rep)
    assert res.students == 2 and res.extra_lines == 0
    assert {r["Student Last Name"] for r in res.rows} == {"Roe", "De La Cruz"}
    assert res.path.exists()
    assert ("warning", "Sections: A2-8") in rep.lines
    assert capsys.readouterr() == ("", "")


def test_grade_files(canvas, tmp_path, capsys):
    from painter.errors import InvalidInput
    from painter.services.grade_files import GradeFilesRequest, make_grade_files
    rep = RecordingReporter()
    res = make_grade_files(canvas, GradeFilesRequest(100, tmp_path, assignment_ids=(7001,)), rep)
    assert sorted(p.name for p in res.written) == ["A1-DATE_Grading-27-1.txt",
                                                   "A2-DATE_Grading-27-1.txt"]
    again = make_grade_files(canvas, GradeFilesRequest(100, tmp_path, assignment_ids=(7001,)))
    assert again.written == [] and len(again.kept) == 2
    with pytest.raises(InvalidInput, match="assignment-label"):
        make_grade_files(canvas, GradeFilesRequest(100, tmp_path))
    assert capsys.readouterr() == ("", "")


def _grades(tmp_path, text=None):
    from golden.scenarios import GRADES
    p = tmp_path / "A2.txt"
    p.write_text(text or GRADES, encoding="utf-8")
    return p


def test_plan_then_post_grades(canvas, fake_canvas, tmp_path, capsys):
    from datetime import datetime
    from painter.services.grading import plan_grades, post_grade_plans
    plans = plan_grades(canvas, [_grades(tmp_path)])
    assert plans.errors == [] and plans.total == 2
    assert fake_canvas.posted_forms == []                 # planning posts nothing
    rep = RecordingReporter()
    res = post_grade_plans(canvas, plans, tmp_path, datetime(2026, 11, 12), rep)
    assert res.failed == 0 and res.log_path.name == "grade_post_log_20261112_000000.csv"
    assert len(fake_canvas.posted_forms) == 1
    assert "Verified: all 2 update(s) are on Canvas." in rep.text("info")
    assert rep.progress_events[-1][:2] == (2, 2)
    assert capsys.readouterr() == ("", "")


def test_post_refuses_plans_with_errors_and_honours_cancel(canvas, fake_canvas, tmp_path):
    from datetime import datetime
    from golden.scenarios import GRADES
    from painter.errors import Cancelled, InvalidInput
    from painter.services.grading import plan_grades, post_grade_plans
    bad = plan_grades(canvas, [_grades(tmp_path, GRADES.replace("id=502", "id=999"))])
    assert bad.errors
    with pytest.raises(InvalidInput):
        post_grade_plans(canvas, bad, tmp_path, datetime.now())
    good = plan_grades(canvas, [_grades(tmp_path)])
    with pytest.raises(Cancelled):
        post_grade_plans(canvas, good, tmp_path, datetime.now(),
                         RecordingReporter(cancel_after=0))
    assert fake_canvas.posted_forms == []
