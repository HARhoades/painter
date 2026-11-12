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


def test_organize_plan_changes_nothing_then_execute(tmp_path, capsys):
    from golden.scenarios import make_tree, write_roster
    from painter.services.organize import OrganizeRequest, execute_organize, plan_organize
    src = tmp_path / "A"
    make_tree(src)
    roster = write_roster(tmp_path / "roster.csv")
    before = sorted(p.name for p in src.iterdir())
    plan = plan_organize(OrganizeRequest(src, roster))
    assert sorted(p.name for p in src.iterdir()) == before          # read only
    assert [i.label for i in plan.unmatched] == ["Stranger_999"]
    assert plan.counts == {"A1-8": 1, "A2-8": 1}
    rep = RecordingReporter()
    res = execute_organize(plan, rep)
    assert (res.done, res.skipped) == (2, 0) and res.log_path.exists()
    assert (src / "A1-8" / "Doe-Jane_501" / "essay.pdf").exists()
    assert capsys.readouterr() == ("", "")


def test_download_service_result_progress_and_cancel(canvas, tmp_path, capsys):
    from painter.errors import Cancelled
    from painter.services.submissions import DownloadRequest, download_submissions
    rep = RecordingReporter()
    res = download_submissions(canvas, DownloadRequest(
        100, tmp_path / "o", assignment_ids=(7001,), excel_log=False), rep)
    assert res.failures == 0 and len(res.rows) == 2 and res.manifest.exists()
    assert {r["status"] for r in res.rows} == {"downloaded"}
    assert rep.progress_events[-1][:2] == (1, 1)
    with pytest.raises(Cancelled, match="rerun to resume"):
        download_submissions(canvas, DownloadRequest(
            100, tmp_path / "c", excel_log=False), RecordingReporter(cancel_after=1))
    assert not list((tmp_path / "c").rglob("*.part"))
    assert capsys.readouterr() == ("", "")


def test_student_listing(canvas):
    from painter.domain.roster import Roster
    from painter.services.submissions import student_listing
    roster = Roster.load(canvas, 100)
    listing = student_listing(canvas, 100, roster, Selection.of(["A2"]), (7001,))
    assert [u["id"] for u in listing.users] == [503, 502] and listing.filtered


def test_quiz_export_service(canvas, fake_canvas, tmp_path, capsys):
    from golden.scenarios import add_new_quiz
    from painter.errors import InvalidInput
    from painter.services.quiz_export import EXPORTED, QuizExportRequest, export_quiz
    add_new_quiz(fake_canvas)
    dry = export_quiz(canvas, QuizExportRequest(100, (7003,), tmp_path / "d", dry_run=True))
    assert dry.outcome == EXPORTED and not (tmp_path / "d").exists()
    rep = RecordingReporter()
    res = export_quiz(canvas, QuizExportRequest(100, (7003,), tmp_path / "o",
                                                course_export=False), rep)
    assert res.outcome == EXPORTED
    assert sorted(p.name for p in res.files) == [
        "Quiz-1_new-quiz.json", "Quiz-1_qti-report.csv", "Quiz-1_qti.zip",
        "Quiz-1_student-answers.csv"]
    assert any("not the QTI" in w for w in res.warnings)
    with pytest.raises(InvalidInput, match="is not a quiz"):
        export_quiz(canvas, QuizExportRequest(100, (7001,), tmp_path / "x"))
    assert capsys.readouterr() == ("", "")
