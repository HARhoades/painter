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
