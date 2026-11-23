"""Parallel downloads (phase 7): same files and manifest as one at a time,
in listing order, with per-assignment progress and a clean stop."""
import threading
import time

import pytest

from conftest import BASE, FILES, make_response
from painter.canvas.client import Canvas
from painter.errors import Cancelled
from painter.events import AssignmentProgress, ItemDone, RecordingReporter
from painter.services.submissions import DownloadRequest, download_submissions
from painter.storage.tabular import read_records


def add_files(fake, aid, per_student, sizes=None):
    """Give assignment `aid` `per_student` attachments for each of 501-503."""
    sizes = sizes or {}
    if aid not in {a["id"] for a in fake.assignments}:
        fake.assignments.append({"id": aid, "name": f"Lab {aid}", "due_at": None,
                                 "published": True, "submission_types": ["online_upload"],
                                 "all_dates": [], "overrides": []})
    subs = {}
    n = 0
    for uid in (501, 502, 503):
        atts = []
        for k in range(per_student):
            n += 1
            path = f"/f/{aid}-{uid}-{k}"
            body = b"x" * sizes.get((uid, k), 10 + n)
            fake.file_bodies[path] = body
            atts.append({"id": aid * 100 + n, "display_name": f"part{k}.txt",
                         "url": f"{FILES}{path}", "size": len(body)})
        subs[uid] = {"user_id": uid, "workflow_state": "submitted", "attempt": 1,
                     "submitted_at": "2026-09-01T00:00:00Z", "seconds_late": 0,
                     "late": False, "missing": False, "score": None,
                     "attachments": atts}
    fake.submissions[aid] = subs


def run(tmp_path, workers, ids=(7001, 7101, 7102), reporter=None, **kw):
    req = DownloadRequest(100, tmp_path / "out", ids, excel_log=False,
                          workers=workers, **kw)
    return download_submissions(Canvas(BASE, "t"), req, reporter or RecordingReporter())


@pytest.fixture
def course(fake_canvas):
    add_files(fake_canvas, 7101, 2)
    add_files(fake_canvas, 7102, 3)
    return fake_canvas


def files_under(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and p.name != "manifest.csv"}


def test_same_files_and_manifest_as_one_at_a_time(course, tmp_path):
    serial = run(tmp_path / "a", 1)
    parallel = run(tmp_path / "b", 4)
    assert files_under(tmp_path / "a" / "out") == files_under(tmp_path / "b" / "out")
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ("path", "extracted_to")}
                          for r in rows]
    assert strip(parallel.rows) == strip(serial.rows)          # listing order kept
    _, a = read_records(tmp_path / "a" / "out" / "manifest.csv")
    _, b = read_records(tmp_path / "b" / "out" / "manifest.csv")
    assert [r["filename"] for r in a] == [r["filename"] for r in b]
    assert not list((tmp_path / "b").rglob("*.part"))


def test_every_assignment_reports_waiting_first_and_one_final_state(course, tmp_path):
    rep = RecordingReporter()
    res = run(tmp_path, 4, reporter=rep)
    by_id = {}
    for e in rep.of(AssignmentProgress):
        by_id.setdefault(e.assignment_id, []).append(e)
    assert set(by_id) == {7001, 7101, 7102}
    for aid, evs in by_id.items():
        assert evs[0].state == "waiting"
        assert [e.state for e in evs].count("done") == 1 and evs[-1].state == "done"
        assert evs[-1].done == evs[-1].total
    assert by_id[7101][-1].total == 6 and by_id[7102][-1].total == 9
    assert sum(e.done for e in (v[-1] for v in by_id.values())) == len(res.rows)
    assert len(rep.of(ItemDone)) == len(res.rows)


def test_console_blocks_are_whole_and_under_their_assignment(course, tmp_path):
    rep = RecordingReporter()
    run(tmp_path, 4, reporter=rep)
    text = rep.text("info")
    assert "Downloading 4 files at a time." in text
    assert "[7102] done: 9 file(s)" in text
    files_each = {7001: 1, 7101: 2, 7102: 3}
    current, block, seen = None, None, []
    for line in text.splitlines() + [""]:
        if line.startswith("["):
            current = int(line[1:line.index("]")])
        elif "  submitted " in line:
            block = [current, 0]
            seen.append(block)
        elif line.startswith("    ") and block is not None and not line.startswith("      "):
            block[1] += 1
        elif not line.startswith("      "):
            block = None
    assert len(seen) == 8                     # 7001: Ana never submitted
    for aid, n in seen:
        assert n == files_each[aid], (aid, n)


