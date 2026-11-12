"""The old script name still works as a module and as a command."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_shim_reexports_the_package():
    import canvas_fetch_submissions as shim
    from painter.canvas.client import Canvas
    from painter.cli.main import main
    from painter.services.grading import post_grades

    assert shim.main is main and shim.Canvas is Canvas and shim.post_grades is post_grades
    assert "Download (and optionally extract) student submission files" in shim.__doc__


def test_old_command_and_module_entry_point_run():
    for cmd in (["canvas_fetch_submissions.py"], ["-m", "painter"]):
        r = subprocess.run([sys.executable, *cmd, "--course", "1"], cwd=ROOT,
                           capture_output=True, text=True)
        assert r.returncode == 2 and "--base-url is required" in r.stderr
