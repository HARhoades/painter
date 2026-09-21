#!/usr/bin/env python3
"""
Download (and optionally extract) student submission files from a Canvas course.

Setup
-----
1. In Canvas: Account -> Settings -> "+ New Access Token". Copy the token.
2. export CANVAS_API_TOKEN='...'         (Windows: set CANVAS_API_TOKEN=...)
3. pip install requests

Usage
-----
  # list assignments so you can find the IDs
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-assignments

  # download everything for the course (unchanged default)
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --out ./submissions

  # just one assignment, no auto-extract
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --assignment 67890 --no-extract

  # only certain students -- by Canvas ID, SIS ID, login, or name fragment
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --student 884321 --student "Nguyen" --student jdoe2

  # see the roster (IDs, SIS IDs, logins, sections) to build those filters
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-students

  # --list-students honours the same filters: this lists everyone in
  # "Lab 002" plus Nguyen, limited to students assigned assignment 67890
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-students --section "Lab 002" --student Nguyen \
      --assignment 67890

  # whole sections, by ID / SIS ID / name fragment
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --section "Lab 002" --section 45678 --by-section

  # union: everyone in one section, plus one extra student elsewhere
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --section "Lab 002" --student 884321

  # sections as folders, but every file directly inside the section folder
  # (no per-student sub-folders); filenames are prefixed with the student
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --by-section --flat

  # see the sections
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-sections

Posting grades and comments
---------------------------
  # check a grade file against Canvas without posting anything
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --post-grades A2-DATE_Grading-27-1.txt --dry-run

  # post it (shows the plan, then asks for confirmation; --yes skips the prompt)
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --post-grades A2-DATE_Grading-27-1.txt --post-grades A2-DATE_Grading-27-2.txt

  Grade file format (one assignment and one section per file):

    [ASSIGNMENT]
    title=DATE Scenario
    id=280869

    [SECTION]
    title=A2-8
    instructor=Rhoades
    id=27440

    [STUDENT]
    name=Doe, Jane
    id=884321
    grade=9
    comments=Clear analysis. Tighten the
      recommendation section next time.

  * id= may be the Canvas user ID, SIS user ID, or login. If it is blank the
    student is matched by name ("Jane Doe" and "Doe, Jane" both work); if both
    are given they must agree.
  * grade= is whatever Canvas accepts for the assignment's grading type
    (points, 85%, A-, pass/complete...). EX or excused excuses the student.
    Leave it blank to send only a comment.
  * comments= may continue onto following lines. Leave it blank to send
    only a grade.
  * Unused [STUDENT] blocks (every field blank) are ignored.
  * --course is optional here: it is looked up from the section ID.

  Everything is posted through the bulk update_grades endpoint, one request
  per file. Nothing is posted if any file has an error. A comment that is
  already on the student's submission word-for-word is not posted again, so a
  rerun does not duplicate comments. Each run writes grade_post_log_*.csv.

Each download run also writes an Excel log named for the run's start time, e.g.
submission_log_20260819_143005.xlsx, with sheets: Files (one row per
downloaded file), By Student, By Section, and Run Summary. Requires
openpyxl (pip install openpyxl); use --no-xlsx to skip it.

Output layout
-------------
  out/
    01_Homework-1/
      Doe-Jane_884321/
        analysis.zip
        analysis/            <- extracted contents
          main.py
      manifest.csv

  With --by-section --flat:
  out/
    01_Homework-1/
      Lab-002/
        Doe-Jane_884321__analysis.zip
        Doe-Jane_884321__analysis/    <- extracted contents (omit with --no-extract)
        Roe-Rick_884399__analysis.zip
    manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

TOKEN_ENV = "CANVAS_API_TOKEN"
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"}


# --------------------------------------------------------------------------
# Canvas API client
# --------------------------------------------------------------------------
class Canvas:
    def __init__(self, base_url: str, token: str, per_page: int = 100):
        self.base = base_url.rstrip("/")
        self.per_page = per_page
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _request(self, method: str, url: str, retry_server_errors: bool = True,
                 **kw) -> requests.Response:
        """Single request with backoff for throttling and transient 5xx.

        Pass retry_server_errors=False for writes that are not safe to repeat:
        a 5xx does not prove Canvas ignored the request, and resending a bulk
        grade update would post every comment twice. Throttling (403 "rate
        limit") is always retried, since Canvas rejects those unprocessed.
        """
        last = None
        for attempt in range(5):
            resp = self.session.request(method, url, timeout=60, **kw)
            last = resp
            throttled = resp.status_code == 403 and "rate limit" in resp.text.lower()
            server_error = resp.status_code in (500, 502, 503, 504)
            if throttled or (retry_server_errors and server_error):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp
        last.raise_for_status()
        return last

    def paginate(self, path: str, params: dict | None = None):
        """Yield items across all pages, following Canvas's Link headers."""
        params = dict(params or {})
        params.setdefault("per_page", self.per_page)
        url = f"{self.base}/api/v1{path}"
        while url:
            resp = self._request("GET", url, params=params)
            params = None  # the "next" URL already carries the query string
            payload = resp.json()
            if isinstance(payload, list):
                yield from payload
            else:
                yield payload
            url = resp.links.get("next", {}).get("url")

    def assignments(self, course_id: int):
        """Assignments, including per-section and per-student date overrides.

        assignment["due_at"] alone is only the "Everyone" date. all_dates adds
        an AssignmentDate per override, but identifies it only by title, so
        overrides is requested too -- that is what carries course_section_id
        and student_ids.
        """
        return list(self.paginate(f"/courses/{course_id}/assignments",
                                  {"order_by": "position",
                                   "include[]": ["all_dates", "overrides"]}))

    def sections(self, course_id: int):
        """Sections in the course.

        Note: include[]=students is deliberately NOT used here. Canvas caps
        that nested collection and does not paginate it, so it silently
        truncates in large courses. Section membership comes from the
        enrollments endpoint below instead, which does paginate.
        """
        return list(self.paginate(f"/courses/{course_id}/sections",
                                  {"include[]": ["total_students"]}))

    def student_enrollments(self, course_id: int):
        """One record per student-per-section, each carrying course_section_id.

        A student in two sections yields two enrollments. sis_user_id and
        login_id appear only if your role may view SIS data; treated as
        optional throughout.
        """
        return list(self.paginate(
            f"/courses/{course_id}/enrollments",
            {"type[]": "StudentEnrollment", "state[]": ["active", "invited"]},
        ))

    def submissions(self, course_id: int, assignment_id: int, include_history=False):
        include = ["user"] + (["submission_history"] if include_history else [])
        return list(self.paginate(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions",
            {"include[]": include},
        ))

    # ---- grading -----------------------------------------------------------
    def section(self, section_id: int) -> dict:
        """A single section; carries course_id, so a grade file needs no --course."""
        return self._request("GET", f"{self.base}/api/v1/sections/{section_id}").json()

    def assignment(self, course_id: int, assignment_id: int) -> dict:
        return self._request(
            "GET", f"{self.base}/api/v1/courses/{course_id}/assignments/{assignment_id}"
        ).json()

    def submissions_with_comments(self, course_id: int, assignment_id: int):
        """Every submission's current grade plus its comment thread."""
        return list(self.paginate(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions",
            {"include[]": ["submission_comments"]},
        ))

    def bulk_update_grades(self, course_id: int, assignment_id: int,
                           grade_data: dict[int, dict[str, str]]) -> dict:
        """POST .../submissions/update_grades and return the Progress object.

        grade_data maps Canvas user ID -> {"posted_grade": ..., "excuse": ...,
        "text_comment": ...}; each becomes a grade_data[<id>][<key>] form field.
        The update runs as a background job; see wait_for_progress().
        """
        form = {f"grade_data[{uid}][{key}]": value
                for uid, fields in grade_data.items()
                for key, value in fields.items()}
        url = (f"{self.base}/api/v1/courses/{course_id}/assignments/"
               f"{assignment_id}/submissions/update_grades")
        return self._request("POST", url, data=form,
                             retry_server_errors=False).json()

    def wait_for_progress(self, progress: dict, timeout: float = 300.0,
                          interval: float = 2.0) -> dict:
        """Poll a Progress object until it completes, fails, or times out."""
        url = progress.get("url") or f"{self.base}/api/v1/progress/{progress['id']}"
        deadline = time.monotonic() + timeout
        while progress.get("workflow_state") not in ("completed", "failed"):
            if time.monotonic() > deadline:
                break
            time.sleep(interval)
            progress = self._request("GET", url).json()
        return progress


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
def parse_ts(value: str | None):
    """Canvas returns ISO 8601 in UTC, e.g. 2026-03-04T23:59:00Z."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_ts(value: str | None, tz=None) -> str:
    """Render a Canvas timestamp, optionally converted to a local zone."""
    dt = parse_ts(value)
    if dt is None:
        return ""
    if tz is not None:
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M")


def fmt_lateness(seconds) -> str:
    """seconds_late -> '2d 3h 14m'. Canvas reports 0 when on time."""
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return " ".join(p for p in (f"{d}d" if d else "", f"{h}h" if h else "",
                                f"{m}m" if m else "") if p) or "<1m"


class DueDates:
    """Effective due date per student for one assignment.

    Precedence follows Canvas: an ad-hoc (per-student) override beats a
    section override, which beats the base "Everyone" date. If a student sits
    in two overridden sections Canvas applies the most lenient date, so the
    latest of the candidates is used here.
    """

    def __init__(self, assignment: dict):
        self.base = assignment.get("due_at")
        self.by_section: dict[int, str | None] = {}
        self.by_user: dict[int, str | None] = {}

        for date in assignment.get("all_dates") or []:
            if date.get("base"):
                self.base = date.get("due_at")

        for ov in assignment.get("overrides") or []:
            due = ov.get("due_at")
            if "course_section_id" in ov and ov["course_section_id"]:
                self.by_section[ov["course_section_id"]] = due
            for uid in ov.get("student_ids") or []:
                self.by_user[uid] = due

    def effective(self, user_id: int, section_ids: list[int]) -> tuple[str | None, str]:
        """Returns (due_at, source-label)."""
        if user_id in self.by_user:
            return self.by_user[user_id], "student override"

        candidates = [(self.by_section[s], s) for s in section_ids
                      if s in self.by_section]
        if candidates:
            if any(due is None for due, _ in candidates):
                return None, "section override (no due date)"
            latest = max(candidates, key=lambda c: parse_ts(c[0]))
            label = "section override"
            if len(candidates) > 1:
                label += " (most lenient of %d)" % len(candidates)
            return latest[0], label

        return self.base, "everyone"



# --------------------------------------------------------------------------
# Excel run log
# --------------------------------------------------------------------------
# (header, row-key). The order here defines the column letters the formulas
# below rely on, so inserting a column means updating the COL_* constants too.
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
    ("Extracted", "extracted_yn"), ("Saved to", "path"),
]
COL_ASSIGN_ID, COL_USER_ID, COL_SECTION = "B", "D", "E"
COL_LATE, COL_FILE = "K", "R"
COL_NEW_SUB, COL_NEW_STU = "U", "V"   # helper flags appended after the above

HEAD_FILL = "DDEBF7"
FONT = "Arial"


def _yn(value) -> str:
    return "Yes" if value else "No"


def log_filename(run_started: datetime) -> str:
    """Run-start timestamp, so repeated runs never overwrite each other."""
    return run_started.strftime("submission_log_%Y%m%d_%H%M%S.xlsx")


def write_run_log(rows: list[dict], path: Path, run_started: datetime,
                  args) -> None:
    """Write the per-run Excel log: every file, plus student and section rollups.

    Counts are Excel formulas rather than Python-computed constants, so the
    rollups stay correct if you sort, filter, or delete rows on the Files
    sheet while grading.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_font = Font(name=FONT, bold=True)
    bold_font = Font(name=FONT, bold=True)
    body_font = Font(name=FONT)
    fill = PatternFill("solid", fgColor=HEAD_FILL)
    box = Border(bottom=Side(style="thin", color="B0B0B0"))
    last_row = max(len(rows) + 1, 2)   # keep ranges valid on an empty run

    def style_header(ws, ncols: int) -> None:
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.font, cell.fill, cell.border = head_font, fill, box
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}1"

    def autosize(ws, ncols: int, cap: int = 40) -> None:
        for c in range(1, ncols + 1):
            widest = max((len(str(ws.cell(row=r, column=c).value or ""))
                          for r in range(1, ws.max_row + 1)), default=8)
            ws.column_dimensions[get_column_letter(c)].width = \
                min(max(widest + 2, 9), cap)

    def body(ws, first: int = 2) -> None:
        for row_cells in ws.iter_rows(min_row=first):
            for cell in row_cells:
                if not cell.font.bold:
                    cell.font = body_font

    # ---- Sheet 1: one row per downloaded file --------------------------
    files = wb.active
    files.title = "Files"
    headers = [h for h, _ in LOG_COLUMNS] + ["New submission", "New student"]
    files.append(headers)

    for r, row in enumerate(rows, start=2):
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
        files.append(values)

    ncols = len(headers)
    style_header(files, ncols)
    body(files)
    autosize(files, ncols)

    # ---- Sheets 2 and 3: rollups ---------------------------------------
    def rollup(title: str, key_header: str, keys: list, extra: list,
               match_col: str, with_headcount: bool):
        ws = wb.create_sheet(title)
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
                f"=COUNTIFS(Files!${match_col}:${match_col},$A{i})",
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
            first_num = 2 + len(extra)
            for c in range(first_num, ncol + 1):
                letter = get_column_letter(c)
                totals.append(f"=SUM({letter}2:{letter}{last})")
            ws.append(totals)
            for cell in ws[ws.max_row]:
                cell.font = bold_font
        style_header(ws, ncol)
        body(ws)
        autosize(ws, ncol)
        return ws

    # By student -- one row per student who submitted anything this run.
    seen, student_ids = set(), []
    for row in rows:
        uid = row.get("user_id")
        if uid not in seen:
            seen.add(uid)
            student_ids.append(uid)
    name_of = {r.get("user_id"): r.get("student", "") for r in rows}
    sect_of = {r.get("user_id"): r.get("section", "") for r in rows}
    all_of = {r.get("user_id"): r.get("all_sections", "") for r in rows}
    rollup("By Student", "User ID", student_ids, [
        ("Student", lambda k: name_of.get(k, "")),
        ("Section", lambda k: sect_of.get(k, "")),
        ("All sections", lambda k: all_of.get(k, "")),
    ], COL_USER_ID, with_headcount=False)

    # By section
    seen, section_names = set(), []
    for row in rows:
        name = row.get("section", "")
        if name not in seen:
            seen.add(name)
            section_names.append(name)
    rollup("By Section", "Section", section_names, [],
           COL_SECTION, with_headcount=True)

    # ---- Sheet 4: what this run actually did ---------------------------
    info = wb.create_sheet("Run Summary")
    filters = []
    if args.assignment:
        filters.append("assignments: " + ", ".join(str(a) for a in args.assignment))
    if args.section:
        filters.append("sections: " + ", ".join(args.section))
    if args.student:
        filters.append("students: " + ", ".join(args.student))

    info.append(["Field", "Value"])
    for label, value in [
        ("Run started", run_started.strftime("%Y-%m-%d %H:%M:%S")),
        ("Course ID", args.course),
        ("Canvas host", args.base_url),
        ("Filters", "; ".join(filters) or "none (all students)"),
        ("Times shown in", args.tz or "UTC, as returned by Canvas"),
        ("Output folder", str(Path(args.out).resolve())),
        ("Files downloaded", f"=COUNTA(Files!${COL_FILE}$2:${COL_FILE}${last_row})"),
        ("Submissions", f"=SUM(Files!${COL_NEW_SUB}$2:${COL_NEW_SUB}${last_row})"),
        ("Students", f"=SUM(Files!${COL_NEW_STU}$2:${COL_NEW_STU}${last_row})"),
        ("Late files",
         f'=COUNTIF(Files!${COL_LATE}$2:${COL_LATE}${last_row},"Yes")'),
    ]:
        info.append([label, value])
    info.append([])
    for note in [
        "Counts are formulas over the Files sheet, so they follow any rows "
        "you delete or filter there.",
        "Due and Late come from Canvas and already account for section and "
        "student date overrides.",
        "New submission / New student on the Files sheet are helper flags "
        "(1 on a student's first file) used by the rollups.",
    ]:
        info.append(["Note", note])
    style_header(info, 2)
    body(info)
    info.column_dimensions["A"].width = 20
    info.column_dimensions["B"].width = 62

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------
def slug(text: str, maxlen: int = 60) -> str:
    """Make a string safe for use as a single path component."""
    text = re.sub(r"[^\w\s.,-]", "", text or "").strip()
    text = re.sub(r"[\s,]+", "-", text)
    return text[:maxlen].strip("-.") or "unnamed"


