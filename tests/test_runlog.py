"""Excel run log: formulas point at the right columns (review finding 12)."""
from datetime import datetime

import pytest

from painter.storage import runlog_xlsx as rl

openpyxl = pytest.importorskip("openpyxl")


def _info(tmp_path):
    return rl.RunInfo(datetime(2026, 11, 12), 100, "https://canvas.test", tmp_path)


def test_column_letters_follow_log_columns():
    assert rl._letter(1) == "A" and rl._letter(26) == "Z" and rl._letter(27) == "AA"
    headers = [h for h, _ in rl.LOG_COLUMNS] + ["New submission", "New student"]
    def header_at(letter):
        return headers[openpyxl.utils.column_index_from_string(letter) - 1]
    assert header_at(rl.COL_ASSIGN_ID) == "Assignment ID"
    assert header_at(rl.COL_USER_ID) == "User ID"
    assert header_at(rl.COL_SECTION) == "Section"
    assert header_at(rl.COL_LATE) == "Late"
    assert header_at(rl.COL_FILE) == "File"
    assert header_at(rl.COL_NEW_SUB) == "New submission"
    assert header_at(rl.COL_NEW_STU) == "New student"


def test_written_log_headers_match_formula_columns(tmp_path):
    rows = [{"assignment": "A", "assignment_id": 1, "student": "Doe, Jane",
             "user_id": 501, "section": "A1-8", "late": True, "filename": "x.pdf"}]
    path = tmp_path / "log.xlsx"
    rl.write_run_log(rows, path, _info(tmp_path))
    ws = openpyxl.load_workbook(path)["Files"]
    assert ws[f"{rl.COL_USER_ID}1"].value == "User ID"
    assert ws[f"{rl.COL_NEW_SUB}1"].value == "New submission"
    assert ws[f"{rl.COL_LATE}2"].value == "Yes"
    assert f"${rl.COL_USER_ID}$2" in ws[f"{rl.COL_NEW_SUB}2"].value
