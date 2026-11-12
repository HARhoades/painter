"""Default locations (review finding 8)."""
from pathlib import Path

from painter.config import default_browser_profile


def test_browser_profile_defaults_to_local_app_data_on_windows():
    env = {"LOCALAPPDATA": r"C:\Users\me\AppData\Local",
           "USERPROFILE": r"C:\Users\me"}
    p = default_browser_profile(env, "win32")
    assert p == Path(r"C:\Users\me\AppData\Local") / "painter" / "browser-profile"
    assert "OneDrive" not in str(p)


def test_browser_profile_on_macos_and_linux():
    assert default_browser_profile({"HOME": "/Users/me"}, "darwin") == \
        Path("/Users/me/Library/Application Support/painter/browser-profile")
    assert default_browser_profile({"HOME": "/home/me"}, "linux") == \
        Path("/home/me/.local/state/painter/browser-profile")
    assert default_browser_profile({"HOME": "/home/me", "XDG_STATE_HOME": "/s"}, "linux") == \
        Path("/s/painter/browser-profile")


def test_cli_no_longer_defaults_to_the_working_folder(fake_canvas, run_cli, monkeypatch):
    seen = {}
    monkeypatch.setattr("painter.cli.main.browser_quiz_uploads",
                        lambda canvas, args: seen.setdefault("p", args.browser_profile) and 0)
    run_cli("--base-url", "https://canvas.test", "--course", "100",
            "--assignment", "7001", "--browser-uploads")
    assert seen["p"] == str(default_browser_profile())


def test_reporters(capsys):
    from painter.cli.console import ConsoleReporter
    from painter.events import NULL, RecordingReporter
    r = ConsoleReporter()
    r.info("a")
    r.info("b", end="")
    r.warning("c")
    r.progress(1, 2)
    out, err = capsys.readouterr()
    assert (out, err) == ("a\nb", "c\n") and not r.cancelled()
    rec = RecordingReporter(cancel_after=1)
    rec.info("x")
    rec.warning("y")
    assert rec.text() == "x\ny" and rec.text("warning") == "y"
    assert rec.cancelled() is False and rec.cancelled() is True
    NULL.info("ignored")