def safe_filename(name: str) -> str:
    """Strip any directory components a client may have snuck into a filename."""
    name = os.path.basename(name.replace("\\", "/"))
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name or "file"


def download(url: str, dest: Path, expected_size: int | None = None) -> bool:
    """Stream a file to disk. Returns True if it was newly downloaded."""
    if dest.exists() and (expected_size is None or dest.stat().st_size == expected_size):
        return False  # already have it — makes reruns cheap
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    # Canvas attachment URLs are pre-signed and redirect to blob storage;
    # do NOT send the Bearer header along, some backends reject it.
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    tmp.replace(dest)
    return True


def extract(archive: Path, dest: Path) -> bool:
    """Extract a zip/tar into dest, refusing any member that escapes dest."""
    dest.mkdir(parents=True, exist_ok=True)
    dest_res = dest.resolve()

    def is_inside(target: Path) -> bool:
        try:
            target.resolve().relative_to(dest_res)
            return True
        except ValueError:
            return False

    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    name = member.filename
                    if name.startswith("__MACOSX/") or name.endswith("/"):
                        continue
                    target = dest / name
                    if not is_inside(target):
                        print(f"      ! skipped unsafe path in archive: {name}")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as out:
                        out.write(src.read())
            return True

        if tarfile.is_tarfile(archive):
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    if not member.isreg():
                        continue
                    target = dest / member.name
                    if not is_inside(target):
                        print(f"      ! skipped unsafe path in archive: {member.name}")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tf.extractfile(member) as src, open(target, "wb") as out:
                        out.write(src.read())
            return True
    except Exception as exc:
        print(f"      ! could not extract {archive.name}: {exc}")
    return False


