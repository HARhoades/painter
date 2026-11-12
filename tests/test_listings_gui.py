"""Listings and counts the window needs (phase 5, steps 2-3)."""
from datetime import datetime, timezone

import pytest

from conftest import BASE, add_courses
from painter.canvas.client import Canvas
from painter.domain.selection import Selection
from painter.errors import Cancelled
from painter.events import RecordingReporter
from painter.services.courses import list_courses, whoami
from painter.services.submissions import (DownloadRequest, assignment_listing, count_files,
                                          download_submissions)


@pytest.fixture
def canvas(fake_canvas):
    add_courses(fake_canvas)
    return Canvas(BASE, "test-token")


def test_courses_teacher_and_ta_current_term_first(canvas):
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    got = list_courses(canvas, now)
    assert [(c.id, c.role, c.term_current) for c in got] == [
        (100, "Teacher", True), (200, "TA", True), (300, "Teacher", False)]
    assert got[0].sections == 2 and got[0].students == 3 and got[0].code == "AI105-27-1"


def test_whoami(canvas):
    assert whoami(canvas) == "Hunter Rhoades"


def test_assignment_listing(canvas, fake_canvas):
    fake_canvas.assignments.append({"id": 7003, "name": "Quiz 1", "is_quiz_lti_assignment": True,
                                    "submission_types": ["external_tool"], "due_at": None})
    got = assignment_listing(canvas, 100)
    assert [(a.id, a.due, a.new_quiz) for a in got] == [
        (7001, "2026-09-01 03:59", False), (7002, "", False), (7003, "", True)]


def test_count_matches_what_download_fetches(canvas, tmp_path):
    count = count_files(canvas, 100, (7001, 7002))
    assert count.per_assignment[7001].submitted == 2 and count.files == 2
    res = download_submissions(canvas, DownloadRequest(100, tmp_path, (7001, 7002), excel_log=False))
    assert len([r for r in res.rows if r.get("status", "").startswith("downloaded")]) == count.files


def test_count_with_a_selection(canvas):
    count = count_files(canvas, 100, (7001,), Selection.of(sections=["A1-8"]))
    assert count.students == 1 and count.files == 1


def test_count_can_be_cancelled_with_what_it_has(canvas):
    rep = RecordingReporter()
    calls = iter([False, True])
    rep.cancelled = lambda: next(calls)
    with pytest.raises(Cancelled) as exc:
        count_files(canvas, 100, (7001, 7002), reporter=rep)
    assert list(exc.value.result.per_assignment) == [7001]
