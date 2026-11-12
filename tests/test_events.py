"""Phase 4 part C: typed events, the queue reporter, and cancellable waits."""
from __future__ import annotations

import threading

import pytest

from painter.canvas.client import Canvas, WAIT_SLICE
from painter.errors import Cancelled
from painter.events import (
    QueueReporter, RecordingReporter, Stage, Waiting, watch,
)
from conftest import BASE, make_response


def test_wait_is_one_sleep_unless_something_can_cancel():
    c = Canvas(BASE, "t")
    slept = []
    c.sleep = slept.append
    c.wait(3.5, "pacing")
    assert slept == [3.5]                       # the command line: unchanged
    rep = RecordingReporter()
    with watch(c, rep):
        c.wait(2.5, "pacing", percent=40)
    assert slept[1:] == [WAIT_SLICE, WAIT_SLICE, 0.5]
    assert rep.events == [Waiting("pacing", 2.5, 40)]
    assert c.on_wait is None and c.should_stop is None   # restored


def test_cancel_cuts_a_wait_short():
    c = Canvas(BASE, "t")
    slept = []
    c.sleep = slept.append
    with watch(c, RecordingReporter(cancel_after=2)):
        with pytest.raises(Cancelled, match="stopped while Canvas is busy"):
            c.wait(60, "Canvas is busy")
    assert len(slept) == 2                      # not 60 seconds


def test_pause_after_a_write_is_never_cancelled():
    """Canvas has acted on a POST; stopping would lose its reply."""
    c = Canvas(BASE, "t")
    slept = []
    c.sleep = slept.append

    class S:
        headers = {}

        def request(self, method, url, **kw):
            return make_response(url, payload={"id": 1},
                                 headers={"X-Rate-Limit-Remaining": "50"})
    c.session = S()
    with watch(c, RecordingReporter(cancel_after=0)):
        assert c._request("POST", f"{BASE}/x").json() == {"id": 1}
        assert slept == [10.0]                  # one uninterrupted pause
        with pytest.raises(Cancelled):          # a GET may stop
            c._request("GET", f"{BASE}/x")


def test_cancel_while_waiting_for_the_report_keeps_the_job(fake_canvas, tmp_path):
    """Stopping mid-poll leaves the job saved, so a rerun resumes it."""
    from golden.scenarios import add_new_quiz
    from painter.canvas.jobs import _load_state
    from painter.domain.selection import Selection
    from painter.services.quiz_export import QuizExportRequest, export_quiz
    add_new_quiz(fake_canvas)
    fake_canvas.extra[("GET", "/api/v1/progress/5")] = {
        "id": 5, "workflow_state": "running", "completion": 10}
    rep = RecordingReporter(cancel_after=1)
    with pytest.raises(Cancelled, match="waiting for the student analysis report"):
        export_quiz(Canvas(BASE, "t"), QuizExportRequest(
            100, (7003,), tmp_path, Selection(), course_export=False), rep)
    posts = [p for m, p, _ in fake_canvas.calls if m == "POST"]
    assert posts == ["/api/quiz/v1/courses/100/quizzes/7003/reports"]
    state = _load_state(tmp_path / "Quiz-1_7003" / ".quiz_export_state.json")
    assert list(state.values())[0]["progress_id"] == 5
    assert rep.of(Waiting)[0].reason == "waiting for the student analysis report"


def test_queue_reporter_across_threads():
    q = QueueReporter()

    def work():
        q.info("hello")
        q.progress(1, 2, "a")
        q.event(Stage("Downloading", total=2))
        while not q.cancelled():
            pass
        q.warning("stopped")
    t = threading.Thread(target=work)
    t.start()
    q.cancel()
    t.join(5)
    assert q.drain() == [("info", "hello"), ("progress", (1, 2, "a")),
                         ("event", Stage("Downloading", total=2)), ("warning", "stopped")]