# --------------------------------------------------------------------------
# Main workflow
# --------------------------------------------------------------------------
class Roster:
    """Course membership, joined across the sections and enrollments endpoints.

    Canvas submission objects carry no section field, so the only way to know
    which section a submission belongs to is to build this map first and look
    up by user_id.
    """

    def __init__(self, sections: list[dict], enrollments: list[dict]):
        self.sections = sections
        self.section_by_id = {s["id"]: s for s in sections}
        self.users: dict[int, dict] = {}
        self.sections_of_user: dict[int, list[int]] = {}
        self.users_of_section: dict[int, set[int]] = {s["id"]: set() for s in sections}

        for enr in enrollments:
            uid = enr.get("user_id")
            if uid is None:
                continue
            user = dict(enr.get("user") or {})
            user.setdefault("id", uid)
            # SIS/login live on the enrollment, not the nested user object.
            if enr.get("sis_user_id"):
                user.setdefault("sis_user_id", enr["sis_user_id"])
            if enr.get("user", {}).get("login_id"):
                user.setdefault("login_id", enr["user"]["login_id"])
            self.users.setdefault(uid, user)

            sid = enr.get("course_section_id")
            if sid is None:
                continue
            self.sections_of_user.setdefault(uid, [])
            if sid not in self.sections_of_user[uid]:
                self.sections_of_user[uid].append(sid)
            self.users_of_section.setdefault(sid, set()).add(uid)

    def section_names(self, user_id: int) -> list[str]:
        return [self.section_by_id.get(s, {}).get("name", str(s))
                for s in self.sections_of_user.get(user_id, [])]

    def primary_section(self, user_id: int, preferred: set[int] | None) -> dict | None:
        """The section to file a student under when writing per-section folders.

        If a student is in several sections, prefer one the user actually
        selected; otherwise fall back to their first enrollment.
        """
        ids = self.sections_of_user.get(user_id, [])
        if not ids:
            return None
        if preferred:
            for sid in ids:
                if sid in preferred:
                    return self.section_by_id.get(sid)
        return self.section_by_id.get(ids[0])


