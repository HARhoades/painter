"""--jobs on the command line and the worker-count setting (phase 7).

Completion order isn't fixed with several workers, so these compare each
student's block of lines exactly but ignore the order of the blocks."""
import json

import pytest

from conftest import BASE
from painter.cli import exit_codes
from painter.config import DEFAULT_WORKERS, MAX_WORKERS, Settings, load_settings, save_settings
from painter.storage.tabular import read_records

COMMON = ("--base-url", BASE, "--course", "100")


def blocks(out: str) -> dict[str, list[str]]:
    """{assignment id: sorted per-student blocks}; each block is its lines."""
    found: dict[str, list[tuple]] = {}
    current, block = None, None
    for line in out.splitlines():
        if line.startswith("["):
            current = line[1:line.index("]")]
            block = None
        elif "  submitted " in line:
            block = [line]
            found.setdefault(current, []).append(block)
        elif line.startswith("    ") and block is not None:
            block.append(line)
        else:
            block = None
    return {k: sorted(tuple(b) for b in v) for k, v in found.items()}


def test_the_default_is_four_at_a_time_with_the_same_files_and_blocks(fake_canvas, run_cli, tmp_path):
    code1, out1, _ = run_cli(*COMMON, "download", "--out", str(tmp_path / "a"), "--no-xlsx",
                             "--jobs", "1")
    code4, out4, _ = run_cli(*COMMON, "download", "--out", str(tmp_path / "b"), "--no-xlsx")
    assert code1 == code4 == exit_codes.OK
    assert f"Downloading {DEFAULT_WORKERS} files at a time." in out4
    assert "at a time" not in out1
    assert blocks(out4) == blocks(out1)
    _, a = read_records(tmp_path / "a" / "manifest.csv")
    _, b = read_records(tmp_path / "b" / "manifest.csv")
    assert [(r["assignment_id"], r["filename"], r["status"]) for r in a] == \
           [(r["assignment_id"], r["filename"], r["status"]) for r in b]


def test_rerun_finds_everything_cached(fake_canvas, run_cli, tmp_path):
    out_dir = str(tmp_path / "o")
    run_cli(*COMMON, "download", "--out", out_dir, "--no-xlsx")
    before = len(fake_canvas.calls)
    code, out, _ = run_cli(*COMMON, "download", "--out", out_dir, "--no-xlsx")
    assert code == exit_codes.OK
    assert "    downloaded" not in out and "    cached" in out
    assert not [p for m, p, _ in fake_canvas.calls[before:] if p.startswith("/f/")]


def test_a_failed_file_gives_the_problems_exit_code(fake_canvas, run_cli, tmp_path):
    del fake_canvas.file_bodies["/f/1"]
    code, out, err = run_cli(*COMMON, "download", "--out", str(tmp_path / "o"), "--no-xlsx")
    assert code == exit_codes.PROBLEMS
    assert "! failed essay.pdf" in out
    assert "1 failed" in out


@pytest.mark.parametrize("bad", ["0", str(MAX_WORKERS + 1), "four", "-2"])
def test_jobs_outside_the_range_is_refused(fake_canvas, run_cli, tmp_path, bad):
    code, _, err = run_cli(*COMMON, "download", "--out", str(tmp_path / "o"), "--jobs", bad)
    assert code == exit_codes.BAD_INPUT
    assert "--jobs" in err and f"1 to {MAX_WORKERS}" in err
    assert not fake_canvas.calls                          # nothing asked of Canvas


# ---- the setting --------------------------------------------------------------
def test_setting_defaults_to_four():
    assert Settings().download_workers == DEFAULT_WORKERS == 4


@pytest.mark.parametrize("stored, expected", [
    (None, 4), ("6", 4), (True, 4), (0, 4), (MAX_WORKERS + 1, 4), (2.5, 4), (1, 1), (8, 8)])
def test_setting_is_clamped_when_read(tmp_path, stored, expected):
    p = tmp_path / "settings.json"
    data = {"base_url": "https://x.test"}
    if stored is not None:
        data["download_workers"] = stored
    p.write_text(json.dumps(data), encoding="utf-8")
    assert load_settings(p).download_workers == expected


def test_setting_round_trips(tmp_path):
    p = tmp_path / "settings.json"
    s = Settings()
    s.download_workers = 6
    save_settings(s, p)
    assert load_settings(p).download_workers == 6
