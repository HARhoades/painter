"""The old script name runs the same command line as `painter`."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_shim_runs_the_package_cli():
    import canvas_fetch_submissions as shim
    from painter.cli.main import main
    assert shim.main is main


def test_old_script_and_module_entry_point_run_the_subcommands():
    for cmd in (["canvas_fetch_submissions.py"], ["-m", "painter"]):
        r = subprocess.run([sys.executable, *cmd, "download", "--course", "1"], cwd=ROOT,
                           capture_output=True, text=True)
        assert r.returncode == 2 and "--base-url is required" in r.stderr