def match_section(spec: str, section: dict) -> bool:
    """Does one --section spec identify this section?

    Exact match on Canvas section ID or SIS section ID, otherwise a
    case-insensitive substring match on the section name. Section names are
    not unique in Canvas, so ID matching is checked first.
    """
    spec = spec.strip()
    exact = {str(section.get("id", "")), str(section.get("sis_section_id") or "")}
    if spec and spec in exact:
        return True
    return spec.casefold() in (section.get("name") or "").casefold()


def resolve_sections(roster: Roster, specs: list[str]) -> set[int]:
    """Turn --section specs into section IDs, failing loudly on typos."""
    selected: set[int] = set()
    unmatched: list[str] = []

    for spec in specs:
        hits = [s for s in roster.sections if match_section(spec, s)]
        if not hits:
            unmatched.append(spec)
            continue
        if len(hits) > 1:
            names = ", ".join(f"{s.get('name')} ({s['id']})" for s in hits)
            print(f"  note: '{spec}' matched {len(hits)} sections -> {names}")
        for s in hits:
            selected.add(s["id"])

    if unmatched:
        raise SystemExit(
            "No section match for: " + ", ".join(repr(s) for s in unmatched) +
            "\nRun with --list-sections to see valid IDs and names."
        )
    return selected


def match_student(spec: str, user: dict) -> bool:
    """Does one --student spec identify this roster entry?

    Exact match on Canvas ID / SIS ID / login, otherwise a case-insensitive
    substring match on either form of the name.
    """
    spec = spec.strip()
    exact = {
        str(user.get("id", "")),
        str(user.get("sis_user_id") or ""),
        str(user.get("login_id") or ""),
    }
    if spec in exact and spec:
        return True
    needle = spec.casefold()
    haystacks = (user.get("name") or "", user.get("sortable_name") or "")
    return any(needle in h.casefold() for h in haystacks)


def resolve_students(roster: Roster, specs: list[str]) -> set[int]:
    """Turn --student specs into user IDs, failing loudly on typos."""
    selected: set[int] = set()
    unmatched: list[str] = []

    for spec in specs:
        hits = [u for u in roster.users.values() if match_student(spec, u)]
        if not hits:
            unmatched.append(spec)
            continue
        if len(hits) > 1:
            names = ", ".join(f"{u.get('sortable_name')} ({u['id']})" for u in hits)
            print(f"  note: '{spec}' matched {len(hits)} students -> {names}")
        for u in hits:
            selected.add(u["id"])

    if unmatched:
        raise SystemExit(
            "No roster match for: " + ", ".join(repr(s) for s in unmatched) +
            "\nRun with --list-students to see valid IDs and names."
        )
    return selected


def select_students(roster: Roster, args) -> tuple[set[int] | None, set[int]]:
    """Apply --section and --student, as a union.

    Returns (student_ids, section_ids). student_ids is None when neither
    filter was given, meaning "everyone". Shared by the download pass and
    --list-students so both select exactly the same people.
    """
    if not (args.student or args.section):
        return None, set()
    student_ids: set[int] = set()
    section_ids: set[int] = set()
    if args.section:
        section_ids = resolve_sections(roster, args.section)
        for sid in section_ids:
            student_ids |= roster.users_of_section.get(sid, set())
        names = ", ".join(roster.section_by_id[s].get("name", str(s))
                          for s in sorted(section_ids))
        print(f"Sections: {names}", file=sys.stderr)
    if args.student:
        student_ids |= resolve_students(roster, args.student)
    return student_ids, section_ids


def assigned_students(canvas: Canvas, course_id: int,
                      assignment_ids: list[int]) -> set[int]:
    """Students who have the given assignment(s), i.e. a submission record.

    Canvas creates a submission record for every student an assignment is
    assigned to, whether or not they have turned anything in, so this also
    respects "assign to" overrides. With several assignments, a student
    who has any of them is included.
    """
    users: set[int] = set()
    for aid in assignment_ids:
        try:
            for sub in canvas.paginate(
                    f"/courses/{course_id}/assignments/{aid}/submissions"):
                if sub.get("user_id") is not None:
                    users.add(sub["user_id"])
        except requests.HTTPError as exc:
            raise SystemExit(f"Assignment {aid} not found in course {course_id} "
                             f"({exc}).\nRun with --list-assignments to see valid IDs.")
    return users


def student_dir_name(sub: dict) -> str:
    user = sub.get("user") or {}
    name = user.get("sortable_name") or user.get("name") or "Anonymous"
    return f"{slug(name, 45)}_{sub.get('user_id', 'unknown')}"


def flat_filename(sub: dict, fname: str) -> str:
    """Prefix a filename with the student so a shared folder never collides.

    Reuses student_dir_name(), so the prefix matches the folder name the
    default layout would have used, including the Canvas user ID that keeps
    two students with the same name apart.
    """
    return f"{student_dir_name(sub)}__{fname}"


def collect_attachments(sub: dict, include_history: bool) -> list[dict]:
    """Attachments for a submission, de-duplicated by attachment id.

    Group assignments repeat the same attachment for every member, and
    resubmissions live in submission_history rather than the top level.
    """
    seen, out = set(), []
    buckets = [sub]
    if include_history:
        buckets += sub.get("submission_history") or []
    for bucket in buckets:
        for att in bucket.get("attachments") or []:
            aid = att.get("id")
            if aid in seen:
                continue
            seen.add(aid)
            out.append(att)
    return out


# --------------------------------------------------------------------------
# Posting grades and comments
# --------------------------------------------------------------------------
GRADE_FILE_KEYS = {
    "ASSIGNMENT": ("title", "id"),
    "SECTION": ("title", "instructor", "id"),
    "STUDENT": ("name", "id", "grade", "comments"),
}
EXCUSED_WORDS = {"ex", "excused", "excuse"}
PASS_FAIL_WORDS = {"pass", "fail", "complete", "incomplete"}


class GradeFileError(Exception):
    def __init__(self, path: Path, line: int | None, message: str):
        where = f"{path.name}:{line}" if line else path.name
        super().__init__(f"{where}: {message}")


@dataclass
class GradeEntry:
    line: int
    name: str
    id: str
    grade: str
    comments: str


@dataclass
class GradeFile:
    path: Path
    assignment_id: int
    assignment_title: str
    section_id: int | None
    section_title: str
    instructor: str
    entries: list[GradeEntry]
    blank_entries: int = 0     # named students with no grade and no comment


@dataclass
class PlannedGrade:
    entry: GradeEntry
    user_id: int
    student: str
    fields: dict[str, str]     # what goes into grade_data[<user_id>]
    grade_before: str
    comment_skipped: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class GradePlan:
    source: GradeFile
    course_id: int
    assignment: dict
    section: dict | None
    items: list[PlannedGrade]
    notes: list[str] = field(default_factory=list)

    @property
    def to_send(self) -> list[PlannedGrade]:
        return [it for it in self.items if it.fields]


