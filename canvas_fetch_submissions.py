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

  # whole sections, by ID / SIS ID / name fragment
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --section "Lab 002" --section 45678 --by-section

  # union: everyone in one section, plus one extra student elsewhere
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --section "Lab 002" --student 884321

  # see the sections
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-sections

Each run also writes an Excel log named for the run's start time, e.g.
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

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        """Single request with backoff for throttling and transient 5xx."""
        last = None
        for attempt in range(5):
            resp = self.session.request(method, url, timeout=60, **kw)
            last = resp
            throttled = resp.status_code == 403 and "rate limit" in resp.text.lower()
            if throttled or resp.status_code in (500, 502, 503, 504):
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


def student_dir_name(sub: dict) -> str:
    user = sub.get("user") or {}
    name = user.get("sortable_name") or user.get("name") or "Anonymous"
    return f"{slug(name, 45)}_{sub.get('user_id', 'unknown')}"


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


def main() -> int:
    p = argparse.ArgumentParser(description="Bulk-download Canvas submissions.")
    p.add_argument("--base-url", required=True,
                   help="e.g. https://yourschool.instructure.com")
    p.add_argument("--course", type=int, required=True, help="Course ID")
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
    p.add_argument("--list-assignments", action="store_true",
                   help="Print assignment IDs and exit")
    p.add_argument("--list-students", action="store_true",
                   help="Print the course roster and exit")
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
    args = p.parse_args()
    run_started = datetime.now()   # names the log file; local clock, not UTC

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"Set the {TOKEN_ENV} environment variable first.", file=sys.stderr)
        return 1

    canvas = Canvas(args.base_url, token)

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
        for u in sorted(roster.users.values(),
                        key=lambda x: x.get("sortable_name") or ""):
            sis = u.get("sis_user_id") or u.get("login_id") or "-"
            secs = "; ".join(roster.section_names(u["id"])) or "-"
            print(f"{u['id']:>10}  {sis:<16}  {u.get('sortable_name', ''):<32}  {secs}")
        return 0

    assignments = canvas.assignments(args.course)

    if args.list_assignments:
        for a in assignments:
            print(f"{a['id']:>10}  {a['name']}")
        return 0

    # None means "no filter" -- the all-students pass stays the default.
    student_ids = None
    section_ids: set[int] = set()
    if args.student or args.section:
        student_ids = set()
        if args.section:
            section_ids = resolve_sections(roster, args.section)
            for sid in section_ids:
                student_ids |= roster.users_of_section.get(sid, set())
            names = ", ".join(roster.section_by_id[s].get("name", str(s))
                              for s in sorted(section_ids))
            print(f"Sections: {names}")
        if args.student:
            student_ids |= resolve_students(roster, args.student)
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
            sdir = sdir / student_dir_name(sub)
            flag = f"  [LATE +{lateness}]" if lateness else ""
            if status == "excused":
                flag = "  [EXCUSED]"
            print(f"  {sdir.relative_to(adir)}"
                  f"  submitted {fmt_ts(sub.get('submitted_at'), tz) or '-'}{flag}")

            for att in attachments:
                fname = safe_filename(att.get("display_name") or att.get("filename", ""))
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