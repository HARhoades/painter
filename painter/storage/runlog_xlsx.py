"""The Excel log written by a download run."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# --------------------------------------------------------------------------
# Excel run log
# --------------------------------------------------------------------------
# (header, row-key). The formulas below find their columns by key, so
# columns can be added or reordered here freely (review finding 12).
LOG_COLUMNS = [
    ("Assignment", "assignment"), ("Assignment ID", "assignment_id"),
    ("Student", "student"), ("User ID", "user_id"),
    ("Section", "section"), ("All sections", "all_sections"),
    ("Due", "due_at"), ("Due source", "due_source"),
    ("Submitted", "submitted_at"), ("Attempt", "attempt"),
    ("Late", "late_yn"), ("Late by", "late_by"),
    ("Late policy", "late_policy_status"), ("Missing", "missing_yn"),
    ("Graded", "graded_at"), ("Score", "score"),
    ("State", "workflow_state"), ("File", "filename"),
    ("Status", "status"),
    ("Extracted", "extracted_yn"), ("Saved to", "path"),
]


def _letter(n: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA (same as openpyxl's get_column_letter)."""
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def column_of(key: str) -> str:
    """Files-sheet column letter for a LOG_COLUMNS row-key."""
    return _letter([k for _, k in LOG_COLUMNS].index(key) + 1)


COL_ASSIGN_ID, COL_USER_ID, COL_SECTION = (column_of("assignment_id"),
                                           column_of("user_id"), column_of("section"))


COL_LATE, COL_FILE = column_of("late_yn"), column_of("filename")


COL_STATUS = column_of("status")


# helper flags appended after LOG_COLUMNS
COL_NEW_SUB, COL_NEW_STU = _letter(len(LOG_COLUMNS) + 1), _letter(len(LOG_COLUMNS) + 2)


HEAD_FILL = "DDEBF7"


FONT = "Arial"


def _yn(value) -> str:
    return "Yes" if value else "No"


def log_filename(run_started: datetime) -> str:
    """Run-start timestamp, so repeated runs never overwrite each other."""
    return run_started.strftime("submission_log_%Y%m%d_%H%M%S.xlsx")


@dataclass
class RunInfo:
    """What the Run Summary sheet records about a download run."""
    run_started: datetime
    course_id: int
    base_url: str
    out_root: Path
    assignment_ids: tuple = ()
    section_specs: tuple = ()
    student_specs: tuple = ()
    tz_name: str | None = None


def write_run_log(rows: list[dict], path: Path, run: RunInfo) -> None:
    """Write the per-run Excel log: every file, plus student and section rollups.

    Counts are Excel formulas rather than Python-computed constants, so the
    rollups stay correct if you sort, filter, or delete rows on the Files
    sheet while grading.
    """
    from openpyxl import Workbook

    wb = Workbook()
    st = _Styles()
    files = wb.active
    files.title = "Files"
    _files_sheet(files, rows, st)

    # By student -- one row per student who submitted anything this run.
    name_of = {r.get("user_id"): r.get("student", "") for r in rows}
    sect_of = {r.get("user_id"): r.get("section", "") for r in rows}
    all_of = {r.get("user_id"): r.get("all_sections", "") for r in rows}
    _rollup_sheet(wb.create_sheet("By Student"), "User ID",
                  _first_seen(rows, "user_id", None), [
                      ("Student", lambda k: name_of.get(k, "")),
                      ("Section", lambda k: sect_of.get(k, "")),
                      ("All sections", lambda k: all_of.get(k, "")),
                  ], COL_USER_ID, False, st)
    _rollup_sheet(wb.create_sheet("By Section"), "Section",
                  _first_seen(rows, "section", ""), [], COL_SECTION, True, st)
    _summary_sheet(wb.create_sheet("Run Summary"), len(rows), run, st)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


class _Styles:
    """Fonts, fill and border shared by every sheet (openpyxl loaded lazily)."""

    def __init__(self):
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        self.head_font = Font(name=FONT, bold=True)
        self.bold_font = Font(name=FONT, bold=True)
        self.body_font = Font(name=FONT)
        self.fill = PatternFill("solid", fgColor=HEAD_FILL)
        self.box = Border(bottom=Side(style="thin", color="B0B0B0"))
        self.head_align = Alignment(vertical="center", wrap_text=True)

    def header(self, ws, ncols: int) -> None:
        from openpyxl.utils import get_column_letter
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.font, cell.fill, cell.border = self.head_font, self.fill, self.box
            cell.alignment = self.head_align
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}1"

    def body(self, ws, first: int = 2) -> None:
        for row_cells in ws.iter_rows(min_row=first):
            for cell in row_cells:
                if not cell.font.bold:
                    cell.font = self.body_font

    @staticmethod
    def autosize(ws, ncols: int, cap: int = 40) -> None:
        from openpyxl.utils import get_column_letter
        for c in range(1, ncols + 1):
            widest = max((len(str(ws.cell(row=r, column=c).value or ""))
                          for r in range(1, ws.max_row + 1)), default=8)
            ws.column_dimensions[get_column_letter(c)].width = \
                min(max(widest + 2, 9), cap)