def parse_grade_file(path: Path) -> GradeFile:
    """Read a grade file of [ASSIGNMENT], [SECTION] and [STUDENT] blocks.

    A line that does not start with a key known to its block continues the
    previous comments= value, so comments can span lines. Anything else
    unexpected is an error, reported with its line number.
    """
    blocks: list[dict] = []
    current: dict | None = None
    last_key = None

    text = path.read_text(encoding="utf-8-sig")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()

        header = re.fullmatch(r"\[\s*([A-Za-z]+)\s*\]", stripped)
        if header:
            kind = header.group(1).upper()
            if kind not in GRADE_FILE_KEYS:
                raise GradeFileError(path, lineno, f"unknown block [{header.group(1)}]")
            current = {"_kind": kind, "_line": lineno}
            blocks.append(current)
            last_key = None
            continue

        if current is None:
            if stripped:
                raise GradeFileError(path, lineno, "text before the first [BLOCK] header")
            continue

        kv = re.match(r"\s*([A-Za-z_]+)\s*=(.*)$", line)
        if kv and kv.group(1).lower() in GRADE_FILE_KEYS[current["_kind"]]:
            key = kv.group(1).lower()
            if key in current:
                raise GradeFileError(path, lineno, f"'{key}' appears twice in one block")
            current[key] = kv.group(2).strip()
            last_key = key
            continue

        if last_key == "comments":
            # Indentation is for readability in the file; don't send it.
            current["comments"] += "\n" + stripped
            continue
        if stripped:
            raise GradeFileError(path, lineno, f"unexpected line: {stripped!r}")

    def int_field(block: dict, key: str, required: bool) -> int | None:
        value = (block.get(key) or "").strip()
        if not value:
            if required:
                raise GradeFileError(path, block["_line"],
                                     f"[{block['_kind']}] needs {key}=")
            return None
        try:
            return int(value)
        except ValueError:
            raise GradeFileError(path, block["_line"],
                                 f"[{block['_kind']}] {key}={value!r} is not a number")

    assigns = [b for b in blocks if b["_kind"] == "ASSIGNMENT"]
    if len(assigns) != 1:
        raise GradeFileError(path, None, f"expected one [ASSIGNMENT] block, found {len(assigns)}")
    sections = [b for b in blocks if b["_kind"] == "SECTION"]
    if len(sections) > 1:
        raise GradeFileError(path, None, f"expected at most one [SECTION] block, found {len(sections)}")
    a = assigns[0]
    s = sections[0] if sections else {}

    entries, blank = [], 0
    for b in blocks:
        if b["_kind"] != "STUDENT":
            continue
        e = GradeEntry(line=b["_line"],
                       name=(b.get("name") or "").strip(),
                       id=(b.get("id") or "").strip(),
                       grade=(b.get("grade") or "").strip(),
                       comments=(b.get("comments") or "").strip())
        if not (e.name or e.id):
            if e.grade or e.comments:
                raise GradeFileError(path, e.line,
                                     "student has a grade or comment but no name or id")
            continue                      # unused template slot
        if not (e.grade or e.comments):
            blank += 1
            continue
        entries.append(e)

    return GradeFile(
        path=path,
        assignment_id=int_field(a, "id", required=True),
        assignment_title=(a.get("title") or "").strip(),
        section_id=int_field(s, "id", required=False) if s else None,
        section_title=(s.get("title") or "").strip(),
        instructor=(s.get("instructor") or "").strip(),
        entries=entries,
        blank_entries=blank,
    )


def _name_tokens(text: str | None) -> set[str]:
    return set(re.findall(r"\w+", (text or "").casefold()))


def name_matches(name: str, user: dict) -> bool:
    """Every word of `name` appears in the student's Canvas name.

    Word-based, so "Jane Doe", "Doe, Jane" and "Doe Jane" all match, and a
    name without the middle name still matches one that has it.
    """
    want = _name_tokens(name)
    if not want:
        return False
    have = set().union(*(_name_tokens(user.get(k))
                         for k in ("name", "sortable_name", "short_name")))
    return want <= have


def resolve_grade_entry(roster: Roster, entry: GradeEntry,
                        section_id: int | None) -> dict:
    """Find the roster user a [STUDENT] block refers to, or raise LookupError."""
    def label(u: dict) -> str:
        return f"{u.get('sortable_name') or u.get('name')} ({u['id']})"

    if entry.id:
        hits = [u for u in roster.users.values()
                if entry.id in {str(u.get("id", "")),
                                str(u.get("sis_user_id") or ""),
                                str(u.get("login_id") or "")}]
        if not hits:
            raise LookupError(f"no student in the course has id {entry.id}")
        if len(hits) > 1:
            raise LookupError(f"id {entry.id} matches several students: "
                              + ", ".join(label(u) for u in hits))
        user = hits[0]
        if entry.name and not name_matches(entry.name, user):
            raise LookupError(f"id {entry.id} is {label(user)}, not {entry.name!r}")
        return user

    hits = [u for u in roster.users.values() if name_matches(entry.name, u)]
    if len(hits) > 1 and section_id:
        in_section = [u for u in hits
                      if section_id in roster.sections_of_user.get(u["id"], [])]
        if in_section:
            hits = in_section
    if not hits:
        raise LookupError(f"no student named {entry.name!r} in the course")
    if len(hits) > 1:
        raise LookupError(f"{entry.name!r} matches several students ("
                          + ", ".join(label(u) for u in hits) + "); add id=")
    return hits[0]


def grade_fields(entry: GradeEntry, assignment: dict) -> tuple[dict[str, str], list[str]]:
    """The grade_data fields for one student, checked against the grading type.

    Raises ValueError for a grade Canvas would reject or misread; returns
    warnings for grades that are legal but worth a second look.
    """
    fields: dict[str, str] = {}
    warnings: list[str] = []
    grade = entry.grade
    gtype = assignment.get("grading_type") or "points"

    if grade:
        if grade.casefold() in EXCUSED_WORDS:
            fields["excuse"] = "true"
        elif gtype == "not_graded":
            raise ValueError("the assignment is set to 'not graded', but a grade was given")
        elif gtype in ("points", "percent"):
            m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(%?)", grade)
            if not m:
                raise ValueError(f"grade {grade!r} is not a number "
                                 f"(the assignment is graded by {gtype})")
            value = float(m.group(1))
            pts = assignment.get("points_possible")
            if value < 0:
                warnings.append(f"grade {grade} is negative")
            elif gtype == "points" and not m.group(2) and pts is not None and value > pts:
                warnings.append(f"grade {grade} is above points possible ({pts:g})")
            elif (gtype == "percent" or m.group(2)) and value > 100:
                warnings.append(f"grade {grade} is above 100%")
            fields["posted_grade"] = m.group(1) + m.group(2)
        elif gtype == "pass_fail":
            if grade.casefold() not in PASS_FAIL_WORDS:
                raise ValueError(f"grade {grade!r} must be one of "
                                 + "/".join(sorted(PASS_FAIL_WORDS)))
            fields["posted_grade"] = grade.casefold()
        else:
            # letter_grade / gpa_scale: Canvas checks it against the grading scheme
            fields["posted_grade"] = grade

    if entry.comments:
        fields["text_comment"] = entry.comments
    return fields, warnings


