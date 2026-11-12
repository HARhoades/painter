"""The browser-uploads flow, driven by a fake browser instead of Playwright.

PlaywrightQuizBrowser only drives the browser; everything that decides what
to visit, where files go and what is logged runs here for real.
"""
from __future__ import annotations

import pytest

from painter.canvas.client import Canvas
from painter.events import RecordingReporter
from painter.services.quiz_uploads import (
    NO_STUDENTS, UPLOADS_WITH_PROBLEMS, BrowserUploadsRequest, browser_quiz_uploads,
)
from conftest import BASE
from golden.scenarios import add_new_quiz


def upload(pos, name, size, url):
    return {"position": pos, "item_id": f"i{pos}",
            "scored_data": {"value": [{"name": name, "size": size, "url": url}]}}


class FakeBrowser:
    """Scripted SpeedGrader: quiz session -> captured {"results", "name"}."""

    def __init__(self, captured, bodies, clickable=()):
        self.captured, self.bodies, self.clickable = captured, bodies, set(clickable)
        self.events = []

    def __call__(self, canvas, req, reporter):          # used as open_browser
        return self

    def __enter__(self):
        self.events.append("open")
        return self

    def __exit__(self, *exc):
        self.events.append("close")
        return False

    def sign_in(self):
        self.events.append("sign_in")

    def load_student(self, uid, sess, timeout):
        self.events.append(("load", uid))
        key = sess or f"guess{uid}"
        return (key, self.captured[key]) if key in self.captured else (None, {})

    def fetch(self, url):
        if url not in self.bodies:
            raise RuntimeError("HTTP 403")
        return self.bodies[url]

    def click_download(self, name, target):
        if name not in self.clickable:
            raise RuntimeError("no link")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"clicked")

    def pause(self, seconds):
        self.events.append("pause")


@pytest.fixture
def quiz(fake_canvas):
    add_new_quiz(fake_canvas)        # sessions 5010, 5020, 5030 for 501, 502, 503
    return Canvas(BASE, "t")


def req(tmp_path, **kw):
    return BrowserUploadsRequest(100, (7003,), tmp_path / "o", **kw)


def test_visits_saves_logs_and_falls_back(quiz, tmp_path):
    browser = FakeBrowser(
        captured={
            # 503 (De La Cruz) never loads
            "5010": {"results": [upload(1, "essay.pdf", 3, "u1"),
                                 upload(2, "draw.png", None, "u2"),
                                 upload(3, "gone.txt", 1, "u3")]},
            "5020": {"results": []},                       # Roe: no uploads
        },
        bodies={"u1": b"abc"}, clickable={"draw.png"})
    rep = RecordingReporter()
    res = browser_quiz_uploads(quiz, req(tmp_path), rep, open_browser=browser)

    assert res.outcome == UPLOADS_WITH_PROBLEMS
    assert (res.saved, res.no_files, res.failed) == (2, 1, 2)
    # sorted by name; a pause only after a student whose files were processed
    assert browser.events == ["open", "sign_in", ("load", 503), ("load", 501), "pause",
                              ("load", 502), "close"]
    folder = tmp_path / "o" / "Quiz-1_7003" / "Quiz-1_uploads" / "Doe-Jane_501"
    assert (folder / "Q1__essay.pdf").read_bytes() == b"abc"
    assert (folder / "Q2__draw.png").read_bytes() == b"clicked"
    assert not (folder / "Q3__gone.txt").exists()
    statuses = [(r["user_id"], r["status"]) for r in res.log]
    assert statuses == [
        (503, "failed: quiz results did not load"),
        (501, "downloaded"), (501, "downloaded (via click)"),
        (501, "failed: HTTP 403; click: no link"),
        (502, "no files")]
    assert len(res.log_paths) == 1 and res.log_paths[0].name == "uploads_log.csv"
    assert "2 file(s) saved, 1 student(s) with no upload, 2 problem(s)." in rep.text()
    assert [e[:2] for e in rep.progress_events] == [(0, 3), (1, 3), (2, 3)]

    # a rerun keeps what is already there
    again = browser_quiz_uploads(quiz, req(tmp_path), RecordingReporter(),
                                 open_browser=FakeBrowser(browser.captured, {}))
    assert [r["status"] for r in again.log if r["user_id"] == 501][:2] == ["cached", "cached"]


def test_page_for_another_student_is_skipped(quiz, fake_canvas, tmp_path):
    """Without a session id in the launch URL the page decides; a name check guards it."""
    for uid in (501, 502, 503):
        fake_canvas.submissions[7003][uid]["url"] = "https://x/launch"
    browser = FakeBrowser(captured={
        "guess501": {"name": "Rick Roe", "results": [upload(1, "a.pdf", 1, "u")]},
        "guess502": {"name": "Rick Roe", "results": []},
        "guess503": {"name": "Ana De La Cruz", "results": []}}, bodies={"u": b"x"})
    res = browser_quiz_uploads(quiz, req(tmp_path), RecordingReporter(),
                               open_browser=browser)
    doe = [r for r in res.log if r["user_id"] == 501]
    assert doe == [{"student_folder": "Doe-Jane_501", "user_id": 501,
                    "quiz_session": "guess501", "question": "", "file": "", "size": "",
                    "status": "failed: page showed Rick Roe"}]
    assert res.saved == 0 and res.no_files == 2


def test_cancel_stops_between_students_and_still_logs(quiz, tmp_path):
    from painter.errors import Cancelled
    browser = FakeBrowser(captured={"5030": {"results": []}}, bodies={})
    with pytest.raises(Cancelled, match="log written"):
        browser_quiz_uploads(quiz, req(tmp_path), RecordingReporter(cancel_after=1),
                             open_browser=browser)
    assert browser.events == ["open", "sign_in", ("load", 503), "close"]
    assert (tmp_path / "o" / "Quiz-1_7003" / "Quiz-1_uploads" / "uploads_log.csv").exists()


def test_limit_and_nobody_to_visit(quiz, fake_canvas, tmp_path):
    browser = FakeBrowser(captured={}, bodies={})
    res = browser_quiz_uploads(quiz, req(tmp_path, limit=1), RecordingReporter(),
                               open_browser=browser)
    assert [e for e in browser.events if isinstance(e, tuple)] == [("load", 503)]
    for uid in (501, 502, 503):
        fake_canvas.submissions[7003][uid]["workflow_state"] = "unsubmitted"
    nobody = browser_quiz_uploads(quiz, req(tmp_path), RecordingReporter(),
                                  open_browser=FakeBrowser({}, {}))
    assert nobody.outcome == NO_STUDENTS