def test_largest_files_start_first_within_an_assignment(fake_canvas, tmp_path, monkeypatch):
    import requests
    add_files(fake_canvas, 7101, 1, sizes={(501, 0): 10, (502, 0): 5000, (503, 0): 300})
    order = []
    real = fake_canvas.handle

    def spy(session, method, url, **kw):
        if url.startswith(FILES):
            order.append(url.rsplit("/", 1)[1])
        return real(session, method, url, **kw)
    monkeypatch.setattr(requests.Session, "request", lambda s, m, u, **kw: spy(s, m, u, **kw))
    run(tmp_path, 2, ids=(7101,))
    # two workers: the two largest start together, the smallest waits
    assert set(order[:2]) == {"7101-502-0", "7101-503-0"} and order[2] == "7101-501-0"


def test_listing_the_next_assignment_overlaps_the_downloads(course, tmp_path, monkeypatch):
    """A2's listing is requested while A1's files are still downloading."""
    import requests
    gate = threading.Event()
    events = []
    real = course.handle

    def handle(session, method, url, **kw):
        if url.startswith(FILES) and "/f/7101-" in url:
            events.append(("file-start", url))
            gate.wait(5)                       # hold A1's files until A2 is listed
            events.append(("file-end", url))
        elif "/assignments/7102/submissions" in url:
            events.append(("list-7102", url))
            gate.set()
        return real(session, method, url, **kw)
    monkeypatch.setattr(requests.Session, "request",
                        lambda s, m, u, **kw: handle(s, m, u, **kw))
    run(tmp_path, 4, ids=(7101, 7102))
    kinds = [k for k, _ in events]
    assert kinds.index("list-7102") < kinds.index("file-end")


def test_one_failed_file_does_not_stop_the_others(course, tmp_path):
    del course.file_bodies["/f/7101-502-0"]               # 404 for one file
    res = run(tmp_path, 4)
    assert res.failures == 1
    failed = [r for r in res.rows if r["status"].startswith("failed")]
    assert [r["filename"] for r in failed] == ["part0.txt"]
    assert len(res.rows) == 2 + 6 + 9        # every file has a row


def test_stop_part_way_writes_manifest_and_marks_stopped(course, tmp_path):
    rep = RecordingReporter(cancel_after=3)
    with pytest.raises(Cancelled) as exc:
        run(tmp_path, 2, reporter=rep)
    res = exc.value.result
    assert (tmp_path / "out" / "manifest.csv").exists()
    assert not list(tmp_path.rglob("*.part"))
    finals = {}
    for e in rep.of(AssignmentProgress):
        finals[e.assignment_id] = e
    assert all(e.state in ("done", "stopped") for e in finals.values())
    assert any(e.state == "stopped" for e in finals.values())
    saved = {r["path"] for r in res.rows}
    assert all((tmp_path / "out").joinpath(p).exists() or __import__("pathlib").Path(p).exists()
               for p in saved)
    again = run(tmp_path, 2)                                # rerun finishes the job
    assert {r["status"] for r in again.rows} <= {"downloaded", "cached"}
    assert len(again.rows) == 2 + 6 + 9


def test_files_sharing_a_path_are_never_written_at_once(course, tmp_path, monkeypatch):
    """If two jobs ever map to one saved path, the second waits for the first
    (two threads writing one .part would corrupt it)."""
    import painter.services.submissions as subs
    monkeypatch.setattr(subs, "attachment_filenames", lambda atts: ["same.txt"] * len(atts))
    active, clash, lock = set(), [], threading.Lock()
    real = subs._fetch_one

    def spy(canvas, att, sdir, fname, unpack):
        target = sdir / fname
        with lock:
            if target in active:
                clash.append(target)
            active.add(target)
        time.sleep(0.01)
        try:
            return real(canvas, att, sdir, fname, unpack)
        finally:
            with lock:
                active.discard(target)
    monkeypatch.setattr(subs, "_fetch_one", spy)
    res = run(tmp_path, 4, ids=(7102,))                     # 3 files per student, one name
    assert clash == []
    assert len(res.rows) == 9 and {r["status"] for r in res.rows} == {"downloaded"}
    assert not list(tmp_path.rglob("*.part"))


