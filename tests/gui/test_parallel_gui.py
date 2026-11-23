"""Phase 7 in the window: the worker-count setting and one bar per assignment."""
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from conftest import connect_window  # noqa: E402
from painter.config import DEFAULT_WORKERS, load_settings  # noqa: E402
from painter.errors import Cancelled  # noqa: E402
from painter.events import AssignmentProgress, ItemDone, Stage  # noqa: E402
from painter.gui.views.download_run import assignment_caption  # noqa: E402
from painter.services.submissions import DownloadResult  # noqa: E402


@pytest.fixture
def setup(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.views["home"].list.setCurrentRow(0)
    v = window.views["download_setup"]
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        window.go("download_setup")
    v.folder.set_path(str(tmp_path / "out"))
    return v


def tick(v, *aids):
    for r in range(v.table.rowCount()):
        it = v.table.item(r, 0)
        if it.data(Qt.UserRole) in aids:
            it.setCheckState(Qt.Checked)


def test_settings_card_is_folded_and_saves_at_once(window, qtbot, tmp_path):
    connect_window(window, qtbot)
    window.go("connect")
    card = window.views["connect"].download_prefs
    assert card.workers.value() == DEFAULT_WORKERS == 4
    assert card.box.isHidden()                             # under "Advanced"
    card.fold.setChecked(True)
    assert not card.box.isHidden()
    card.workers.setValue(2)
    assert window.session.settings.download_workers == 2
    assert load_settings(tmp_path / "settings.json").download_workers == 2
    assert card.workers.maximum() == 8 and card.workers.minimum() == 1


def test_request_takes_the_setting_at_the_time_of_download(window, setup):
    tick(setup, 7001)
    assert setup.request().workers == 4
    window.session.settings.download_workers = 1
    assert setup.request().workers == 1


def test_real_download_shows_a_bar_per_assignment(window, setup, qtbot):
    tick(setup, 7001, 7002)
    setup.picker.section_buttons[11].setChecked(True)
    setup.picker.section_buttons[12].setChecked(True)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.finished, timeout=10000):
        setup.start()
        assert not window.settings_btn.isEnabled()         # no Settings while running
    rows = run.assignments
    assert set(rows.rows) == {7001, 7002}
    assert rows.caption(7001) == "✓  2 files"
    assert rows.caption(7002) == "no files"
    assert rows.bar(7001).value() == rows.bar(7001).maximum() == 2
    assert run.h1.text() == "Downloading 2 assignments · 4 at a time"
    assert run.student_bar.isHidden()                       # several students at once


def test_rows_follow_each_state_and_a_stop(window, setup, qtbot, monkeypatch):
    gate = threading.Event()

    def fake_download(canvas, req, reporter):
        reporter.event(Stage("Downloading 3 assignments · 4 at a time"))
        for aid in (1, 2, 3):
            reporter.event(AssignmentProgress(aid, f"A{aid}", "waiting"))
        reporter.event(AssignmentProgress(1, "A1", "downloading", 3, 10, 1))
        reporter.event(AssignmentProgress(2, "A2", "listing"))
        reporter.event(ItemDone("file", "x.pdf", "downloaded", "Doe, Jane"))
        gate.wait(5)
        reporter.event(AssignmentProgress(1, "A1", "stopped", 3, 10, 1))
        reporter.event(AssignmentProgress(2, "A2", "stopped"))
        reporter.event(AssignmentProgress(3, "A3", "stopped"))
        raise Cancelled("stopped", DownloadResult([], 1, []))
    monkeypatch.setattr("painter.gui.views.download_run.download_submissions", fake_download)
    tick(setup, 7001)
    setup.picker.section_buttons[11].setChecked(True)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.cancelled, timeout=5000):
        setup.start()
        qtbot.waitUntil(lambda: 2 in run.assignments.rows and
                        run.assignments.caption(2) == "listing submissions…", timeout=3000)
        assert run.assignments.caption(1) == "3 of 10 files · 1 failed"
        assert run.assignments.caption(3) == "waiting"
        assert run.assignments.bar(2).maximum() == 0         # busy while listing
        assert run.assignments.rows[1][2].property("tone") == "bad"
        run.stop()
        gate.set()
    # the done screen took over; the rows kept their final words
    assert run.assignments.caption(1) == "stopped at 3 of 10 · 1 failed"
    assert run.assignments.caption(2) == "stopped before it started"


def test_captions():
    c = lambda **kw: assignment_caption(AssignmentProgress(1, "A", **kw))
    assert c(state="done", done=5, total=5) == "✓  5 files"
    assert c(state="done", done=1, total=1) == "✓  1 file"
    assert c(state="done", done=5, total=5, failed=2) == "3 of 5 · 2 failed"
    assert c(state="downloading", done=0, total=4) == "0 of 4 files"