def test_cancel_during_a_download_retry_stops_the_run_cleanly(fake_canvas, tmp_path, monkeypatch):
    import painter.services.submissions as subs
    from painter.services.submissions import DownloadRequest, download_submissions
    real = subs.download
    calls = []

    def flaky(canvas, url, dest, size=None):
        calls.append(url)
        if len(calls) == 2:
            raise Cancelled("stopped while retrying after a connection error")
        return real(canvas, url, dest, size)
    monkeypatch.setattr(subs, "download", flaky)
    with pytest.raises(Cancelled, match="manifest written") as exc:
        download_submissions(Canvas(BASE, "t"), DownloadRequest(
            100, tmp_path / "o", assignment_ids=(7001,), excel_log=False))
    res = exc.value.result
    assert [r["status"] for r in res.rows] == ["downloaded"]    # not "failed: ..."
    assert res.failures == 0 and res.manifest.exists()


# ---- what a GUI sees from each service --------------------------------------------
def test_events_from_quiz_export_and_report_uploads(fake_canvas, tmp_path):
    from golden.scenarios import add_new_quiz
    from painter.domain.selection import Selection
    from painter.events import ItemDone
    from painter.services.quiz_export import QuizExportRequest, export_quiz
    add_new_quiz(fake_canvas, report_rows=(
        "Name,ID,Q1\r\nJane Doe,501,https://canvas.test/files/9/download\r\n"))
    fake_canvas.extra[("GET", "/api/v1/files/9")] = {
        "id": 9, "display_name": "essay.pdf", "size": 2, "url": "https://files.test/f/9"}
    fake_canvas.file_bodies["/f/9"] = b"hi"
    rep = RecordingReporter()
    export_quiz(Canvas(BASE, "t"), QuizExportRequest(
        100, (7003,), tmp_path, Selection(), uploads=True, course_export=False), rep)
    assert [s.name for s in rep.of(Stage)] == [
        "Quiz content", "Student answers", "File uploads linked from the report"]
    kinds = [(e.kind, e.key, e.status) for e in rep.of(ItemDone)]
    assert ("upload", "essay.pdf", "downloaded") in kinds
    assert ("file", "Quiz-1_qti.zip", "exported") in kinds


def test_cancel_during_report_uploads_still_writes_the_log(fake_canvas, tmp_path):
    from painter.services.quiz_plan import QuizExportPlan
    from painter.services.quiz_uploads import download_report_uploads
    raw = tmp_path / "r.csv"
    raw.write_text("Name,ID,Q1,Q2\nJane Doe,501,https://bucket.s3.amazonaws.com/a.pdf,"
                   "https://bucket.s3.amazonaws.com/b.pdf\n", encoding="utf-8")
    from painter.canvas.client import FetchResult
    c = Canvas(BASE, "t")

    def fake_fetch(url, dest, *a, **k):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return FetchResult(True)
    c.fetch_file = fake_fetch
    with pytest.raises(Cancelled, match="uploads log written"):
        download_report_uploads(c, raw, QuizExportPlan([tmp_path / "q"]), 100, "Quiz",
                                RecordingReporter(cancel_after=1))
    log = tmp_path / "q" / "Quiz_uploads" / "uploads_log.csv"
    assert log.exists() and log.read_text(encoding="utf-8-sig").count("downloaded") == 1


def test_grade_posting_reports_each_student(fake_canvas, tmp_path):
    from datetime import datetime
    from golden.scenarios import GRADES
    from painter.events import ItemDone
    from painter.services.grading import plan_grades, post_grade_plans
    p = tmp_path / "A2.txt"
    p.write_text(GRADES, encoding="utf-8")
    c = Canvas(BASE, "t")
    rep = RecordingReporter()
    post_grade_plans(c, plan_grades(c, [p]), tmp_path, datetime(2026, 1, 1), rep)
    assert rep.of(Stage) == [Stage("Posting A2.txt", total=2)]
    assert [(e.key, e.status) for e in rep.of(ItemDone)] == [
        ("Roe, Rick", "verified"), ("De La Cruz, Ana", "verified")]