def _first_seen(rows: list[dict], key: str, default) -> list:
    """Distinct values of row[key], in the order they first appear."""
    seen, out = set(), []
    for row in rows:
        v = row.get(key, default)
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _file_values(row: dict, r: int) -> list:
    """One Files-sheet row: the LOG_COLUMNS, then the two helper flags."""
    values = []
    for _, key in LOG_COLUMNS:
        if key == "late_yn":
            values.append(_yn(row.get("late")))
        elif key == "missing_yn":
            values.append(_yn(row.get("missing")))
        elif key == "extracted_yn":
            values.append(_yn(row.get("extracted_to")))
        else:
            values.append(row.get(key, ""))
    # Flag the first file of each submission, and the first file of each
    # student, so the rollups can count submissions and headcount with a
    # plain SUMIFS instead of a distinct-count array formula.
    values.append(
        f"=IF(COUNTIFS(${COL_USER_ID}$2:${COL_USER_ID}{r},${COL_USER_ID}{r},"
        f"${COL_ASSIGN_ID}$2:${COL_ASSIGN_ID}{r},${COL_ASSIGN_ID}{r})=1,1,0)")
    values.append(
        f"=IF(COUNTIFS(${COL_USER_ID}$2:${COL_USER_ID}{r},"
        f"${COL_USER_ID}{r})=1,1,0)")
    return values


def _files_sheet(ws, rows: list[dict], st: _Styles) -> None:
    """Sheet 1: one row per attachment."""
    headers = [h for h, _ in LOG_COLUMNS] + ["New submission", "New student"]
    ws.append(headers)
    for r, row in enumerate(rows, start=2):
        ws.append(_file_values(row, r))
    st.header(ws, len(headers))
    st.body(ws)
    st.autosize(ws, len(headers))


def _rollup_sheet(ws, key_header: str, keys: list, extra: list, match_col: str,
                  with_headcount: bool, st: _Styles) -> None:
    """Sheets 2 and 3: per-student or per-section counts, as formulas."""
    from openpyxl.utils import get_column_letter
    head = [key_header] + [h for h, _ in extra]
    if with_headcount:
        head.append("Students")
    head += ["Files", "Submissions", "Late files"]
    ws.append(head)

    for i, key in enumerate(keys, start=2):
        line = [key] + [fn(key) for _, fn in extra]
        if with_headcount:
            line.append(f"=SUMIFS(Files!${COL_NEW_STU}:${COL_NEW_STU},"
                        f"Files!${match_col}:${match_col},$A{i})")
        line += [
            f'=COUNTIFS(Files!${match_col}:${match_col},$A{i},'
            f'Files!${COL_STATUS}:${COL_STATUS},"<>failed*")',
            f"=SUMIFS(Files!${COL_NEW_SUB}:${COL_NEW_SUB},"
            f"Files!${match_col}:${match_col},$A{i})",
            f'=COUNTIFS(Files!${match_col}:${match_col},$A{i},'
            f'Files!${COL_LATE}:${COL_LATE},"Yes")',
        ]
        ws.append(line)

    ncol = len(head)
    if keys:
        last = ws.max_row
        totals = ["Total"] + [""] * len(extra)
        for c in range(2 + len(extra), ncol + 1):
            letter = get_column_letter(c)
            totals.append(f"=SUM({letter}2:{letter}{last})")
        ws.append(totals)
        for cell in ws[ws.max_row]:
            cell.font = st.bold_font
    st.header(ws, ncol)
    st.body(ws)
    st.autosize(ws, ncol)


SUMMARY_NOTES = [
    "Counts are formulas over the Files sheet, so they follow any rows "
    "you delete or filter there.",
    "Due and Late come from Canvas and already account for section and "
    "student date overrides.",
    "New submission / New student on the Files sheet are helper flags "
    "(1 on a student's first file) used by the rollups.",
]


def _summary_sheet(ws, n_rows: int, run: RunInfo, st: _Styles) -> None:
    """Sheet 4: what this run did, and totals as formulas over Files."""
    last_row = max(n_rows + 1, 2)   # keep ranges valid on an empty run
    filters = []
    if run.assignment_ids:
        filters.append("assignments: " + ", ".join(str(a) for a in run.assignment_ids))
    if run.section_specs:
        filters.append("sections: " + ", ".join(run.section_specs))
    if run.student_specs:
        filters.append("students: " + ", ".join(run.student_specs))

    ws.append(["Field", "Value"])
    for label, value in [
        ("Run started", run.run_started.strftime("%Y-%m-%d %H:%M:%S")),
        ("Course ID", run.course_id),
        ("Canvas host", run.base_url),
        ("Filters", "; ".join(filters) or "none (all students)"),
        ("Times shown in", run.tz_name or "UTC, as returned by Canvas"),
        ("Output folder", str(Path(run.out_root).resolve())),
        ("Files downloaded",
         f"=COUNTA(Files!${COL_FILE}$2:${COL_FILE}${last_row})"
         f'-COUNTIF(Files!${COL_STATUS}$2:${COL_STATUS}${last_row},"failed*")'),
        ("Files failed",
         f'=COUNTIF(Files!${COL_STATUS}$2:${COL_STATUS}${last_row},"failed*")'),
        ("Submissions", f"=SUM(Files!${COL_NEW_SUB}$2:${COL_NEW_SUB}${last_row})"),
        ("Students", f"=SUM(Files!${COL_NEW_STU}$2:${COL_NEW_STU}${last_row})"),
        ("Late files",
         f'=COUNTIF(Files!${COL_LATE}$2:${COL_LATE}${last_row},"Yes")'),
    ]:
        ws.append([label, value])
    ws.append([])
    for note in SUMMARY_NOTES:
        ws.append(["Note", note])
    st.header(ws, 2)
    st.body(ws)
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 62