def test_second_ctrl_c_stops_the_workers_and_leaves_no_part_files(course, tmp_path):
    class Interrupting(RecordingReporter):
        def progress(self, done, total, label=""):
            super().progress(done, total, label)
            if done == 2:
                raise KeyboardInterrupt      # as the console's second Ctrl+C does
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, 4, reporter=Interrupting())
    assert not [t for t in threading.enumerate() if t.name.startswith("painter-download")]
    assert not list(tmp_path.rglob("*.part"))


def test_one_worker_is_the_serial_path_with_the_same_assignment_events(course, tmp_path):
    rep = RecordingReporter()
    res = run(tmp_path, 1, reporter=rep)
    assert "at a time" not in rep.text()
    finals = {}
    for e in rep.of(AssignmentProgress):
        finals.setdefault(e.assignment_id, []).append(e.state)
    assert {aid: (s[0], s[-1]) for aid, s in finals.items()} == {
        7001: ("waiting", "done"), 7101: ("waiting", "done"), 7102: ("waiting", "done")}
    last = [e for e in rep.of(AssignmentProgress) if e.state == "done"]
    assert sum(e.done for e in last) == len(res.rows)


def test_serial_stop_marks_the_rest_stopped(course, tmp_path):
    rep = RecordingReporter(cancel_after=3)
    with pytest.raises(Cancelled):
        run(tmp_path, 1, reporter=rep)
    finals = {}
    for e in rep.of(AssignmentProgress):
        finals[e.assignment_id] = e.state
    assert "stopped" in finals.values() and set(finals.values()) <= {"done", "stopped"}


# ---- rate limiting: reported live and on the result ---------------------------
def throttle_once(monkeypatch, fake, path, retry_after="3", remaining=None):
    """Canvas refuses the first request for `path` as over the limit."""
    import requests
    real, seen = fake.handle, set()

    def handle(session, method, url, **kw):
        if url.endswith(path) and path not in seen:
            seen.add(path)
            return make_response(url, 429, headers={"Retry-After": retry_after})
        resp = real(session, method, url, **kw)
        if remaining is not None and "/submissions" in url:
            resp.headers["X-Rate-Limit-Remaining"] = remaining
        return resp
    monkeypatch.setattr(requests.Session, "request", lambda s, m, u, **kw: handle(s, m, u, **kw))


@pytest.mark.parametrize("workers", [1, 4])
def test_a_throttled_request_is_reported(course, tmp_path, monkeypatch, workers):
    from painter.events import RateLimit
    throttle_once(monkeypatch, course, "/f/7101-502-1")
    rep = RecordingReporter()
    res = run(tmp_path, workers, reporter=rep)
    assert res.failures == 0                                 # retried, then fetched
    assert res.rate == RateLimit(throttled=1, throttle_seconds=3.0, workers=workers)
    assert rep.of(RateLimit)[-1] == res.rate
    assert ("Canvas rate limiting during this run: 1 request(s) refused, waited 3s "
            f"({workers} file(s) at a time)") in rep.text("warning")


def test_pacing_alone_is_reported_with_the_lowest_allowance(course, tmp_path, monkeypatch):
    from painter.events import RateLimit
    throttle_once(monkeypatch, course, "/nothing", remaining="50")
    rep = RecordingReporter()
    res = run(tmp_path, 4, reporter=rep)
    assert res.rate.throttled == 0 and res.rate.paced_seconds > 0
    assert res.rate.lowest_remaining == 50.0 and res.rate.limited
    assert "lowest remaining 50" in rep.text("warning")


def test_no_rate_limiting_no_report(course, tmp_path):
    from painter.events import RateLimit
    rep = RecordingReporter()
    res = run(tmp_path, 4, reporter=rep)
    assert res.rate is None and rep.of(RateLimit) == []
    assert "rate limiting" not in rep.text()


def test_each_run_counts_only_its_own_rate_limiting(course, tmp_path, monkeypatch):
    """The window keeps one Canvas client; a later run doesn't inherit counts."""
    throttle_once(monkeypatch, course, "/f/7101-502-1")
    canvas = Canvas(BASE, "t")
    first = download_submissions(canvas, DownloadRequest(100, tmp_path / "a", (7101,),
                                                         excel_log=False, workers=4))
    second = download_submissions(canvas, DownloadRequest(100, tmp_path / "b", (7101,),
                                                          excel_log=False, workers=4))
    assert first.rate.throttled == 1 and second.rate is None
