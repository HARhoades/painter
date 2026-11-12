"""Phase 4 part E: one exit-status table for every command."""
from __future__ import annotations

import os
import signal

import pytest

from painter.cli import exit_codes as X
from conftest import BASE

COMMON = ("--base-url", BASE, "--course", "100")


def test_quiz_nobody_selected_is_3_and_unfinished_export_is_1(fake_canvas, run_cli, tmp_path):
    from golden.scenarios import add_new_quiz
    add_new_quiz(fake_canvas)
    code, _, _ = run_cli(*COMMON, "quiz", "export", "--assignment", "7003",
                         "--no-course-export", "--student", "Doe", "--out", str(tmp_path / "o"))
    assert code == X.OK
    for uid in (501, 502, 503):
        del fake_canvas.submissions[7003][uid]
    code, _, err = run_cli(*COMMON, "quiz", "export", "--assignment", "7003",
                           "--student", "Doe", "--out", str(tmp_path / "o"))
    assert code == X.NOTHING and "nothing exported" in err


def test_unfinished_course_export_is_1(fake_canvas, run_cli, tmp_path):
    from golden.scenarios import add_new_quiz
    add_new_quiz(fake_canvas)
    fake_canvas.extra[("POST", "/api/v1/courses/100/content_exports")] = {
        "id": 80, "workflow_state": "created"}
    fake_canvas.extra[("GET", "/api/v1/courses/100/content_exports/80")] = {
        "id": 80, "workflow_state": "exporting"}
    code, _, err = run_cli(*COMMON, "quiz", "export", "--assignment", "7003",
                           "--no-answers", "--timeout", "0", "--out", str(tmp_path / "o"))
    assert code == X.PROBLEMS and "Rerun the same command to pick it up" in err


def _boom(exc):
    def run(*a, **k):
        raise exc
    return run


def test_unexpected_error_writes_a_crash_report(fake_canvas, run_cli, monkeypatch, tmp_path):
    monkeypatch.setattr("painter.crash.app_data_dir", lambda: tmp_path / "app")
    monkeypatch.setattr("painter.cli.commands.download_submissions",
                        _boom(ZeroDivisionError("bad sum")))
    code, _, err = run_cli(*COMMON, "download", "--out", str(tmp_path / "o"))
    assert code == X.UNKNOWN
    assert "Error: unexpected problem (ZeroDivisionError: bad sum)." in err
    report = next((tmp_path / "app" / "logs").glob("crash_*.txt"))
    assert "Traceback" in report.read_text(encoding="utf-8") and str(report) in err
    code, _, err = run_cli("--debug", *COMMON, "download", "--out", str(tmp_path / "o"))
    assert code == X.UNKNOWN and "Traceback" in err and "ZeroDivisionError: bad sum" in err


@pytest.mark.parametrize("exc, code", [
    (KeyboardInterrupt(), X.INTERRUPTED),
    (PermissionError("[Errno 13] Permission denied: 'o'"), X.SETUP),
])
def test_interrupt_and_file_system_errors(fake_canvas, run_cli, monkeypatch, tmp_path, exc, code):
    monkeypatch.setattr("painter.cli.commands.download_submissions", _boom(exc))
    got, _, err = run_cli(*COMMON, "download", "--out", str(tmp_path / "o"))
    assert got == code and "Traceback" not in err


def test_cancel_from_ctrl_c_is_130_with_what_was_done(fake_canvas, run_cli, monkeypatch, tmp_path):
    from painter.errors import Cancelled
    monkeypatch.setattr("painter.cli.commands.download_submissions",
                        _boom(Cancelled("stopped after 1 file(s); manifest written")))
    code, _, err = run_cli(*COMMON, "download", "--out", str(tmp_path / "o"))
    assert code == X.INTERRUPTED and "Stopped: stopped after 1 file(s)" in err


def test_first_ctrl_c_asks_to_stop_second_stops_now(capsys):
    from painter.cli.console import ConsoleReporter
    rep = ConsoleReporter()
    with rep.stoppable():
        assert rep.cancelled() is False
        os.kill(os.getpid(), signal.SIGINT)
        assert rep.cancelled() is True
        assert "Ctrl+C again to stop now" in capsys.readouterr().err
        with pytest.raises(KeyboardInterrupt):
            os.kill(os.getpid(), signal.SIGINT)
    assert rep.cancelled() is False                 # reset for the next task
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_every_code_is_documented_in_help():
    from painter.cli.main import build_parser
    text = build_parser().format_help()
    for code, _ in X.TABLE:
        assert f"{code:>3}  " in text
