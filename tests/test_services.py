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
