"""The Excel run log, cell by cell: values, fonts, fills, widths, panes,
filters. Recorded from the code before write_run_log was split (phase 4,
part B); regenerate with PAINTER_SNAPSHOT_RECORD=1 after an intended change."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from painter.storage.runlog_xlsx import RunInfo, write_run_log  # noqa: E402

SNAP = Path(__file__).resolve().parent / "snapshots" / "run_log.json"

ROWS = [
    {"assignment": "DATE Scenario", "assignment_id": 7001, "student": "Doe, Jane",
     "user_id": 501, "section": "A1-8", "all_sections": "A1-8", "due_at": "2026-09-01 03:59",
     "due_source": "everyone", "submitted_at": "2026-08-31 20:00", "attempt": 1,
     "late": False, "late_by": "", "late_policy_status": "", "missing": False,
     "graded_at": "", "score": "", "workflow_state": "submitted", "filename": "essay.pdf",
     "status": "downloaded", "path": "/o/essay.pdf", "extracted_to": ""},
    {"assignment": "DATE Scenario", "assignment_id": 7001, "student": "Roe, Rick",
     "user_id": 502, "section": "A2-8", "all_sections": "A2-8; Lab", "due_at": "",
     "due_source": "section override", "submitted_at": "", "attempt": 2, "late": True,
     "late_by": "1d", "late_policy_status": "late", "missing": False, "graded_at": "",
     "score": 8.5, "workflow_state": "graded", "filename": "analysis.zip",
     "status": "failed: 404", "path": "/o/analysis.zip", "extracted_to": "/o/analysis"},
    {"assignment": "Reflection", "assignment_id": 7002, "student": "Roe, Rick",
     "user_id": 502, "section": "A2-8", "filename": "r.txt", "status": "cached",
     "path": "/o/r.txt", "late": True},
]


def dump(path: Path) -> dict:
    wb = openpyxl.load_workbook(path)
    out = {}
    for ws in wb.worksheets:
        cells = []
        for row in ws.iter_rows():
            for c in row:
                if c.value is None and not c.font.bold:
                    continue
                cells.append([c.coordinate, c.value, c.font.name, bool(c.font.bold),
                              c.fill.fgColor.rgb if c.fill.fill_type else None,
                              bool(c.alignment.wrap_text), c.border.bottom.style])
        out[ws.title] = {
            "cells": cells,
            "widths": {k: v.width for k, v in sorted(ws.column_dimensions.items())},
            "freeze": ws.freeze_panes, "filter": ws.auto_filter.ref,
        }
    return out


@pytest.mark.parametrize("rows", [ROWS, []], ids=["three-rows", "empty"])
def test_run_log_matches_snapshot(tmp_path, rows):
    run = RunInfo(datetime(2026, 11, 12, 9, 30), 100, "https://canvas.test",
                  Path("/o"), (7001,), ("A2",), ("Doe",), "America/New_York")
    path = tmp_path / "log.xlsx"
    write_run_log(rows, path, run)
    got = dump(path)
    key = "three-rows" if rows else "empty"
    snap = json.loads(SNAP.read_text(encoding="utf-8")) if SNAP.exists() else {}
    if os.environ.get("PAINTER_SNAPSHOT_RECORD") == "1":
        snap[key] = got
        SNAP.write_text(json.dumps(snap, indent=1, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8")
        return
    assert json.loads(json.dumps(got, default=str)) == snap[key]