def _norm_comment(text: str | None) -> str:
    return " ".join((text or "").split())


def _grade_before(sub: dict | None) -> str:
    if not sub:
        return ""
    if sub.get("excused"):
        return "EXCUSED"
    return str(sub.get("entered_grade") or sub.get("grade") or "")


def plan_grade_file(canvas: Canvas, gf: GradeFile, course_id: int | None,
                    rosters: dict[int, Roster],
                    allow_duplicate_comments: bool) -> tuple[GradePlan | None, list[str]]:
    """Resolve a parsed grade file against Canvas. Reads only; posts nothing."""
    errors: list[str] = []
    where = gf.path.name

    def err(msg: str, entry: GradeEntry | None = None) -> None:
        errors.append(f"{where}:{entry.line}: {msg}" if entry else f"{where}: {msg}")

    # Course: from --course, else from the section.
    if course_id is None:
        if gf.section_id is None:
            err("no [SECTION] id to find the course from; pass --course")
            return None, errors
        try:
            course_id = canvas.section(gf.section_id)["course_id"]
        except requests.HTTPError as exc:
            err(f"could not look up section {gf.section_id}: {exc}")
            return None, errors

    if course_id not in rosters:
        rosters[course_id] = Roster(canvas.sections(course_id),
                                    canvas.student_enrollments(course_id))
    roster = rosters[course_id]
    notes: list[str] = []

    section = None
    if gf.section_id is not None:
        section = roster.section_by_id.get(gf.section_id)
        if section is None:
            err(f"section {gf.section_id} is not in course {course_id}")
        elif gf.section_title and \
                gf.section_title.casefold() not in (section.get("name") or "").casefold():
            notes.append(f"file says section {gf.section_title!r}, "
                         f"Canvas calls it {section.get('name')!r}")

    try:
        assignment = canvas.assignment(course_id, gf.assignment_id)
    except requests.HTTPError as exc:
        err(f"assignment {gf.assignment_id} not found in course {course_id} ({exc})")
        return None, errors

    if gf.assignment_title and \
            gf.assignment_title.casefold() not in (assignment.get("name") or "").casefold():
        notes.append(f"file says assignment {gf.assignment_title!r}, "
                     f"Canvas calls it {assignment.get('name')!r}")
    if assignment.get("published") is False:
        err("the assignment is unpublished; Canvas will not accept grades for it")
    if assignment.get("post_manually"):
        notes.append("grades are posted manually for this assignment: students "
                     "will not see these grades or comments until you post them")
    if assignment.get("moderated_grading"):
        notes.append("moderated assignment: grades are saved as provisional grades")
    if assignment.get("anonymous_grading"):
        notes.append("anonymous grading is on for this assignment")
    if gf.blank_entries:
        notes.append(f"{gf.blank_entries} named student(s) have no grade or comment; skipped")

    existing = {s.get("user_id"): s
                for s in canvas.submissions_with_comments(course_id, gf.assignment_id)}

    items: list[PlannedGrade] = []
    seen: dict[int, int] = {}
    for entry in gf.entries:
        try:
            user = resolve_grade_entry(roster, entry, gf.section_id)
        except LookupError as exc:
            err(str(exc), entry)
            continue
        uid = user["id"]
        if uid in seen:
            err(f"{user.get('sortable_name')} is listed twice (also line {seen[uid]})", entry)
            continue
        seen[uid] = entry.line

        try:
            fields, warnings = grade_fields(entry, assignment)
        except ValueError as exc:
            err(str(exc), entry)
            continue

        sub = existing.get(uid)
        if sub is None:
            err(f"{user.get('sortable_name')} has no submission record for this "
                "assignment (not assigned to them?)", entry)
            continue

        if gf.section_id and section and \
                gf.section_id not in roster.sections_of_user.get(uid, []):
            warnings.append(f"not enrolled in section {section.get('name')}")

        skipped = False
        if "text_comment" in fields and not allow_duplicate_comments:
            posted = {_norm_comment(c.get("comment"))
                      for c in sub.get("submission_comments") or []}
            if _norm_comment(fields["text_comment"]) in posted:
                del fields["text_comment"]
                skipped = True

        before = _grade_before(sub)
        if before and "posted_grade" in fields and \
                before.casefold() != fields["posted_grade"].casefold():
            warnings.append(f"replaces existing grade {before}")

        items.append(PlannedGrade(entry=entry, user_id=uid,
                                  student=user.get("sortable_name") or user.get("name") or "",
                                  fields=fields, grade_before=before,
                                  comment_skipped=skipped, warnings=warnings))

    return GradePlan(source=gf, course_id=course_id, assignment=assignment,
                     section=section, items=items, notes=notes), errors


def _preview(text: str, width: int = 60) -> str:
    one_line = " ".join(text.split())
    return repr(one_line if len(one_line) <= width else one_line[:width - 1] + "…")


def print_grade_plan(plan: GradePlan) -> None:
    a, gf = plan.assignment, plan.source
    scale = a.get("grading_type") or ""
    if scale == "points" and a.get("points_possible") is not None:
        scale = f"points, out of {a['points_possible']:g}"
    print(f"\n{gf.path.name}  (course {plan.course_id})")
    print(f"  Assignment {a['id']}  {a.get('name', '')}  ({scale})")
    if plan.section:
        inst = f"  instructor {gf.instructor}" if gf.instructor else ""
        print(f"  Section    {plan.section['id']}  {plan.section.get('name', '')}{inst}")
    for note in plan.notes:
        print(f"  note: {note}")
    for it in plan.items:
        parts = []
        if "excuse" in it.fields:
            parts.append(f"grade {it.grade_before or '-'} -> EXCUSED")
        elif "posted_grade" in it.fields:
            parts.append(f"grade {it.grade_before or '-'} -> {it.fields['posted_grade']}")
        if "text_comment" in it.fields:
            parts.append(f"comment {_preview(it.fields['text_comment'])}")
        elif it.comment_skipped:
            parts.append("comment already on Canvas, not re-sent")
        if not it.fields:
            parts.append("(nothing to send)")
        print(f"    {it.student} ({it.user_id}):  " + "   ".join(parts))
        for w in it.warnings:
            print(f"      ! {w}")
    print(f"  {len(plan.to_send)} student(s) to update")


def verify_posted(it: PlannedGrade, sub: dict | None, gtype: str) -> list[str]:
    """Compare what Canvas now holds against what was sent."""
    if sub is None:
        return ["submission not found after posting"]
    problems = []
    f = it.fields
    if "excuse" in f and not sub.get("excused"):
        problems.append("not marked excused")
    if "posted_grade" in f:
        if sub.get("entered_grade") is None and sub.get("grade") is None:
            problems.append("no grade recorded")
        elif gtype == "points" and not f["posted_grade"].endswith("%"):
            # entered_score is before any late penalty; score is after it.
            got = sub.get("entered_score", sub.get("score"))
            if got is None or abs(float(got) - float(f["posted_grade"])) > 1e-6:
                problems.append(f"score is {got}, expected {f['posted_grade']}")
    if "text_comment" in f:
        posted = {_norm_comment(c.get("comment"))
                  for c in sub.get("submission_comments") or []}
        if _norm_comment(f["text_comment"]) not in posted:
            problems.append("comment not found")
    return problems


