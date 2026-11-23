"""Run time, new data and speed for a download (for comparing worker counts)."""
from datetime import datetime
from pathlib import Path

import pytest

from conftest import BASE
from painter.canvas.client import Canvas
from painter.domain.measures import fmt_bytes, fmt_clock, fmt_duration, fmt_speed
from painter.errors import Cancelled
from painter.events import RecordingReporter
from painter.services.submissions import DownloadRequest, download_submissions


def test_formats():
    assert fmt_duration(0.4) == "under a second"
    assert fmt_duration(42.4) == "42 s"
    assert fmt_duration(187) == "3 min 07 s"
    assert fmt_duration(3900) == "1 h 05 min"
    assert fmt_clock(7) == "0:07" and fmt_clock(222) == "3:42" and fmt_clock(3909) == "1:05:09"
    assert fmt_bytes(812) == "812 B" and fmt_bytes(14540) == "14.2 KB"
    assert fmt_bytes(19_500_000) == "18.6 MB" and fmt_bytes(1_288_490_189) == "1.20 GB"
    assert fmt_speed(10 << 20, 2) == "5.0 MB/s"
    assert fmt_speed(100, 0.5) == "" and fmt_speed(0, 10) == ""


@pytest.mark.parametrize("workers", [1, 4])
def test_result_carries_time_data_and_workers(fake_canvas, tmp_path, workers):
    rep = RecordingReporter()
    req = DownloadRequest(100, tmp_path, (7001,), excel_log=False, workers=workers)
    res = download_submissions(Canvas(BASE, "t"), req, rep)
    sizes = sum(len(fake_canvas.file_bodies[p]) for p in ("/f/1", "/f/2"))
    assert res.elapsed > 0 and res.workers == workers
    assert res.downloaded_bytes == sizes
    line = [t for k, t in rep.lines if t.startswith("Finished in ")]
    at_once = "one file at a time." if workers == 1 else "4 files at a time."
    assert len(line) == 1 and f"2 new file(s) ({fmt_bytes(sizes)}" in line[0]
    assert line[0].endswith(at_once)
    again = download_submissions(Canvas(BASE, "t"), req, RecordingReporter())
    assert again.downloaded_bytes == 0                      # all cached


def test_a_stopped_run_says_stopped(fake_canvas, tmp_path):
    rep = RecordingReporter(cancel_after=1)
    with pytest.raises(Cancelled) as exc:
        download_submissions(Canvas(BASE, "t"), DownloadRequest(
            100, tmp_path, (7001,), excel_log=False, workers=1), rep)
    assert exc.value.result.elapsed > 0
    assert any(t.startswith("Stopped in ") for _, t in rep.lines)


def test_excel_summary_has_the_timing_rows(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from painter.storage.runlog_xlsx import RunInfo, write_run_log
    path = tmp_path / "log.xlsx"
    write_run_log([], path, RunInfo(datetime(2026, 11, 23), 100, BASE, Path("/o"),
                                    elapsed=222.44, downloaded_bytes=50 << 20, workers=4,
                                    rate_limiting="2 request(s) refused, waited 7 s"))
    ws = openpyxl.load_workbook(path)["Run Summary"]
    values = {r[0].value: r[1].value for r in ws.iter_rows(min_row=2) if r[0].value}
    assert values["Run time"] == "3 min 42 s"
    assert values["Run time (seconds)"] == 222.4
    assert values["New data"] == "50.0 MB" and values["New data (MB)"] == 50.0
    assert values["Average speed"] == "230.2 KB/s"
    assert values["Files at a time"] == 4
    assert values["Rate limiting"] == "2 request(s) refused, waited 7 s"


def test_excel_from_a_real_run_says_none_for_rate_limiting(fake_canvas, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    res = download_submissions(Canvas(BASE, "t"), DownloadRequest(
        100, tmp_path, (7001,), workers=4, run_started=datetime(2026, 11, 23, 16, 0)))
    ws = openpyxl.load_workbook(res.log_path)["Run Summary"]
    values = {r[0].value: r[1].value for r in ws.iter_rows(min_row=2) if r[0].value}
    assert values["Rate limiting"] == "none" and values["Files at a time"] == 4