# ---- rate limiting banner -------------------------------------------------------
def test_rate_limit_banner_appears_and_stays_for_the_run(window, setup, qtbot, monkeypatch):
    from painter.events import RateLimit, Waiting
    gate = threading.Event()
    use = RateLimit(throttled=2, throttle_seconds=7.4, lowest_remaining=12, workers=4)

    def fake_download(canvas, req, reporter):
        reporter.event(Waiting("Canvas is rate-limiting requests; retrying", 4))
        reporter.event(use)
        reporter.event(ItemDone("file", "x.pdf", "downloaded", "Doe, Jane"))
        reporter.progress(1, 2, "x.pdf")                # clears the wait banner
        gate.wait(5)
        return DownloadResult([{"status": "downloaded", "user_id": 501,
                                "assignment_id": 7001}], 0, [], rate=use)
    monkeypatch.setattr("painter.gui.views.download_run.download_submissions", fake_download)
    tick(setup, 7001)
    setup.picker.section_buttons[11].setChecked(True)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.finished, timeout=5000):
        setup.start()
        qtbot.waitUntil(lambda: not run.rate.isHidden(), timeout=3000)
        qtbot.waitUntil(lambda: run.big.text() == "1", timeout=3000)
        assert run.rate.property("kind") == "attention"
        assert run.rate.title.text() == "Canvas is rate-limiting this download"
        body = run.rate.text.text()
        assert "refused 2 requests so far" in body and "waited 7 s" in body
        assert "Lowest remaining allowance: 12." in body
        assert "Downloading 4 files at a time" in body
        assert "Files to download at once" in body
        assert not run.rate.isHidden()                  # still up after files arrived
        gate.set()
    done = window.views["download_done"]
    assert window.current is done and not done.rate.isHidden()
    assert done.rate.title.text() == "Canvas rate-limited this download"
    assert "so far" not in done.rate.text.text()


def test_no_rate_limit_banner_on_a_clean_run(window, setup, qtbot):
    tick(setup, 7001)
    setup.picker.section_buttons[11].setChecked(True)
    with qtbot.waitSignal(window.runner.finished, timeout=10000):
        setup.start()
    assert window.views["download_run"].rate.isHidden()
    assert window.views["download_done"].rate.isHidden()


def test_rate_text_pacing_only_and_long_waits():
    from painter.events import RateLimit
    from painter.gui.views.download_run import fmt_seconds, rate_text
    title, body = rate_text(RateLimit(paced_seconds=95, workers=1), finished=True)
    assert title == "Painter slowed down to stay under Canvas's rate limit"
    assert "paused 1 min 35 s before the limit ran out" in body
    assert "1 file at a time" in body and "refused" not in body
    assert fmt_seconds(0.3) == "under a second" and fmt_seconds(5) == "5 s"


# ---- run time ---------------------------------------------------------------------
def test_clock_ticks_while_running_and_the_done_screen_shows_run_time(window, setup, qtbot,
                                                                      monkeypatch):
    gate = threading.Event()
    result = DownloadResult([{"status": "downloaded", "user_id": 501, "assignment_id": 7001}],
                            0, [], elapsed=222.4, downloaded_bytes=50 << 20, workers=4)

    def fake_download(canvas, req, reporter):
        gate.wait(5)
        return result
    monkeypatch.setattr("painter.gui.views.download_run.download_submissions", fake_download)
    tick(setup, 7001)
    setup.picker.section_buttons[11].setChecked(True)
    run = window.views["download_run"]
    with qtbot.waitSignal(window.runner.finished, timeout=8000):
        setup.start()
        assert run.clock.text() == "0:00 elapsed" and run.ticker.isActive()
        qtbot.waitUntil(lambda: run.clock.text() == "0:01 elapsed", timeout=3000)
        gate.set()
    assert not run.ticker.isActive()
    assert run.clock.text() == "3:42 in all"                 # the run's own measure
    done = window.views["download_done"]
    tile = done.time_tile
    texts = [w.text() for w in tile.findChildren(type(done.h1))]
    assert "3 min 42 s" in texts
    assert "run time · 50.0 MB new at 230.2 KB/s · 4 files at a time" in texts


def test_timing_tile_wording():
    from painter.gui.views.download_done import timing_tile
    r = DownloadResult([], 0, [], elapsed=0.4, downloaded_bytes=0, workers=1)
    assert timing_tile(r) == ("under a second", "run time · 0 B new · one file at a time")
    r = DownloadResult([], 0, [], elapsed=65, downloaded_bytes=3 << 20, workers=6)
    assert timing_tile(r, stopped=True) == (
        "1 min 05 s", "run time before you stopped · 3.0 MB new at 47.3 KB/s · 6 files at a time")