def post_grade_plan(canvas: Canvas, plan: GradePlan) -> list[dict]:
    """One bulk update_grades call for the file, then a read-back check."""
    a = plan.assignment
    to_send = plan.to_send
    print(f"\nPosting {len(to_send)} update(s) for {a.get('name')} "
          f"({plan.source.path.name})...")
    job_state, message = "", ""
    try:
        progress = canvas.bulk_update_grades(
            plan.course_id, a["id"], {it.user_id: it.fields for it in to_send})
        progress = canvas.wait_for_progress(progress)
        job_state = progress.get("workflow_state") or ""
        message = progress.get("message") or ""
    except requests.HTTPError as exc:
        job_state, message = "request failed", str(exc)

    if job_state == "completed":
        print("  Canvas job completed.")
    else:
        print(f"  ! Canvas job {job_state or 'did not finish'}"
              + (f": {message}" if message else "")
              + ". Checking what was saved anyway.")

    after = {s.get("user_id"): s
             for s in canvas.submissions_with_comments(plan.course_id, a["id"])}
    rows = []
    bad = 0
    for it in plan.items:
        sub = after.get(it.user_id)
        problems = verify_posted(it, sub, a.get("grading_type") or "points") \
            if it.fields else []
        if problems:
            bad += 1
            print(f"  ! {it.student} ({it.user_id}): " + "; ".join(problems))
        rows.append({
            "file": plan.source.path.name,
            "course_id": plan.course_id,
            "assignment_id": a["id"],
            "assignment": a.get("name", ""),
            "section": (plan.section or {}).get("name", ""),
            "user_id": it.user_id,
            "student": it.student,
            "grade_before": it.grade_before,
            "grade_sent": "EXCUSED" if "excuse" in it.fields
                          else it.fields.get("posted_grade", ""),
            "comment_sent": it.fields.get("text_comment", ""),
            "comment_skipped_duplicate": "yes" if it.comment_skipped else "",
            "job_state": job_state,
            "canvas_grade_after": _grade_before(sub),
            "canvas_score_after": (sub or {}).get("score", ""),
            "problems": "; ".join(problems),
        })
    if not bad:
        print(f"  Verified: all {len(to_send)} update(s) are on Canvas.")
    return rows


