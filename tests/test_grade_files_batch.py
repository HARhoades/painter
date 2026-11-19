"""Blank grade files for several assignments and sections; finding them again;
the finished-download report."""
from pathlib import Path

import pytest

from painter.domain.run_report import build_report, late_minutes
from painter.errors import Cancelled, InvalidInput
from painter.events import RecordingReporter
from painter.services.grade_files import (
    GradeFilesBatch, batch_labels, find_grade_files, make_grade_files_for, parse_grade_file,
)


def _canvas():
    from conftest import BASE
    from painter.canvas.client import Canvas
    return Canvas(BASE, "test-token")


def test_one_file_per_section_per_assignment(fake_canvas, tmp_path):
    out = tmp_path / "grade-files" / "AI105"
    res = make_grade_files_for(_canvas(), GradeFilesBatch(100, out, (7001, 7002), (11, 12)))
    names = sorted(p.name for p in res.written)
    assert len(names) == 4 and res.kept == []
    files = {p.name: parse_grade_file(p) for p in res.written}
    assert {(f.assignment_id, f.section_id) for f in files.values()} == {
        (7001, 11), (7001, 12), (7002, 11), (7002, 12)}
    a2 = next(f for f in files.values() if f.assignment_id == 7001 and f.section_id == 12)
    assert a2.blank_entries == 2 and a2.entries == []          # Rick and Ana, blank


def test_existing_files_are_kept_unless_replaced(fake_canvas, tmp_path):
    req = GradeFilesBatch(100, tmp_path, (7001,), (11,))
    first = make_grade_files_for(_canvas(), req).written[0]
    first.write_text(first.read_text().replace("grade=", "grade=9", 1))
    again = make_grade_files_for(_canvas(), req)
    assert again.written == [] and again.kept == [first]
    assert "grade=9" in first.read_text()
    forced = make_grade_files_for(_canvas(), GradeFilesBatch(100, tmp_path, (7001,), (11,), True))
    assert forced.written == [first] and "grade=9" not in first.read_text()


def test_nothing_chosen_or_gone_is_said_plainly(fake_canvas, tmp_path):
    with pytest.raises(InvalidInput, match="assignment"):
        make_grade_files_for(_canvas(), GradeFilesBatch(100, tmp_path, (), (11,)))
    with pytest.raises(InvalidInput, match="section"):
        make_grade_files_for(_canvas(), GradeFilesBatch(100, tmp_path, (7001,), ()))
    with pytest.raises(InvalidInput, match="no longer"):
        make_grade_files_for(_canvas(), GradeFilesBatch(100, tmp_path, (9999,), (11,)))
    with pytest.raises(InvalidInput, match="no longer"):
        make_grade_files_for(_canvas(), GradeFilesBatch(100, tmp_path, (7001,), (77,)))


def test_stop_between_assignments(fake_canvas, tmp_path):
    with pytest.raises(Cancelled) as err:
        make_grade_files_for(_canvas(), GradeFilesBatch(100, tmp_path, (7001, 7002), (11,)),
                             RecordingReporter(cancel_after=1))
    assert len(err.value.result.written) <= 1


def test_labels_stay_apart_when_names_start_alike():
    got = batch_labels([{"id": 1, "name": "DATE Scenario"}, {"id": 2, "name": "DATE Review"},
                        {"id": 3, "name": "Quiz"}])
    assert got == {1: "DATE-Scenario", 2: "DATE-Review", 3: "Quiz"}
    assert batch_labels([{"id": 5, "name": ""}])[5] == "5"


def test_chosen_base_names_win_and_never_collide():
    a = [{"id": 1, "name": "DATE Scenario"}, {"id": 2, "name": "Quiz"}]
    assert batch_labels(a, {1: "Lab one"}) == {1: "Lab-one", 2: "Quiz"}
    assert batch_labels(a, {1: "quiz"}) == {1: "quiz", 2: "Quiz-2"}
    assert batch_labels(a, {1: "   "})[1] == "DATE-Scenario"


def test_find_grade_files_newest_first(tmp_path):
    assert find_grade_files(tmp_path / "none") == []
    import os
    (tmp_path / "AI105").mkdir()
    old, new = tmp_path / "AI105" / "a.txt", tmp_path / "b.txt"
    old.write_text("x"), new.write_text("y")
    (tmp_path / "notes.md").write_text("z")
    os.utime(old, (1, 1))
    assert find_grade_files(tmp_path) == [new, old]


# ---- the finished-download report ----
def _row(aid, uid, attempt=1, late_by="", status="downloaded", policy=""):
    return {"assignment": f"A{aid}", "assignment_id": aid, "student": f"S{uid}",
            "user_id": uid, "section": "A1-8", "submitted_at": "2026-09-01 09:00",
            "attempt": attempt, "late": bool(late_by), "late_by": late_by,
            "late_policy_status": policy, "status": status, "score": 9.5}


def test_report_groups_files_by_student_and_ranks_lateness():
    rows = [_row(1, 5, 2, "1d 2h"), _row(1, 5, 2, "1d 2h", "failed: 404"),
            _row(1, 6, 1, "15m"), _row(1, 7, 3), _row(2, 5, 1, "", policy="excused")]
    rep = build_report(rows)
    assert len(rep.students) == 4
    s5 = next(s for s in rep.students if s.user_id == 5 and s.assignment_id == 1)
    assert (s5.files, s5.failed, s5.attempts, s5.late_by) == (2, 1, 2, "1d 2h")
    assert [s.user_id for s in rep.late] == [5, 6]
    a1 = next(a for a in rep.assignments if a.assignment_id == 1)
    assert (a1.students, a1.files, a1.late, a1.resubmitted, a1.latest_late) == \
        (3, 4, 2, 2, "1d 2h")
    assert next(a for a in rep.assignments if a.assignment_id == 2).excused == 1


def test_late_minutes():
    assert late_minutes("2d 3h 14m") == 2 * 1440 + 3 * 60 + 14
    assert late_minutes("<1m") == 0 and late_minutes("") == 0
