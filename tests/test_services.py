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
    # per file, within the assignment's stage
    assert [p[:2] for p in rep.progress_events] == [(0, 2), (1, 2), (2, 2)]
    from painter.events import ItemDone, Stage
    assert rep.of(Stage) == [Stage("Downloading DATE Scenario", total=2, step=1, steps=1)]
    assert [(e.key, e.status) for e in rep.of(ItemDone)] == [
        ("essay.pdf", "downloaded"), ("analysis.zip", "downloaded")]
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


def test_browser_uploads_dry_run_and_missing_playwright(canvas, fake_canvas, tmp_path, capsys):
    from golden.scenarios import add_new_quiz
    from painter.errors import MissingDependency
    from painter.services.quiz_uploads import (
        UPLOADS_DONE, BrowserUploadsRequest, browser_quiz_uploads,
    )
    add_new_quiz(fake_canvas)
    rep = RecordingReporter()
    res = browser_quiz_uploads(canvas, BrowserUploadsRequest(
        100, (7003,), tmp_path, dry_run=True), rep)
    assert res.outcome == UPLOADS_DONE
    assert "3 submitted student(s) to visit." in rep.text("info")
    with pytest.raises(MissingDependency):          # Playwright is not in the test env
        browser_quiz_uploads(canvas, BrowserUploadsRequest(100, (7003,), tmp_path, limit=1))
    assert capsys.readouterr() == ("", "")


# ---- cancelling part-way still leaves a record of what was done ----------------
A1_GRADES = """\
[ASSIGNMENT]
title=DATE Scenario
id=7001

[SECTION]
title=A1-8
instructor=Rhoades
id=11

[STUDENT]
name=Doe, Jane
id=501
grade=9
comments=
"""


def test_cancel_between_grade_files_still_writes_the_post_log(canvas, fake_canvas, tmp_path):
    from datetime import datetime
    from painter.errors import Cancelled
    from painter.services.grading import plan_grades, post_grade_plans
    a1 = tmp_path / "A1.txt"
    a1.write_text(A1_GRADES, encoding="utf-8")
    plans = plan_grades(canvas, [a1, _grades(tmp_path)])
    assert not plans.errors and len(plans.plans) == 2
    with pytest.raises(Cancelled, match="stopped before posting A2.txt") as exc:
        post_grade_plans(canvas, plans, tmp_path / "logs", datetime(2026, 11, 12),
                         RecordingReporter(cancel_after=1))
    assert len(fake_canvas.posted_forms) == 1            # A1 went out, A2 did not
    res = exc.value.result
    assert [r["student"] for r in res.rows] == ["Doe, Jane"]
    assert res.log_path is not None and res.log_path.exists()


def test_cancel_before_any_grade_file_writes_no_log(canvas, fake_canvas, tmp_path):
    from datetime import datetime
    from painter.errors import Cancelled
    from painter.services.grading import plan_grades, post_grade_plans
    plans = plan_grades(canvas, [_grades(tmp_path)])
    with pytest.raises(Cancelled) as exc:
        post_grade_plans(canvas, plans, tmp_path / "logs", datetime.now(),
                         RecordingReporter(cancel_after=0))
    assert exc.value.result.rows == [] and exc.value.result.log_path is None
    assert not (tmp_path / "logs").exists() and fake_canvas.posted_forms == []


def test_cancel_during_organize_still_writes_its_log(tmp_path):
    from golden.scenarios import make_tree, write_roster
    from painter.errors import Cancelled
    from painter.services.organize import OrganizeRequest, execute_organize, plan_organize
    src = tmp_path / "A"
    make_tree(src)
    plan = plan_organize(OrganizeRequest(src, write_roster(tmp_path / "roster.csv")))
    with pytest.raises(Cancelled, match="log written") as exc:
        execute_organize(plan, RecordingReporter(cancel_after=1))
    res = exc.value.result
    assert res.done == 1 and res.log_path.exists()
    logged = res.log_path.read_text(encoding="utf-8-sig")
    assert logged.count("moved") == 1


def test_cancel_during_download_still_writes_the_manifest(canvas, tmp_path):
    from painter.errors import Cancelled
    from painter.services.submissions import DownloadRequest, download_submissions
    out = tmp_path / "o"
    with pytest.raises(Cancelled, match="manifest written") as exc:
        download_submissions(canvas, DownloadRequest(100, out, excel_log=False),
                             RecordingReporter(cancel_after=1))
    res = exc.value.result
    assert len(res.rows) == 1 and res.manifest.exists()
    assert len(res.manifest.read_text(encoding="utf-8-sig").splitlines()) == 2
    assert not list(out.rglob("*.part"))