def post_grades(canvas: Canvas, args, run_started: datetime) -> int:
    """--post-grades: parse and check every file, show the plan, then post."""
    plans: list[GradePlan] = []
    errors: list[str] = []
    rosters: dict[int, Roster] = {}

    for name in args.post_grades:
        path = Path(name)
        try:
            gf = parse_grade_file(path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        except GradeFileError as exc:
            errors.append(str(exc))
            continue
        plan, errs = plan_grade_file(canvas, gf, args.course, rosters,
                                     args.allow_duplicate_comments)
        errors += errs
        if plan:
            plans.append(plan)

    for plan in plans:
        print_grade_plan(plan)

    if errors:
        print("\nErrors (nothing was posted):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    total = sum(len(p.to_send) for p in plans)
    if not total:
        print("\nNothing to post.")
        return 0
    if args.dry_run:
        print(f"\nDry run: {total} update(s) checked, nothing posted.")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("\nNot posting without confirmation; rerun with --yes.",
                  file=sys.stderr)
            return 1
        answer = input(f"\nPost {total} grade/comment update(s) to Canvas? [y/N] ")
        if answer.strip().casefold() not in ("y", "yes"):
            print("Cancelled; nothing posted.")
            return 0

    rows: list[dict] = []
    for plan in plans:
        if plan.to_send:
            rows += post_grade_plan(canvas, plan)

    log_dir = Path(args.log_dir) if args.log_dir else Path(args.post_grades[0]).parent
    log_path = log_dir / run_started.strftime("grade_post_log_%Y%m%d_%H%M%S.csv")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nLog: {log_path}")
    except OSError as exc:
        print(f"\nCould not write log {log_path}: {exc}", file=sys.stderr)

    failed = sum(1 for r in rows if r["problems"])
    if failed:
        print(f"{failed} update(s) could not be verified; see the log.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bulk-download Canvas submissions, or bulk-post grades and comments.")
    p.add_argument("--base-url", required=True,
                   help="e.g. https://yourschool.instructure.com")
    p.add_argument("--course", type=int,
                   help="Course ID (optional with --post-grades: taken from the section)")
    p.add_argument("--assignment", type=int, action="append",
                   help="Assignment ID (repeatable). Default: all assignments.")
    p.add_argument("--out", default="./submissions", help="Output directory")
    p.add_argument("--student", action="append", metavar="SPEC",
                   help="Canvas ID, SIS ID, login, or name fragment (repeatable). "
                        "Default: all students.")
    p.add_argument("--section", action="append", metavar="SPEC",
                   help="Section ID, SIS section ID, or name fragment (repeatable). "
                        "Combined with --student as a union.")
    p.add_argument("--by-section", action="store_true",
                   help="Nest output folders under section name")
    p.add_argument("--flat", action="store_true",
                   help="Don't create a folder per student; save files directly "
                        "in the assignment folder (or the section folder with "
                        "--by-section), prefixed with the student's name and ID")
    p.add_argument("--list-assignments", action="store_true",
                   help="Print assignment IDs and exit")
    p.add_argument("--list-students", action="store_true",
                   help="Print the course roster and exit. Honours --section, "
                        "--student and --assignment.")
    p.add_argument("--list-sections", action="store_true",
                   help="Print the course sections and exit")
    p.add_argument("--tz", metavar="ZONE",
                   help="IANA zone for displaying times, e.g. America/New_York. "
                        "Canvas returns UTC; without this, UTC is written.")
    p.add_argument("--no-xlsx", action="store_true",
                   help="Skip the Excel run log")
    p.add_argument("--log-dir", metavar="DIR",
                   help="Where to write the Excel log (default: --out)")
    p.add_argument("--no-extract", action="store_true",
                   help="Download archives but leave them zipped")
    p.add_argument("--history", action="store_true",
                   help="Also fetch superseded resubmissions")
    g = p.add_argument_group("posting grades and comments")
    g.add_argument("--post-grades", action="append", metavar="FILE",
                   help="Grade file to post via the bulk update_grades endpoint "
                        "(repeatable). See the module docstring for the format.")
    g.add_argument("--dry-run", action="store_true",
                   help="With --post-grades: check files against Canvas and show "
                        "the plan, but post nothing")
    g.add_argument("--yes", action="store_true",
                   help="With --post-grades: skip the confirmation prompt")
    g.add_argument("--allow-duplicate-comments", action="store_true",
                   help="Post a comment even if the same text is already on the "
                        "submission")
    args = p.parse_args()
    if args.course is None and not args.post_grades:
        p.error("--course is required (it is optional only with --post-grades)")
    run_started = datetime.now()   # names the log file; local clock, not UTC

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"Set the {TOKEN_ENV} environment variable first.", file=sys.stderr)
        return 1

    canvas = Canvas(args.base_url, token)

    if args.post_grades:
        return post_grades(canvas, args, run_started)

    tz = None
    if args.tz:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(args.tz)
        except Exception as exc:
            raise SystemExit(f"Unknown timezone {args.tz!r}: {exc}")

    # The roster is needed for any filtering, for --by-section, and for the
    # section column in the manifest. Built once, two API calls.
    need_roster = bool(args.student or args.section or args.by_section
                       or args.list_students or args.list_sections)
    roster = None
    if need_roster:
        roster = Roster(canvas.sections(args.course),
                        canvas.student_enrollments(args.course))

    if args.list_sections:
        for s in sorted(roster.sections, key=lambda x: x.get("name") or ""):
            sis = s.get("sis_section_id") or "-"
            count = len(roster.users_of_section.get(s["id"], set()))
            print(f"{s['id']:>10}  {sis:<16}  {count:>4} students  {s.get('name', '')}")
        return 0

    if args.list_students:
        # Same selection rules as a download run: (--section OR --student),
        # then narrowed to students who have --assignment, if given.
        student_ids, _ = select_students(roster, args)
        users = [u for u in roster.users.values()
                 if student_ids is None or u["id"] in student_ids]
        if args.assignment:
            assigned = assigned_students(canvas, args.course, args.assignment)
            users = [u for u in users if u["id"] in assigned]
        for u in sorted(users, key=lambda x: x.get("sortable_name") or ""):
            sis = u.get("sis_user_id") or u.get("login_id") or "-"
            secs = "; ".join(roster.section_names(u["id"])) or "-"
            print(f"{u['id']:>10}  {sis:<16}  {u.get('sortable_name', ''):<32}  {secs}")
        filtered = student_ids is not None or bool(args.assignment)
        print(f"{len(users)} student(s)"
              + (f" of {len(roster.users)} in the course" if filtered else ""),
              file=sys.stderr)
        return 0

    assignments = canvas.assignments(args.course)

    if args.list_assignments:
        for a in assignments:
            print(f"{a['id']:>10}  {a['name']}")
        return 0

    # None means "no filter" -- the all-students pass stays the default.
    student_ids, section_ids = (select_students(roster, args) if roster
                                else (None, set()))
    if student_ids is not None:
        print(f"Filtering to {len(student_ids)} student(s).")

    if args.assignment:
        wanted = set(args.assignment)
        assignments = [a for a in assignments if a["id"] in wanted]

    out_root = Path(args.out)
    rows = []

    for idx, assign in enumerate(assignments, start=1):
        adir = out_root / f"{idx:02d}_{slug(assign['name'])}"
        due = DueDates(assign)
        base_str = fmt_ts(due.base, tz) or "no due date"
        print(f"\n[{assign['id']}] {assign['name']}  (due {base_str})")

        for sub in canvas.submissions(args.course, assign["id"], args.history):
            if student_ids is not None and sub.get("user_id") not in student_ids:
                continue
            if sub.get("workflow_state") == "unsubmitted":
                continue
            attachments = collect_attachments(sub, args.history)
            if not attachments:
                continue

            section = (roster.primary_section(sub["user_id"], section_ids)
                       if roster else None)
            section_label = (section or {}).get("name", "")

            user_sections = (roster.sections_of_user.get(sub["user_id"], [])
                             if roster else [])
            due_at, due_source = due.effective(sub["user_id"], user_sections)
            lateness = fmt_lateness(sub.get("seconds_late"))
            status = sub.get("late_policy_status") or ""

            sdir = adir
            if args.by_section:
                sdir = sdir / slug(section_label or "no-section", 40)
            if not args.flat:
                sdir = sdir / student_dir_name(sub)
            flag = f"  [LATE +{lateness}]" if lateness else ""
            if status == "excused":
                flag = "  [EXCUSED]"
            where = (sdir.relative_to(adir) / student_dir_name(sub)
                     if args.flat else sdir.relative_to(adir))
            print(f"  {where}"
                  f"  submitted {fmt_ts(sub.get('submitted_at'), tz) or '-'}{flag}")

            for att in attachments:
                fname = safe_filename(att.get("display_name") or att.get("filename", ""))
                if args.flat:
                    fname = flat_filename(sub, fname)
                target = sdir / fname
                try:
                    fresh = download(att["url"], target, att.get("size"))
                except Exception as exc:
                    print(f"    ! failed {fname}: {exc}")
                    continue
                print(f"    {'downloaded' if fresh else 'cached'} {fname}")

                extracted_to = ""
                if not args.no_extract and target.suffix.lower() in ARCHIVE_SUFFIXES:
                    unpack_dir = sdir / target.stem
                    if extract(target, unpack_dir):
                        extracted_to = str(unpack_dir)
                        print(f"      extracted -> {unpack_dir.name}/")

                rows.append({
                    "assignment": assign["name"],
                    "assignment_id": assign["id"],
                    "student": (sub.get("user") or {}).get("sortable_name", ""),
                    "user_id": sub.get("user_id"),
                    "section": section_label,
                    "all_sections": "; ".join(roster.section_names(sub["user_id"]))
                                    if roster else "",
                    "due_at": fmt_ts(due_at, tz),
                    "due_source": due_source,
                    "submitted_at": fmt_ts(sub.get("submitted_at"), tz),
                    "attempt": sub.get("attempt") or "",
                    "late": sub.get("late", False),
                    "late_by": lateness,
                    "late_policy_status": status,
                    "missing": sub.get("missing", False),
                    "graded_at": fmt_ts(sub.get("graded_at"), tz),
                    "score": sub.get("score") if sub.get("score") is not None else "",
                    "workflow_state": sub.get("workflow_state", ""),
                    "filename": fname,
                    "path": str(target),
                    "extracted_to": extracted_to,
                })

    if rows:
        out_root.mkdir(parents=True, exist_ok=True)
        manifest = out_root / "manifest.csv"
        with open(manifest, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n{len(rows)} file(s). Manifest: {manifest}")
    else:
        print("\nNo submission files found.")

    # The Excel log is written even on an empty run, so there is a record
    # that the run happened and matched nothing.
    if not args.no_xlsx:
        log_dir = Path(args.log_dir) if args.log_dir else out_root
        log_path = log_dir / log_filename(run_started)
        try:
            write_run_log(rows, log_path, run_started, args)
            print(f"Excel log: {log_path}")
        except ImportError:
            print("Excel log skipped: openpyxl is not installed "
                  "(pip install openpyxl, or pass --no-xlsx).", file=sys.stderr)
        except Exception as exc:
            print(f"Excel log failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())