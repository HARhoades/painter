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

Creating grade files
--------------------
  # one file per section, students pre-filled from the Canvas roster
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --make-grade-files --assignment 280869 \
      --section 27425 --section 27440 --grade-file-dir ./grading

  Writes <Section><Number>-<ASSIGNMENT>_Grading-AY<YY>-<SEMESTER>.txt, e.g.
  A1-DATE_Grading-27-1.txt for section "A1-8". The assignment part of the name
  is the first word of the Canvas assignment name (override with
  --assignment-label); the AY and semester are read from the course's term
  name (override with --ay 27 --term 1).

  --section is repeatable and accepts a section ID, SIS ID or name fragment;
  with none given, every section in the course gets a file. title= and
  instructor= come from Canvas for each section, and each [STUDENT] block is
  filled in with the student's name and Canvas user ID, leaving grade= and
  comments= for you. --assignment is optional: without it the [ASSIGNMENT]
  title and id are left blank to fill in before posting. Existing files are
  never overwritten unless you pass --force.

Exporting the roster
--------------------
  # one CSV line per student, sorted by last name
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --roster-csv roster.csv

  # just some sections (and/or students), same filters as a download run
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --roster-csv roster.csv --section A2-8 --section 27440

  Columns: Student Full Name (First Last), Student Canvas ID, Student First
  Name, Student Last Name, Instructor Last Name, Section Name, Section Canvas
  ID. A student enrolled in several sections gets one line per section (with
  --section, only the selected ones). A section with several teachers lists
  their surnames separated by "; "; TAs are used only when a section has no
  teacher. The file is UTF-8 with a BOM so Excel shows accented names correctly.

Sorting submissions into section folders
----------------------------------------
  # move each student folder into a folder for their section (no Canvas
  # access needed -- everything comes from the roster CSV above)
  python canvas_fetch_submissions.py --organize ./submissions/03_DATE-Scenario \
      --roster roster.csv

  # preview first; or copy into a new tree and leave the original untouched
  python canvas_fetch_submissions.py --organize ./submissions/03_DATE-Scenario \
      --roster roster.csv --dry-run
  python canvas_fetch_submissions.py --organize ./submissions/03_DATE-Scenario \
      --roster roster.csv --organize-to ./by_section

  Every section in the roster gets a folder named for it (e.g. A2-8), even if
  nobody in it submitted -- except a section that holds the whole roster
  (a course-wide default section), which would always be empty. Each student sub-folder (or --flat file) is matched
  to a roster line by the Canvas ID in its name -- Last-First_884321 as this
  script writes it, or the lastfirst_884321_... names in Canvas's own bulk
  download -- and, failing that, by the student's name. Pointing --organize at
  the --out folder of a whole run sorts every assignment folder inside it.
  --section limits the run to those sections (by name or ID). Anything that
  can't be matched, or matches more than one student, is left where it is and
  reported. A student listed in two sections goes to the one that isn't shared
  by the whole roster; if that doesn't settle it, the first is used with a
  warning (pass --section to choose). Each run writes organize_log_*.csv.

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

Exporting quiz answers and content
----------------------------------
  # every student's answers to one New Quiz, plus the quiz itself, in the
  # quiz's folder under --out (the folder a download run with this
  # --assignment uses)
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --assignment 280869 --export-quiz

  # just two sections' answers, one folder per section; each folder also
  # gets its own copy of the quiz content
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --assignment 280869 --export-quiz \
      --section "Lab 001" --section "Lab 002" --by-section

  # preview: shows how each question converts and where files would go;
  # writes nothing and starts no report or export job
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --assignment 280869 --export-quiz --dry-run

  Every output folder gets:

    <Quiz>_student-answers.csv   Canvas's New Quizzes "student analysis"
                                 report: what each student answered. Without
                                 filters it is kept exactly as Canvas made it;
                                 with --section/--student/--by-section only the
                                 selected students' rows are kept, under the
                                 report's own header (skip it: --no-answers)
    <Quiz>_new-quiz.json         the quiz content: every question, answer
                                 choice, correct answer and feedback exactly
                                 as the New Quizzes API returns them, plus the
                                 quiz settings
    <Quiz>_qti.zip               QTI 1.2 package built from that JSON, in the
                                 Classic Quizzes layout Canvas imports
    <Quiz>_qti-report.csv        one line per question: converted or not, why
    <Quiz>_course-export.imscc   a Common Cartridge course export of the quiz's
                                 assignment -- kept only if it really contains
                                 the quiz (skip it: --no-course-export)

  Instructure does not document the answers report's columns, so rows are
  matched to students by value, not header name: whichever column best
  matches the course roster's Canvas user IDs (then SIS IDs, logins, names).
  If none does, filtered answers are not written and the run says why. The
  unfiltered report is deleted once it has been split.

  Canvas's API has no QTI export for New Quizzes (only the quiz's Build >
  Exports tab in the browser), which is why the QTI zip is built here.
  Converted to QTI: multiple choice, true/false, multiple answer, essay, file
  upload, numeric, matching, fill in the blank (typed and drop-down), and
  stimuli (as text-only questions). Ordering, categorization, hot spot and
  formula questions have no Classic equivalent and stay in the JSON only.
  Questions drawn at random from an item bank cannot be exported: the API
  returns only the bank's name. Each limit is listed in the report CSV.

  New Quiz File Upload answers: a New Quiz submission is an LTI launch with
  no attachments, so a normal download run finds no files for it (it says
  so). Add --quiz-uploads to --export-quiz to download any file links the
  student analysis report contains into <Quiz>_uploads/<Student>_<id>/, with
  an uploads_log.csv. New Quizzes has no API for these files, so this is
  best effort; if the report has no links the run says so and lists the
  report's columns.

  The reliable route is --browser-uploads, which uses a real browser
  (pip install playwright) because the New Quizzes API only accepts the
  token the quiz tool gets inside the browser:

    python canvas_fetch_submissions.py --base-url https://school.instructure.com \
        --course 12345 --assignment 290440 --browser-uploads --limit 3

  The first run opens Chrome; sign in to Canvas there (SSO/CAC as usual)
  and the run carries on by itself once Canvas loads. The session is kept in
  ./canvas-browser-profile (keep that folder private), so later runs start
  signed in.

  If sign-in hangs (CAC certificate prompts often never appear in a browser
  that Playwright starts), start the browser yourself and let the script
  attach to it:

    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
        --remote-debugging-port=9222 --user-data-dir=C:\\canvas-browser-profile
    (Edge: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe")

  Sign in to Canvas in that window, then run with
  --browser-uploads --connect-browser http://localhost:9222

  Each submitted student is opened in SpeedGrader, their File Upload files
  are read from the quiz's own results and saved as <Quiz>_uploads/<Last-First>_<id>/Q<n>__<file>,
  with uploads_log.csv. Files are matched to students by quiz session ID,
  not by name. Reruns skip files already saved. --dry-run lists who would
  be visited without opening a browser.

  A Classic Quiz's content is exported with Canvas's own QTI content export;
  student answers are only implemented for New Quizzes.

  Jobs are never started twice: the report and export job IDs are saved in
  the quiz folder (.quiz_export_state.json) as soon as Canvas returns them,
  and a rerun after a timeout or interruption resumes them. If a report is
  already being generated (Canvas answers 409), the tool waits for it. Files
  are downloaded as soon as each job finishes.

  Exit status: 0 = everything delivered; 1 = nothing exported (no selected
  student has the quiz); 2 = answers and content delivered but the course
  export did not finish (rerun to resume); 3 = the student answers were not
  delivered (the reason is printed; the quiz content still was).

Rate limits
-----------
  Canvas throttles each API token with a leaky bucket. Every request here is
  sequential; throttled responses (429, or 403 "Rate Limit Exceeded") are
  retried with exponential backoff capped at 60 s, honouring Retry-After;
  requests slow down before the bucket runs dry, based on the
  X-Rate-Limit-Remaining header; and background jobs are polled at a growing
  interval capped at 30 s. Retries for a write (posting grades, starting an
  export) happen only for throttling, never after a server error.

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
import json
import os
import random
import re
import shutil
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
# Throttling, retry and polling limits
# --------------------------------------------------------------------------
# Canvas throttles per API token with a leaky bucket. Every response carries
# X-Request-Cost and, when throttling applies, X-Rate-Limit-Remaining. A
# throttled request is answered 429 (current docs) or 403 "Rate Limit
# Exceeded" (older instances); both are retried here.
MAX_ATTEMPTS = 6            # first try + 5 retries
BACKOFF_BASE = 2.0          # seconds; doubles per retry ...
BACKOFF_CAP = 60.0          # ... but never waits longer than this
RATE_LOW_WATER = 150.0      # pace requests once the bucket drops below this
RATE_REFILL_PER_SEC = 10.0  # approximate refill rate; Canvas does not publish it
PACE_CAP = 20.0             # longest single pacing pause, seconds
POLL_START = 2.0            # first wait when polling a background job
POLL_FACTOR = 1.5           # each later wait is this much longer ...
POLL_CAP = 30.0             # ... up to this upper bound between polls
DOWNLOAD_ATTEMPTS = 4       # whole-file retries when a transfer is cut off


def is_throttled(resp: requests.Response) -> bool:
    """429, or the older 403 whose body says the rate limit was exceeded."""
    if resp.status_code == 429:
        return True
    return resp.status_code == 403 and "rate limit" in (resp.text or "").lower()


def retry_after_seconds(resp: requests.Response) -> float | None:
    """Retry-After in seconds, if the server sent a numeric one."""
    try:
        value = float(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Wait before retry number `attempt` (0-based).

    Exponential with jitter, capped at BACKOFF_CAP, so repeated throttling
    never turns into a tight loop that drains the bucket again the moment it
    refills. A server-supplied Retry-After wins, within the same cap.
    """
    if retry_after is not None:
        return min(retry_after, BACKOFF_CAP)
    ceiling = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** attempt))
    return ceiling / 2 + random.uniform(0, ceiling / 2)


def poll_until(fetch, is_done, timeout: float, sleep=time.sleep,
               start: float = POLL_START, factor: float = POLL_FACTOR,
               cap: float = POLL_CAP, on_poll=None):
    """Call fetch() until is_done(result) or timeout; returns (result, done).

    The wait between polls starts at `start` seconds and grows by `factor`
    each time, never exceeding `cap` and never sleeping past the deadline.
    """
    deadline = time.monotonic() + timeout
    interval = start
    result = fetch()
    while not is_done(result):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result, False
        sleep(min(interval, remaining))
        interval = min(cap, interval * factor)
        result = fetch()
        if on_poll:
            on_poll(result)
    return result, True


# --------------------------------------------------------------------------
# Canvas API client
# --------------------------------------------------------------------------
class Canvas:
    def __init__(self, base_url: str, token: str, per_page: int = 100):
        self.base = base_url.rstrip("/")
        self.per_page = per_page
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.sleep = time.sleep          # swapped out in tests
        self.stats = {"requests": 0, "throttled": 0, "retries": 0,
                      "paced_seconds": 0.0, "min_remaining": None}

    def _note_rate(self, resp: requests.Response) -> float | None:
        try:
            remaining = float(resp.headers["X-Rate-Limit-Remaining"])
        except (KeyError, ValueError):
            return None
        low = self.stats["min_remaining"]
        self.stats["min_remaining"] = remaining if low is None else min(low, remaining)
        return remaining

    def _pace(self, remaining: float | None) -> None:
        """Slow down before the bucket runs dry, instead of after a 429."""
        if remaining is None or remaining >= RATE_LOW_WATER:
            return
        wait = min(PACE_CAP, (RATE_LOW_WATER - remaining) / RATE_REFILL_PER_SEC)
        if wait > 0:
            self.stats["paced_seconds"] += wait
            self.sleep(wait)

    def _request(self, method: str, url: str, retry_server_errors: bool = True,
                 auth: bool = True, timeout: float = 60, **kw) -> requests.Response:
        """One request, with backoff for throttling and transient failures.

        Throttled responses (429, or 403 "rate limit") are always retried:
        Canvas rejects those without processing them. Pass
        retry_server_errors=False for writes that are not safe to repeat --
        a 5xx does not prove Canvas ignored the request, and resending a bulk
        grade update or a content export would do the work twice. Connection
        errors are retried for GETs only, for the same reason.

        auth=False drops the Bearer header (pre-signed file URLs; some
        storage backends reject it).
        """
        headers = dict(kw.pop("headers", None) or {})
        if not auth:
            headers["Authorization"] = None   # requests drops None headers
        idempotent = method.upper() == "GET"
        last = None
        for attempt in range(MAX_ATTEMPTS):
            final = attempt == MAX_ATTEMPTS - 1
            try:
                self.stats["requests"] += 1
                resp = self.session.request(method, url, timeout=timeout,
                                            headers=headers or None, **kw)
            except (requests.ConnectionError, requests.Timeout):
                if not idempotent or final:
                    raise
                self.stats["retries"] += 1
                self.sleep(backoff_delay(attempt))
                continue
            last = resp
            remaining = self._note_rate(resp)
            if is_throttled(resp):
                self.stats["throttled"] += 1
                if final:
                    break
                self.stats["retries"] += 1
                resp.close()
                self.sleep(backoff_delay(attempt, retry_after_seconds(resp)))
                continue
            if retry_server_errors and resp.status_code in (500, 502, 503, 504):
                if final:
                    break
                self.stats["retries"] += 1
                resp.close()
                self.sleep(backoff_delay(attempt))
                continue
            resp.raise_for_status()
            self._pace(remaining)
            return resp
        last.raise_for_status()
        return last

    def get_json(self, url: str, params: dict | None = None):
        return self._request("GET", url, params=params).json()

    def paginate_url(self, url: str, params: dict | None = None):
        """Yield items across all pages of a full URL, following Link headers."""
        while url:
            resp = self._request("GET", url, params=params)
            params = None  # the "next" URL already carries the query string
            payload = resp.json()
            if isinstance(payload, list):
                yield from payload
            else:
                yield payload
            url = resp.links.get("next", {}).get("url")

    def paginate(self, path: str, params: dict | None = None):
        """Yield items across all pages of an /api/v1 path."""
        params = dict(params or {})
        params.setdefault("per_page", self.per_page)
        yield from self.paginate_url(f"{self.base}/api/v1{path}", params)

    def fetch_file(self, url: str, dest: Path, expected_size: int | None = None,
                   auth: bool = False) -> bool:
        """Stream a file to disk. Returns True if it was newly downloaded.

        Goes through _request, so throttling and 5xx are retried with
        backoff; a transfer cut off part-way is restarted from scratch up to
        DOWNLOAD_ATTEMPTS times. Written to <dest>.part and renamed only when
        complete, so a failed run never leaves a truncated file in place.
        """
        if dest.exists() and (expected_size is None or dest.stat().st_size == expected_size):
            return False  # already have it -- makes reruns cheap
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        for attempt in range(DOWNLOAD_ATTEMPTS):
            try:
                with self._request("GET", url, auth=auth, stream=True,
                                   timeout=120) as r:
                    with open(tmp, "wb") as fh:
                        for chunk in r.iter_content(chunk_size=1 << 16):
                            fh.write(chunk)
                break
            except (requests.ConnectionError, requests.Timeout,
                    requests.exceptions.ChunkedEncodingError):
                if attempt == DOWNLOAD_ATTEMPTS - 1:
                    tmp.unlink(missing_ok=True)
                    raise
                self.stats["retries"] += 1
                self.sleep(backoff_delay(attempt))
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
        if expected_size is not None and tmp.stat().st_size != expected_size:
            print(f"      ! {dest.name}: {tmp.stat().st_size} bytes, Canvas listed "
                  f"{expected_size}", file=sys.stderr)
        tmp.replace(dest)
        return True

    def rate_summary(self) -> str:
        s = self.stats
        parts = [f"{s['requests']} request(s)"]
        if s["throttled"]:
            parts.append(f"{s['throttled']} throttled")
        if s["retries"]:
            parts.append(f"{s['retries']} retried")
        if s["paced_seconds"]:
            parts.append(f"paused {s['paced_seconds']:.0f}s to stay under the rate limit")
        if s["min_remaining"] is not None:
            parts.append(f"lowest X-Rate-Limit-Remaining {s['min_remaining']:.0f}")
        return ", ".join(parts)

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

    def teacher_enrollments(self, course_id: int):
        """Instructors per section; used to fill instructor= in a grade file."""
        return list(self.paginate(
            f"/courses/{course_id}/enrollments",
            {"type[]": ["TeacherEnrollment", "TaEnrollment"],
             "state[]": ["active", "invited"]},
        ))

    def course(self, course_id: int) -> dict:
        """The course, with its enrollment term (term name carries AY/semester)."""
        return self._request(
            "GET", f"{self.base}/api/v1/courses/{course_id}",
            params={"include[]": ["term"]},
        ).json()

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

    def wait_for_progress(self, progress: dict, timeout: float = 300.0) -> dict:
        """Poll a Progress object until it completes, fails, or times out.

        The polling interval grows from POLL_START to at most POLL_CAP, so a
        slow job costs a handful of requests rather than one every 2 seconds.
        """
        url = progress.get("url") or f"{self.base}/api/v1/progress/{progress['id']}"
        first = [progress]

        def fetch():
            return first.pop() if first else self.get_json(url)

        progress, _ = poll_until(
            fetch, lambda p: p.get("workflow_state") in ("completed", "failed"),
            timeout, sleep=self.sleep)
        return progress

    # ---- quiz content export -------------------------------------------------
    def new_quiz(self, course_id: int, assignment_id: int) -> dict:
        return self.get_json(
            f"{self.base}/api/quiz/v1/courses/{course_id}/quizzes/{assignment_id}")

    def new_quiz_items(self, course_id: int, assignment_id: int) -> list[dict]:
        """Every item in a New Quiz (questions, stimuli, bank entries, banks).

        No per_page is sent: the quiz API documents no paging parameters.
        Link headers are still followed in case a long quiz is paged.
        """
        return list(self.paginate_url(
            f"{self.base}/api/quiz/v1/courses/{course_id}/quizzes/"
            f"{assignment_id}/items"))

    def create_content_export(self, course_id: int, export_type: str,
                              select: dict[str, list]) -> dict:
        """POST a content export job. Never retried on a 5xx: each POST
        starts a new job, and a 5xx does not prove Canvas didn't start one."""
        form: list[tuple[str, str]] = [("export_type", export_type),
                                       ("skip_notifications", "true")]
        for kind, ids in select.items():
            form += [(f"select[{kind}][]", str(i)) for i in ids]
        return self._request(
            "POST", f"{self.base}/api/v1/courses/{course_id}/content_exports",
            data=form, retry_server_errors=False).json()

    def content_export(self, course_id: int, export_id: int) -> dict:
        return self.get_json(
            f"{self.base}/api/v1/courses/{course_id}/content_exports/{export_id}")

    def content_exports(self, course_id: int, limit: int = 20) -> list[dict]:
        """Most recent exports first; only the first page is needed."""
        return self.get_json(
            f"{self.base}/api/v1/courses/{course_id}/content_exports",
            {"per_page": limit})

    def create_quiz_report(self, course_id: int, assignment_id: int,
                           report_type: str = "student_analysis",
                           fmt: str = "csv") -> dict:
        """Start a New Quizzes report; returns its Progress object.

        Not retried on a 5xx (it starts a job). Canvas answers 409 while a
        report of the same type is already being generated.
        """
        return self._request(
            "POST", f"{self.base}/api/quiz/v1/courses/{course_id}/quizzes/"
                    f"{assignment_id}/reports",
            data={"quiz_report[report_type]": report_type,
                  "quiz_report[format]": fmt},
            retry_server_errors=False).json()

    def progress(self, progress_id) -> dict:
        return self.get_json(f"{self.base}/api/v1/progress/{progress_id}")

    def self_user(self) -> dict:
        return self.get_json(f"{self.base}/api/v1/users/self")

    def file(self, file_id) -> dict:
        """File metadata, including a pre-signed download url."""
        return self.get_json(f"{self.base}/api/v1/files/{file_id}")


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


def download(canvas: Canvas, url: str, dest: Path,
             expected_size: int | None = None) -> bool:
    """Download a submission attachment. Returns True if newly downloaded.

    Canvas attachment URLs are pre-signed and redirect to blob storage, so
    the Bearer header is NOT sent (some backends reject it). Retries,
    throttling backoff and the .part-then-rename handling come from
    Canvas.fetch_file.
    """
    return canvas.fetch_file(url, dest, expected_size, auth=False)


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
# Generating grade files from the Canvas roster
# --------------------------------------------------------------------------
# AY27-1, AY 2027 Term 1, 2026-2027 Term 1 ... -> ("27", "1")
TERM_PATTERNS = [
    re.compile(r"\bAY\s*(?P<year>\d{2,4})\s*[-–/ ]\s*(?P<term>\d)\b", re.I),
    re.compile(r"\bAY\s*(?P<year>\d{2,4})\b.*?\b(?:term|semester|sem)\s*(?P<term>\d)\b", re.I),
    re.compile(r"\b\d{4}\s*[-–]\s*(?P<year>\d{4})\b.*?\b(?:term|semester|sem)\s*(?P<term>\d)\b", re.I),
]


def parse_term_name(name: str | None) -> tuple[str, str] | None:
    """Pull (AY, semester) out of a Canvas term name; None if it doesn't fit."""
    for pattern in TERM_PATTERNS:
        m = pattern.search(name or "")
        if m:
            return m.group("year")[-2:], m.group("term")
    return None


def section_prefix(section_name: str) -> str:
    """Filename prefix from a section name: 'A1-8' -> 'A1', 'A1' -> 'A1'."""
    head = re.split(r"[-–_\s]", (section_name or "").strip(), maxsplit=1)[0]
    return slug(head, 20)


def instructor_label(enrollment: dict) -> str:
    """Surname of an instructor, as the grade files use it ('Rhoades')."""
    user = enrollment.get("user") or {}
    sortable = user.get("sortable_name") or ""
    if "," in sortable:
        return sortable.split(",", 1)[0].strip()
    name = user.get("name") or sortable
    return name.split()[-1] if name.split() else ""


def grade_file_name(section_name: str, label: str, ay: str, term: str) -> str:
    """<Section><Number>-<ASSIGNMENT>_Grading-AY<YY>-<SEMESTER>, e.g.
    A1-DATE_Grading-27-1.txt (the AY is written as the two-digit year)."""
    return f"{section_prefix(section_name)}-{label}_Grading-{ay}-{term}.txt"


def render_grade_file(assignment: dict | None, label: str, section: dict,
                      instructor: str, students: list[dict]) -> str:
    """The grade file itself: an [ASSIGNMENT] and [SECTION] header, then one
    [STUDENT] block per student with name and Canvas id filled in."""
    title = (assignment or {}).get("name", "") if assignment else label
    out = ["[ASSIGNMENT]",
           f"title={title}",
           f"id={(assignment or {}).get('id', '')}",
           "",
           "[SECTION]",
           f"title={section.get('name', '')}",
           f"instructor={instructor}",
           f"id={section['id']}",
           ""]
    for user in students:
        out += ["[STUDENT]",
                f"name={user.get('sortable_name') or user.get('name') or ''}",
                f"id={user['id']}",          # Canvas user ID, not the SIS ID
                "grade=",
                "comments=",
                ""]
    return "\n".join(out).rstrip("\n") + "\n"


def make_grade_files(canvas: Canvas, args) -> int:
    """--make-grade-files: write one blank grade file per section."""
    roster = Roster(canvas.sections(args.course),
                    canvas.student_enrollments(args.course))

    if args.section:
        section_ids = resolve_sections(roster, args.section)
    else:
        section_ids = {s["id"] for s in roster.sections}
        print("No --section given: writing a file for every section in the course.")

    # Assignment is optional; without it the header is left blank to fill in.
    assignment = None
    label = args.assignment_label
    if args.assignment:
        if len(args.assignment) > 1:
            raise SystemExit("--make-grade-files takes at most one --assignment.")
        try:
            assignment = canvas.assignment(args.course, args.assignment[0])
        except requests.HTTPError as exc:
            raise SystemExit(f"Assignment {args.assignment[0]} not found in course "
                             f"{args.course} ({exc}).")
        label = label or (assignment.get("name") or "").split()[0]
    if not label:
        raise SystemExit("Without --assignment, pass --assignment-label NAME for "
                         "the filename, e.g. --assignment-label DATE.")
    label = slug(label, 30)

    # AY and semester: from --ay/--term, else from the course's term name.
    ay, term = args.ay, args.term
    if not (ay and term):
        term_name = ((canvas.course(args.course).get("term") or {}).get("name") or "")
        parsed = parse_term_name(term_name)
        if not parsed:
            raise SystemExit(
                f"Could not read an academic year and semester from the course "
                f"term name {term_name!r}. Pass --ay and --term, e.g. --ay 27 --term 1.")
        ay, term = ay or parsed[0], term or parsed[1]
        print(f"Term {term_name!r} -> AY{ay}, semester {term}")
    ay = ay[-2:]

    instructors: dict[int, list[str]] = {}
    for enr in canvas.teacher_enrollments(args.course):
        sid = enr.get("course_section_id")
        name = instructor_label(enr)
        if sid is None or not name:
            continue
        instructors.setdefault(sid, [])
        if name not in instructors[sid]:
            instructors[sid].append(name)

    out_dir = Path(args.grade_file_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    used: dict[str, str] = {}      # filename -> section name that claimed it
    for sid in sorted(section_ids,
                      key=lambda i: roster.section_by_id[i].get("name") or ""):
        section = roster.section_by_id[sid]
        students = sorted(
            (roster.users[u] for u in roster.users_of_section.get(sid, set())),
            key=lambda u: u.get("sortable_name") or u.get("name") or "")
        if not students:
            print(f"  {section.get('name')}: no students, skipped")
            continue
        teachers = instructors.get(sid, [])
        if len(teachers) > 1:
            print(f"  note: {section.get('name')} has several instructors "
                  f"({', '.join(teachers)}); using {teachers[0]}")

        # Two sections can share a prefix (A2-8 and A2-9 both reduce to "A2"),
        # so the second one keeps its full section name instead of clobbering
        # the first.
        section_name = section.get("name") or str(sid)
        name = grade_file_name(section_name, label, ay, term)
        if name in used:
            print(f"  note: {section_name} and {used[name]} share a prefix; "
                  f"using the full section name for {section_name}")
            name = (f"{slug(section_name, 20)}-{label}"
                    f"_Grading-{ay}-{term}.txt")
        used[name] = section_name
        path = out_dir / name
        if path.exists() and not args.force:
            print(f"  ! {path} exists; not overwritten (use --force)")
            continue
        path.write_text(
            render_grade_file(assignment, label, section,
                              teachers[0] if teachers else "", students),
            encoding="utf-8")
        print(f"  {path}  ({len(students)} students)")
        written += 1

    print(f"\n{written} file(s) written to {out_dir}")
    return 0


# --------------------------------------------------------------------------
# Exporting the roster to CSV
# --------------------------------------------------------------------------
ROSTER_CSV_COLUMNS = [
    "Student Full Name", "Student Canvas ID", "Student First Name",
    "Student Last Name", "Instructor Last Name", "Section Name",
    "Section Canvas ID",
]


def split_name(user: dict) -> tuple[str, str]:
    """(first, last) for a Canvas user.

    sortable_name ("Last, First") is the reliable split: it keeps multi-word
    surnames such as "De La Cruz, Ana" together. Without a comma, the last
    word of the display name is taken as the surname.
    """
    sortable = (user.get("sortable_name") or "").strip()
    if "," in sortable:
        last, first = (part.strip() for part in sortable.split(",", 1))
        return first, last
    words = (user.get("name") or sortable).split()
    if not words:
        return "", ""
    return " ".join(words[:-1]), words[-1]


def section_instructors(canvas: Canvas, course_id: int) -> dict[int, list[str]]:
    """Section ID -> instructor surnames. Teachers win; TAs only as a fallback."""
    teachers: dict[int, list[str]] = {}
    tas: dict[int, list[str]] = {}
    for enr in canvas.teacher_enrollments(course_id):
        sid = enr.get("course_section_id")
        name = instructor_label(enr)
        if sid is None or not name:
            continue
        bucket = teachers if enr.get("type") == "TeacherEnrollment" else tas
        names = bucket.setdefault(sid, [])
        if name not in names:
            names.append(name)
    return {sid: teachers.get(sid) or tas.get(sid) or []
            for sid in set(teachers) | set(tas)}


def export_roster_csv(canvas: Canvas, args) -> int:
    """--roster-csv: one line per student (per section), sorted by last name."""
    roster = Roster(canvas.sections(args.course),
                    canvas.student_enrollments(args.course))
    student_ids, section_ids = select_students(roster, args)
    if args.assignment:
        assigned = assigned_students(canvas, args.course, args.assignment)
        student_ids = assigned if student_ids is None else student_ids & assigned
    instructors = section_instructors(canvas, args.course)

    rows = []
    for uid, user in roster.users.items():
        if student_ids is not None and uid not in student_ids:
            continue
        first, last = split_name(user)
        full = " ".join(part for part in (first, last) if part)
        sids = roster.sections_of_user.get(uid, [])
        if section_ids:
            # A student added with --student may sit outside the selected
            # sections; keep their own sections rather than dropping them.
            sids = [s for s in sids if s in section_ids] or sids
        for sid in sids or [None]:
            section = roster.section_by_id.get(sid, {}) if sid is not None else {}
            rows.append({
                "Student Full Name": full,
                "Student Canvas ID": uid,
                "Student First Name": first,
                "Student Last Name": last,
                "Instructor Last Name": "; ".join(instructors.get(sid, [])),
                "Section Name": section.get("name", ""),
                "Section Canvas ID": sid if sid is not None else "",
            })

    rows.sort(key=lambda r: (r["Student Last Name"].casefold(),
                             r["Student First Name"].casefold(),
                             str(r["Student Canvas ID"]),
                             r["Section Name"].casefold()))

    path = Path(args.roster_csv)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=ROSTER_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    students = len({r["Student Canvas ID"] for r in rows})
    extra = len(rows) - students
    print(f"{students} student(s), {len(rows)} line(s) -> {path}")
    if extra:
        print(f"  note: {extra} extra line(s) for students in more than one "
              "section; filter with --section to keep one", file=sys.stderr)
    no_teacher = sorted({r["Section Name"] for r in rows
                         if not r["Instructor Last Name"]})
    if no_teacher:
        print("  note: no instructor enrolled in: " + ", ".join(
            n or "(no section)" for n in no_teacher), file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# Sorting downloaded submissions into section folders
# --------------------------------------------------------------------------
def _letters(text: str) -> str:
    """Lower-case letters only, for comparing names written different ways."""
    return "".join(ch for ch in (text or "").casefold() if ch.isalpha())


def read_roster_csv(path: Path) -> list[dict]:
    """Rows of a --roster-csv file (header names, not positions, are used)."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        raise SystemExit(f"Can't read roster {path}: {exc}")
    need = {"Student Canvas ID", "Section Name"}
    missing = need - set(rows[0].keys() if rows else need)
    if not rows or missing:
        raise SystemExit(f"{path} doesn't look like a --roster-csv file"
                         + (f" (missing {', '.join(sorted(missing))})" if missing else
                            " (no rows)"))
    return rows


class RosterIndex:
    """Lookups over a roster CSV for matching folder names to students."""

    def __init__(self, rows: list[dict], section_specs: list[str] | None):
        self.sections: dict[str, str] = {}          # section name -> section id
        by_student: dict[str, list[str]] = {}       # canvas id -> section names
        self.students: dict[str, dict] = {}
        for r in rows:
            uid = (r.get("Student Canvas ID") or "").strip()
            sec = (r.get("Section Name") or "").strip()
            if not uid:
                continue
            self.students.setdefault(uid, r)
            if sec:
                self.sections.setdefault(sec, (r.get("Section Canvas ID") or "").strip())
                if sec not in by_student.setdefault(uid, []):
                    by_student[uid].append(sec)

        self.filtered_out: set[str] = set()
        if section_specs:
            keep = set()
            for spec in section_specs:
                hits = {n for n, sid in self.sections.items()
                        if spec == sid or spec.casefold() in n.casefold()}
                if not hits:
                    raise SystemExit(f"--section {spec!r} matches no section in the roster")
                keep |= hits
            self.sections = {n: i for n, i in self.sections.items() if n in keep}
            by_student = {u: [s for s in secs if s in keep]
                          for u, secs in by_student.items()}
            by_student = {u: secs for u, secs in by_student.items() if secs}
            self.filtered_out = set(self.students) - set(by_student)
            self.students = {u: r for u, r in self.students.items() if u in by_student}

        # A section every student belongs to (a course-wide default section)
        # says nothing about where a student belongs, so it loses ties.
        # It is "course-wide" only if it holds every student and every
        # student also has a real section of their own.
        everyone = {sec for sec in self.sections
                    if by_student
                    and all(sec in secs and len(secs) > 1
                            for secs in by_student.values())}
        self.catch_all = everyone
        self.section_of: dict[str, str] = {}
        self.ambiguous_section: dict[str, list[str]] = {}
        for uid, secs in by_student.items():
            pick = [s for s in secs if s not in everyone] or secs
            self.section_of[uid] = pick[0]
            if len(pick) > 1:
                self.ambiguous_section[uid] = pick

        # Name keys: "lastfirst" (Canvas bulk-download style), "firstlast",
        # and the sortable form this script writes ("Last-First").
        self.by_name: dict[str, set[str]] = {}
        for uid, r in self.students.items():
            first = r.get("Student First Name", "")
            last = r.get("Student Last Name", "")
            full = r.get("Student Full Name", "")
            for key in {_letters(last + first), _letters(first + last), _letters(full)}:
                if key:
                    self.by_name.setdefault(key, set()).add(uid)

    def match(self, name: str) -> tuple[str | None, str]:
        """(canvas id, how) for a file or folder name, or (None, reason)."""
        # Folder "Doe-Jane_884321", --flat file "Doe-Jane_884321__essay.pdf".
        stem = name.split("__", 1)[0]
        # 1. This script's names end in _<id>.
        for cand in (stem, Path(stem).stem):
            m = re.search(r"_(\d+)$", cand)
            if m and m.group(1) in self.students:
                return m.group(1), "id"
        # 2. Any number in the name that is a roster ID (Canvas bulk
        #    downloads: "doejane_884321_5551234_essay.pdf"; "LATE_" prefixes).
        numbers = set(re.findall(r"\d+", name))
        if numbers & self.filtered_out and not numbers & set(self.students):
            return None, "student not in the selected --section"
        hits = {t for t in numbers if t in self.students}
        if len(hits) == 1:
            return hits.pop(), "id"
        if len(hits) > 1:
            return None, "several roster IDs in the name"
        # 3. The name alone, with the ID and any extras stripped.
        key = _letters(re.split(r"_\d", stem, maxsplit=1)[0])
        uids = self.by_name.get(key, set())
        if len(uids) == 1:
            return next(iter(uids)), "name"
        if len(uids) > 1:
            return None, "name matches several students"
        return None, "no roster match"


def organize_submissions(args) -> int:
    """--organize: move (or copy) student folders into one folder per section."""
    src_root = Path(args.organize)
    if not src_root.is_dir():
        raise SystemExit(f"--organize: {src_root} is not a folder")
    index = RosterIndex(read_roster_csv(Path(args.roster)), args.section)
    if not index.sections:
        raise SystemExit("The roster has no section names to organize by.")
    dest_root = Path(args.organize_to) if args.organize_to else src_root
    copying = dest_root.resolve() != src_root.resolve()
    if copying and dest_root.resolve().is_relative_to(src_root.resolve()):
        raise SystemExit("--organize-to can't be inside the folder being organized")

    # A section that holds every student (a course-wide default) never
    # receives anyone, so it doesn't get a folder.
    section_dirs = {sec: slug(sec, 40) for sec in index.sections
                    if sec not in index.catch_all}
    reserved = {slug(sec, 40) for sec in index.sections}
    dry = args.dry_run
    verb = "copy" if copying else "move"
    log_rows: list[dict] = []
    unmatched: list[str] = []
    counts: dict[str, int] = {}

    def is_assignment_dir(d: Path) -> bool:
        """A folder of student folders (e.g. 03_DATE-Scenario from --out)."""
        if index.match(d.name)[0]:
            return False
        try:
            return any(index.match(c.name)[0] for c in d.iterdir()
                       if not c.name.startswith("."))
        except OSError:
            return False

    def sort_folder(src: Path, dest: Path, label: str) -> None:
        items = sorted(src.iterdir(), key=lambda x: x.name.casefold())
        # Section folders go where students are: here, unless this is a run
        # folder that only holds assignment folders.
        holds_students = any(index.match(i.name)[0] for i in items) or not any(
            i.is_dir() and i.name not in reserved and is_assignment_dir(i)
            for i in items)
        if holds_students and not dry:
            for d in section_dirs.values():
                (dest / d).mkdir(parents=True, exist_ok=True)
        for item in items:
            if item.name.startswith(".") or item.name.startswith("organize_log_"):
                continue
            if item.is_dir() and item.name in reserved:
                continue                      # a section folder from an earlier run
            if item.suffix.lower() == ".xlsx" and item.name.startswith("submission_log_"):
                continue
            uid, how = index.match(item.name)
            if uid is None:
                if item.is_dir() and is_assignment_dir(item):
                    sort_folder(item, dest / item.name, f"{label}{item.name}/")
                    continue
                unmatched.append(f"{label}{item.name}  ({how})")
                log_rows.append({"Item": f"{label}{item.name}", "Student": "",
                                 "Student Canvas ID": "", "Section": "",
                                 "Destination": "", "Matched By": "",
                                 "Result": f"left in place: {how}"})
                continue
            row = index.students[uid]
            sec = index.section_of[uid]
            target = dest / section_dirs[sec] / item.name
            result = "dry run" if dry else f"{verb}d"
            if target.exists():
                result = "skipped: already exists in the section folder"
            elif not dry:
                if copying:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
                else:
                    item.rename(target)
            if not result.startswith("skipped"):
                counts[sec] = counts.get(sec, 0) + 1
            note = ""
            if uid in index.ambiguous_section:
                note = (" [in " + ", ".join(index.ambiguous_section[uid])
                        + f"; used {sec}]")
            print(f"  {label}{item.name} -> {target.relative_to(dest_root)}"
                  f"{'  (by name)' if how == 'name' else ''}{note}"
                  f"{'  SKIPPED, exists' if result.startswith('skipped') else ''}")
            log_rows.append({"Item": f"{label}{item.name}",
                             "Student": row.get("Student Full Name", ""),
                             "Student Canvas ID": uid, "Section": sec,
                             "Destination": str(target), "Matched By": how,
                             "Result": result + note})

    print(f"{'Dry run: ' if dry else ''}{verb.capitalize()} {src_root} -> "
          f"{dest_root} into {len(section_dirs)} section folder(s)")
    sort_folder(src_root, dest_root, "")

    print()
    for sec in sorted(section_dirs, key=str.casefold):
        print(f"  {section_dirs[sec]:<20} {counts.get(sec, 0):>4} item(s)")
    if unmatched:
        print(f"\n{len(unmatched)} item(s) not matched to the roster, left in place:",
              file=sys.stderr)
        for u in unmatched:
            print(f"  {u}", file=sys.stderr)
    if index.ambiguous_section:
        print(f"\nnote: {len(index.ambiguous_section)} student(s) are in more than "
              "one section; pass --section to choose", file=sys.stderr)

    if not dry:
        dest_root.mkdir(parents=True, exist_ok=True)
        log = dest_root / f"organize_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with open(log, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=["Item", "Student", "Student Canvas ID",
                                               "Section", "Destination",
                                               "Matched By", "Result"])
            w.writeheader()
            w.writerows(log_rows)
        print(f"\nLog: {log}")
    return 0


# --------------------------------------------------------------------------
# Exporting a quiz's questions and answers
# --------------------------------------------------------------------------
# New Quizzes has no QTI export in the API (only the Build page's Exports
# tab), so the questions are read from the New Quiz Items API, saved as JSON
# exactly as returned, and converted here into a QTI 1.2 package in the
# Classic Quizzes layout that Canvas's "QTI .zip file" import accepts.
# Optionally a Common Cartridge course export of the quiz's assignment is
# also requested and kept only if it actually contains the quiz.
QTI_NS = "http://www.imsglobal.org/xsd/ims_qtiasiv1p2"
CC_NS = "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"
CANVAS_META_NS = "http://canvas.instructure.com/xsd/cccv1p0"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
EXPORT_STATE_FILE = ".quiz_export_state.json"
EXPORT_FINAL_STATES = {"exported", "failed"}
EXPORT_MAX_AGE_DAYS = 30        # Canvas deletes export packages after this
ORPHAN_WINDOW_SECONDS = 180     # how far back to look for a job a failed POST started
QTI_REPORT_COLUMNS = ["Position", "Item ID", "Entry Type", "Question Type",
                      "Title", "Points", "In QTI", "Notes"]


class Unsupported(Exception):
    """An item that cannot be represented as a Classic Quizzes question."""


def strip_html(text) -> str:
    import html as _html
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    return " ".join(_html.unescape(text).split())


def _num(value) -> str:
    """Numbers as QTI wants them: 10 -> '10.0', 0.25 -> '0.25'."""
    v = float(value)
    return f"{v:.1f}" if v == int(v) and abs(v) < 1e15 else format(v, ".15g")


def _el(parent, tag: str, text=None, **attrs):
    import xml.etree.ElementTree as ET
    attrs = {k.rstrip("_"): str(v) for k, v in attrs.items() if v is not None}
    node = ET.SubElement(parent, tag, attrs) if parent is not None else ET.Element(tag, attrs)
    if text is not None:
        node.text = str(text)
    return node


def _mattext(parent, content, html: bool = True):
    mat = _el(parent, "material")
    return _el(mat, "mattext", content or "",
               texttype="text/html" if html else "text/plain")


def _xml_bytes(root) -> bytes:
    import io
    import xml.etree.ElementTree as ET
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue()


class QtiItemWriter:
    """Builds one Classic-Quizzes-style QTI <item> for a New Quiz question."""

    def __init__(self, builder: "QtiBuilder", ident: str, title: str,
                 qtype: str, points):
        self.b = builder
        self.notes: list[str] = []
        self.item = _el(None, "item", ident=ident, title=title or "Question")
        meta = _el(_el(self.item, "itemmetadata"), "qtimetadata")
        self._meta = meta
        self._field("question_type", qtype)
        self._field("points_possible", _num(points or 0))
        self.answer_ids_field = self._field("original_answer_ids", "")
        self._field("assessment_question_identifierref", ident + "_aq")
        self.presentation = _el(self.item, "presentation")
        self.rp = None
        self.feedback: dict[str, str] = {}

    def _field(self, label: str, value: str):
        f = _el(self._meta, "qtimetadatafield")
        _el(f, "fieldlabel", label)
        return _el(f, "fieldentry", value)

    def set_answer_ids(self, ids) -> None:
        self.answer_ids_field.text = ",".join(str(i) for i in ids)

    def body(self, html: str) -> None:
        _mattext(self.presentation, html)
        if "<img" in (html or "").lower():
            self.notes.append("embedded image stays a link to Canvas; "
                              "not packaged in the zip")

    def resprocessing(self, general_fb: str | None = None):
        self.rp = _el(self.item, "resprocessing")
        _el(_el(self.rp, "outcomes"), "decvar", maxvalue="100", minvalue="0",
            varname="SCORE", vartype="Decimal")
        if general_fb:
            self._feedback_cond("general_fb", general_fb, other=True)
        return self.rp

    def _feedback_cond(self, ident: str, html: str, other: bool = False,
                       varequal: tuple[str, str] | None = None) -> None:
        cond = _el(self.rp, "respcondition", continue_="Yes")
        cv = _el(cond, "conditionvar")
        if other:
            _el(cv, "other")
        else:
            _el(cv, "varequal", varequal[1], respident=varequal[0])
        _el(cond, "displayfeedback", feedbacktype="Response", linkrefid=ident)
        self.feedback[ident] = html

    def score_cond(self, value, action: str = "Set", continue_: str | None = "No"):
        cond = _el(self.rp, "respcondition", continue_=continue_)
        cv = _el(cond, "conditionvar")
        _el(cond, "setvar", value if isinstance(value, str) else _num(value),
            action=action, varname="SCORE")
        return cond, cv

    def correct_feedback(self, cond, fb: dict) -> None:
        if fb.get("correct"):
            _el(cond, "displayfeedback", feedbacktype="Response", linkrefid="correct_fb")
            self.feedback["correct_fb"] = fb["correct"]

    def incorrect_feedback(self, fb: dict) -> None:
        if fb.get("incorrect"):
            self._feedback_cond("general_incorrect_fb", fb["incorrect"], other=True)

    def finish(self):
        for ident, html in self.feedback.items():
            fbe = _el(self.item, "itemfeedback", ident=ident)
            _mattext(_el(fbe, "flow_mat"), html)
        return self.item


class QtiBuilder:
    """Turns New Quiz items into a QTI 1.2 package (Classic Quizzes flavour)."""

    def __init__(self, quiz: dict, ident: str):
        self.quiz = quiz
        self.ident = ident
        self.items = []                  # <item> elements, in quiz order
        self.report: list[dict] = []
        self._next = 1000

    def new_id(self) -> int:
        self._next += 1
        return self._next

    # ---- ordering ----------------------------------------------------------
    @staticmethod
    def ordered(items: list[dict]) -> list[dict]:
        """Quiz order, with each stimulus's questions right after it."""
        def pos(i):
            try:
                return float(i.get("position") or 0)
            except (TypeError, ValueError):
                return 0.0
        by_stim: dict[str, list[dict]] = {}
        top = []
        ids = {str(i.get("id")) for i in items}
        for it in items:
            sid = it.get("stimulus_quiz_entry_id")
            if sid and str(sid) in ids:
                by_stim.setdefault(str(sid), []).append(it)
            else:
                top.append(it)
        out = []
        for it in sorted(top, key=pos):
            out.append(it)
            out += sorted(by_stim.get(str(it.get("id")), []), key=pos)
        return out

    # ---- items -----------------------------------------------------------------
    def add(self, quiz_item: dict) -> None:
        etype = quiz_item.get("entry_type") or ""
        entry = quiz_item.get("entry") or {}
        points = quiz_item.get("points_possible") or 0
        row = {"Position": quiz_item.get("position", ""),
               "Item ID": quiz_item.get("id", ""), "Entry Type": etype,
               "Question Type": "", "Title": "", "Points": points,
               "In QTI": "no", "Notes": ""}
        notes: list[str] = []
        try:
            if etype == "Bank":
                n = (quiz_item.get("properties") or {}).get("sample_num")
                row["Title"] = entry.get("title", "")
                raise Unsupported(
                    f"draws {n or 'all'} question(s) at random from item bank "
                    f"'{entry.get('title', '')}' ({entry.get('item_entry_count', '?')} "
                    "items); bank contents are not available through the API")
            if etype == "BankEntry":
                notes.append(f"single question from item bank {entry.get('bank_id', '?')}")
                etype = entry.get("entry_type") or "Item"
                entry = entry.get("entry") or {}
            row["Title"] = entry.get("title", "")
            if etype == "Stimulus":
                row["Question Type"] = "stimulus"
                w = self._stimulus(quiz_item, entry)
            elif etype == "Item":
                slug_ = entry.get("interaction_type_slug") or ""
                row["Question Type"] = slug_
                w = self._question(quiz_item, entry, slug_, points)
            else:
                raise Unsupported(f"unknown entry type {etype!r}")
            notes += w.notes
            self.items.append(w.finish())
            row["In QTI"] = "yes"
        except Unsupported as exc:
            notes.append(str(exc))
        row["Notes"] = "; ".join(notes)
        self.report.append(row)

    def _writer(self, quiz_item: dict, entry: dict, qtype: str, points) -> QtiItemWriter:
        ident = f"i{quiz_item.get('id', self.new_id())}"
        return QtiItemWriter(self, ident, entry.get("title") or "Question", qtype, points)

    def _stimulus(self, quiz_item: dict, entry: dict) -> QtiItemWriter:
        w = self._writer(quiz_item, entry, "text_only_question", 0)
        parts = []
        if entry.get("title"):
            parts.append(f"<h3>{_escape(entry['title'])}</h3>")
        parts.append(entry.get("body") or "")
        if entry.get("instructions"):
            parts.append(f"<p>{entry['instructions']}</p>")
        w.body("\n".join(parts))
        w.resprocessing()
        w.notes.append("stimulus exported as a text-only question; Classic "
                       "Quizzes cannot pin it beside its questions")
        return w

    def _question(self, quiz_item, entry, slug_, points) -> QtiItemWriter:
        handler = {
            "choice": self._choice, "true-false": self._true_false,
            "multi-answer": self._multi_answer, "essay": self._essay,
            "file-upload": self._file_upload, "numeric": self._numeric,
            "matching": self._matching, "rich-fill-blank": self._rich_fill_blank,
            "fill-blank": self._fill_blank,
        }.get(slug_)
        if handler is None:
            raise Unsupported(f"'{slug_}' questions have no Classic Quizzes "
                              "equivalent; kept in the JSON only")
        return handler(quiz_item, entry, points)

    # Each handler gets the QuizItem, its QuestionItem entry, and points.
    @staticmethod
    def _choice_body(c: dict) -> str:
        return c.get("item_body") or c.get("itemBody") or ""

    def _choice(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        fb = e.get("feedback") or {}
        choices = sorted(data.get("choices") or [], key=lambda c: c.get("position") or 0)
        correct = sd.get("value")
        ids = {c["id"]: self.new_id() for c in choices}
        if correct not in ids:
            raise Unsupported("no correct answer recorded")
        w = self._writer(qi, e, "multiple_choice_question", points)
        w.body(e.get("item_body"))
        lid = _el(w.presentation, "response_lid", ident="response1", rcardinality="Single")
        rc = _el(lid, "render_choice")
        for c in choices:
            _mattext(_el(rc, "response_label", ident=ids[c["id"]]), self._choice_body(c))
        w.set_answer_ids(ids.values())
        w.resprocessing(fb.get("neutral"))
        for cid, html in (e.get("answer_feedback") or {}).items():
            if cid in ids and html:
                w._feedback_cond(f"{ids[cid]}_fb", html,
                                 varequal=("response1", str(ids[cid])))
        cond, cv = w.score_cond(100)
        _el(cv, "varequal", ids[correct], respident="response1")
        w.correct_feedback(cond, fb)
        w.incorrect_feedback(fb)
        if (e.get("properties") or {}).get("vary_points_by_answer") or sd.get("values"):
            w.notes.append("per-answer points dropped; only the correct answer scores")
        return w

    def _true_false(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        fb = e.get("feedback") or {}
        value = sd.get("value")
        if isinstance(value, str):
            value = value.strip().lower() == "true"
        t, f = self.new_id(), self.new_id()
        w = self._writer(qi, e, "true_false_question", points)
        w.body(e.get("item_body"))
        lid = _el(w.presentation, "response_lid", ident="response1", rcardinality="Single")
        rc = _el(lid, "render_choice")
        _mattext(_el(rc, "response_label", ident=t), data.get("true_choice") or "True", html=False)
        _mattext(_el(rc, "response_label", ident=f), data.get("false_choice") or "False", html=False)
        w.set_answer_ids([t, f])
        w.resprocessing(fb.get("neutral"))
        cond, cv = w.score_cond(100)
        _el(cv, "varequal", t if value else f, respident="response1")
        w.correct_feedback(cond, fb)
        w.incorrect_feedback(fb)
        return w

    def _multi_answer(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        fb = e.get("feedback") or {}
        choices = sorted(data.get("choices") or [], key=lambda c: c.get("position") or 0)
        ids = {c["id"]: self.new_id() for c in choices}
        correct = set(sd.get("value") or [])
        if not correct & set(ids):
            raise Unsupported("no correct answer recorded")
        w = self._writer(qi, e, "multiple_answers_question", points)
        w.body(e.get("item_body"))
        lid = _el(w.presentation, "response_lid", ident="response1", rcardinality="Multiple")
        rc = _el(lid, "render_choice")
        for c in choices:
            _mattext(_el(rc, "response_label", ident=ids[c["id"]]), self._choice_body(c))
        w.set_answer_ids(ids.values())
        w.resprocessing(fb.get("neutral"))
        cond, cv = w.score_cond(100)
        both = _el(cv, "and")
        for cid, aid in ids.items():
            if cid in correct:
                _el(both, "varequal", aid, respident="response1")
            else:
                _el(_el(both, "not"), "varequal", aid, respident="response1")
        w.correct_feedback(cond, fb)
        w.incorrect_feedback(fb)
        if e.get("scoring_algorithm") == "AllOrNothing":
            w.notes.append("was all-or-nothing; Classic Quizzes gives partial credit")
        return w

    def _essay(self, qi, e, points):
        fb = e.get("feedback") or {}
        w = self._writer(qi, e, "essay_question", points)
        w.body(e.get("item_body"))
        rs = _el(w.presentation, "response_str", ident="response1", rcardinality="Single")
        _el(_el(rs, "render_fib"), "response_label", ident="answer1", rshuffle="No")
        w.resprocessing(fb.get("neutral"))
        notes = (e.get("scoring_data") or {}).get("value")
        if notes:
            w.notes.append("grading notes kept in the JSON only (Classic has no "
                           "private grading-notes field)")
        return w

    def _file_upload(self, qi, e, points):
        fb = e.get("feedback") or {}
        w = self._writer(qi, e, "file_upload_question", points)
        w.body(e.get("item_body"))
        w.resprocessing(fb.get("neutral"))
        props = e.get("properties") or {}
        if props.get("restrict_types") or (e.get("interaction_data") or {}).get("restrict_count"):
            w.notes.append("file type/count restrictions dropped")
        return w

    def _numeric(self, qi, e, points):
        import math
        fb = e.get("feedback") or {}
        answers = (e.get("scoring_data") or {}).get("value") or []
        if not answers:
            raise Unsupported("no correct answer recorded")
        w = self._writer(qi, e, "numerical_question", points)
        w.body(e.get("item_body"))
        rs = _el(w.presentation, "response_str", ident="response1", rcardinality="Single")
        _el(_el(rs, "render_fib", fibtype="Decimal"), "response_label", ident="answer1")
        w.resprocessing(fb.get("neutral"))

        def exact(cv, value, lo, hi):
            either = _el(cv, "or")
            _el(either, "varequal", _num(value), respident="response1")
            both = _el(either, "and")
            _el(both, "vargte", _num(lo), respident="response1")
            _el(both, "varlte", _num(hi), respident="response1")

        written = 0
        for a in answers:
            kind = a.get("type")
            try:
                if kind == "exactResponse":
                    v = float(a["value"])
                    lo = hi = v
                elif kind == "marginOfError":
                    v, m = float(a["value"]), float(a.get("margin") or 0)
                    if a.get("margin_type") == "percent":
                        m = abs(v) * m / 100
                        w.notes.append("percent margin converted to an absolute margin")
                    lo, hi = v - m, v + m
                elif kind == "withinARange":
                    lo, hi = float(a["start"]), float(a["end"])
                    v = None
                elif kind == "preciseResponse":
                    v, p = float(a["value"]), int(a.get("precision") or 0)
                    if a.get("precision_type") == "significantDigits" and v:
                        step = 10 ** (math.floor(math.log10(abs(v))) - p + 1)
                    else:
                        step = 10 ** (-p)
                    lo, hi = v - step / 2, v + step / 2
                    w.notes.append("precision answer converted to a range")
                else:
                    w.notes.append(f"answer type {kind!r} skipped")
                    continue
            except (KeyError, TypeError, ValueError):
                w.notes.append(f"unreadable {kind} answer skipped")
                continue
            cond, cv = w.score_cond(100)
            if v is None:
                _el(cv, "vargte", _num(lo), respident="response1")
                _el(cv, "varlte", _num(hi), respident="response1")
            else:
                exact(cv, v, lo, hi)
            w.correct_feedback(cond, fb)
            written += 1
        if not written:
            raise Unsupported("no answer could be converted")
        w.incorrect_feedback(fb)
        return w

    def _matching(self, qi, e, points):
        fb = e.get("feedback") or {}
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        questions = data.get("questions") or []
        pairs = sd.get("value") or {}
        answers = list(dict.fromkeys(
            list(data.get("answers") or [])
            + list(((sd.get("edit_data") or {}).get("distractors")) or [])
            + [str(v) for v in pairs.values()]))
        if not questions or not pairs:
            raise Unsupported("no matches recorded")
        aid = {a: self.new_id() for a in answers}
        w = self._writer(qi, e, "matching_question", points)
        w.body(e.get("item_body"))
        qids = {}
        for q in questions:
            qids[q["id"]] = self.new_id()
            lid = _el(w.presentation, "response_lid", ident=f"response_{qids[q['id']]}")
            _mattext(lid, strip_html(q.get("item_body")), html=False)
            rc = _el(lid, "render_choice")
            for a in answers:
                _mattext(_el(rc, "response_label", ident=aid[a]), a, html=False)
        w.set_answer_ids(qids.values())
        w.resprocessing(fb.get("neutral"))
        share = 100 / len(questions)
        for q in questions:
            correct = pairs.get(q["id"])
            if correct is None:
                continue
            cond, cv = w.score_cond(share, action="Add", continue_=None)
            _el(cv, "varequal", aid[str(correct)], respident=f"response_{qids[q['id']]}")
        if e.get("scoring_algorithm") == "DeepEquals":
            w.notes.append("was all-or-nothing; Classic Quizzes gives partial credit")
        return w

    def _blanks(self, qi, e, points, body: str, blank_ids: list[str],
                blanks: dict, scoring: dict, bank_choices: list[dict]):
        """Shared by both fill-in-the-blank flavours. body already holds
        [blank1], [blank2]... in place of each blank."""
        types = {(blanks.get(b) or {}).get("answer_type", "openEntry") for b in blank_ids}
        dropdowns = types <= {"dropdown", "wordbank"}
        w = self._writer(qi, e, "multiple_dropdowns_question" if dropdowns
                         else "fill_in_multiple_blanks_question", points)
        if not dropdowns and types & {"dropdown", "wordbank"}:
            w.notes.append("mixes typed and drop-down blanks; drop-downs became "
                           "typed answers")
        w.body(body)
        w.resprocessing((e.get("feedback") or {}).get("neutral"))
        share = 100 / len(blank_ids)
        all_ids = []
        for n, bid in enumerate(blank_ids, start=1):
            b = blanks.get(bid) or {}
            s = scoring.get(bid) or {}
            sdata = s.get("scoring_data") or {}
            algo = s.get("scoring_algorithm") or ""
            kind = b.get("answer_type", "openEntry")
            options: list[str]
            correct: list[str]
            if kind == "dropdown":
                opts = sorted(b.get("choices") or [], key=lambda c: c.get("position") or 0)
                options = [c.get("item_body", "") for c in opts]
                hit = [c.get("item_body", "") for c in opts if c.get("id") == sdata.get("value")]
                correct = hit or [sdata.get("blank_text") or ""]
            elif kind == "wordbank":
                options = [c.get("item_body", "") for c in bank_choices]
                hit = [c.get("item_body", "") for c in bank_choices
                       if c.get("id") == sdata.get("choice_id")]
                correct = hit or [str(sdata.get("value") or sdata.get("blank_text") or "")]
            else:
                value = sdata.get("value")
                correct = [str(v) for v in value] if isinstance(value, list) else [str(value or "")]
                if algo == "TextRegex":
                    correct = [sdata.get("blank_text") or ""]
                    w.notes.append(f"blank {n}: regex answer replaced by its example answer")
                elif algo in ("TextCloseEnough", "TextContainsAnswer"):
                    w.notes.append(f"blank {n}: {algo} matching became exact match")
                options = correct
            if not dropdowns:
                options = correct           # typed blanks list only right answers
            correct = [c for c in correct if c]
            if not correct:
                raise Unsupported(f"blank {n} has no correct answer recorded")
            label_ids = {opt: self.new_id() for opt in dict.fromkeys(options + correct)}
            all_ids += label_ids.values()
            lid = _el(w.presentation, "response_lid", ident=f"response_blank{n}")
            _mattext(lid, f"blank{n}", html=False)
            rc = _el(lid, "render_choice")
            for opt, i in label_ids.items():
                _mattext(_el(rc, "response_label", ident=i), opt, html=False)
            for c in correct:
                cond, cv = w.score_cond(share, action="Add", continue_=None)
                _el(cv, "varequal", label_ids[c], respident=f"response_blank{n}")
        w.set_answer_ids(all_ids)
        return w

    def _rich_fill_blank(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        blanks = {b["id"]: b for b in data.get("blanks") or []}
        order = [b["id"] for b in data.get("blanks") or []]
        scoring = {s["id"]: s for s in sd.get("value") or [] if "id" in s}
        working = sd.get("working_item_body") or ""
        spans = re.findall(r"`([^`]*)`", working)
        if not order or len(spans) != len(order):
            raise Unsupported("could not locate the blanks in the question text")
        counter = iter(range(1, len(order) + 1))
        body = re.sub(r"`[^`]*`", lambda _m: f"[blank{next(counter)}]", working)
        w = self._blanks(qi, e, points, body, order, blanks, scoring,
                         data.get("word_bank_choices") or [])
        for n, (span, bid) in enumerate(zip(spans, order), start=1):
            text = ((scoring.get(bid) or {}).get("scoring_data") or {}).get("blank_text")
            if text is not None and strip_html(text) != strip_html(span):
                w.notes.append(f"blank {n}: text order did not match answer order; check it")
        return w

    def _fill_blank(self, qi, e, points):
        data, sd = e.get("interaction_data") or {}, e.get("scoring_data") or {}
        blanks = {b["id"]: b for b in data.get("blanks") or []}
        scoring = {s["id"]: s for s in sd.get("value") or [] if "id" in s}
        parts, order = [], []
        for s in sorted(data.get("stem_items") or [], key=lambda s: s.get("position") or 0):
            if s.get("type") == "blank":
                order.append(s.get("blank_id"))
                parts.append(f"[blank{len(order)}]")
            else:
                parts.append(_escape(s.get("value") or ""))
        if not order:
            raise Unsupported("no blanks found")
        body = (data.get("prompt") or "") + f"<p>{''.join(parts)}</p>"
        return self._blanks(qi, e, points, body, order, blanks, scoring, [])

    # ---- package -----------------------------------------------------------
    def assessment_xml(self) -> bytes:
        root = _el(None, "questestinterop", xmlns=QTI_NS)
        root.set("xmlns:xsi", XSI_NS)
        root.set("xsi:schemaLocation",
                 f"{QTI_NS} http://www.imsglobal.org/xsd/ims_qtiasiv1p2p1.xsd")
        assessment = _el(root, "assessment", ident=self.ident,
                         title=self.quiz.get("title") or "Quiz")
        meta = _el(assessment, "qtimetadata")
        f = _el(meta, "qtimetadatafield")
        _el(f, "fieldlabel", "cc_maxattempts")
        _el(f, "fieldentry", self._allowed_attempts())
        section = _el(assessment, "section", ident="root_section")
        section.extend(self.items)
        return _xml_bytes(root)

    def _allowed_attempts(self) -> str:
        ma = (self.quiz.get("quiz_settings") or {}).get("multiple_attempts") or {}
        if not ma.get("multiple_attempts_enabled"):
            return "1"
        return str(ma.get("max_attempts") or 1) if ma.get("attempt_limit") else "-1"

    def meta_xml(self) -> bytes:
        q, s = self.quiz, self.quiz.get("quiz_settings") or {}
        ma = s.get("multiple_attempts") or {}
        root = _el(None, "quiz", identifier=self.ident, xmlns=CANVAS_META_NS)
        _el(root, "title", q.get("title") or "Quiz")
        _el(root, "description", q.get("instructions") or "")
        _el(root, "shuffle_answers", str(bool(s.get("shuffle_answers"))).lower())
        _el(root, "scoring_policy", {"latest": "keep_latest", "average": "keep_average"}
            .get(ma.get("score_to_keep"), "keep_highest"))
        _el(root, "quiz_type", "assignment")
        if q.get("points_possible") is not None:
            _el(root, "points_possible", _num(q["points_possible"]))
        _el(root, "allowed_attempts", self._allowed_attempts())
        if s.get("has_time_limit") and s.get("session_time_limit_in_seconds"):
            _el(root, "time_limit", max(1, int(s["session_time_limit_in_seconds"]) // 60))
        _el(root, "one_question_at_a_time",
            str(s.get("one_at_a_time_type") == "question").lower())
        _el(root, "cant_go_back", str(s.get("one_at_a_time_type") == "question"
                                      and not s.get("allow_backtracking")).lower())
        return _xml_bytes(root)

    def manifest_xml(self) -> bytes:
        root = _el(None, "manifest", identifier=f"{self.ident}_manifest", xmlns=CC_NS)
        md = _el(root, "metadata")
        _el(md, "schema", "IMS Content")
        _el(md, "schemaversion", "1.1.3")
        _el(root, "organizations")
        res = _el(root, "resources")
        main = _el(res, "resource", identifier=self.ident, type="imsqti_xmlv1p2")
        _el(main, "file", href=f"{self.ident}/{self.ident}.xml")
        _el(main, "dependency", identifierref=f"{self.ident}_meta")
        meta = _el(res, "resource", identifier=f"{self.ident}_meta",
                   type="associatedcontent/imscc_xmlv1p1/learning-application-resource",
                   href=f"{self.ident}/assessment_meta.xml")
        _el(meta, "file", href=f"{self.ident}/assessment_meta.xml")
        return _xml_bytes(root)

    def write_zip(self, path: Path) -> None:
        tmp = path.with_name(path.name + ".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("imsmanifest.xml", self.manifest_xml())
            zf.writestr(f"{self.ident}/{self.ident}.xml", self.assessment_xml())
            zf.writestr(f"{self.ident}/assessment_meta.xml", self.meta_xml())
        tmp.replace(path)


def _escape(text: str) -> str:
    import html as _html
    return _html.escape(text or "", quote=False)


def verify_qti_zip(path: Path, expected_items: int) -> None:
    """Reopen the package and check every XML part parses and no item was lost."""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad:
            raise IOError(f"{path.name}: corrupt member {bad}")
        names = zf.namelist()
        if "imsmanifest.xml" not in names:
            raise IOError(f"{path.name}: no imsmanifest.xml")
        found = 0
        for name in names:
            root = ET.fromstring(zf.read(name))
            found += sum(1 for el in root.iter() if el.tag.endswith("item")
                         and el.tag.rsplit("}", 1)[-1] == "item")
    if found != expected_items:
        raise IOError(f"{path.name}: {found} item(s) written, expected {expected_items}")


def quiz_kind(assignment: dict) -> str | None:
    """'new' for a New Quiz, 'classic' for a Classic Quiz, None otherwise."""
    if assignment.get("is_quiz_lti_assignment"):
        return "new"
    if assignment.get("quiz_id") or "online_quiz" in (assignment.get("submission_types") or []):
        return "classic"
    tool = (assignment.get("external_tool_tag_attributes") or {}).get("url") or ""
    if "external_tool" in (assignment.get("submission_types") or []) and "quiz-lti" in tool:
        return "new"
    return None


def assignment_folder(out_root: Path, assignment: dict) -> Path:
    """The assignment's folder in the --out tree.

    Reuses an existing NN_<name> folder (from a download run) if there is
    exactly one; otherwise uses 01_<name>, the name a download run with this
    single --assignment would create.
    """
    name = slug(assignment.get("name") or str(assignment.get("id")))
    pattern = re.compile(r"^\d{2,}_" + re.escape(name) + r"$")
    if out_root.is_dir():
        hits = [d for d in out_root.iterdir() if d.is_dir() and pattern.match(d.name)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            print(f"  note: several folders match {name}; using {hits[0].name}",
                  file=sys.stderr)
            return sorted(hits)[0]
    return out_root / f"01_{name}"


@dataclass
class QuizExportPlan:
    """Where a quiz export goes and whose answers it keeps."""
    dirs: list[Path]                        # every output folder
    selected: set[int] | None = None        # students to keep; None = everyone
    dir_of: dict[int, Path] | None = None   # with --by-section: student -> folder
    roster: Roster | None = None


def quiz_export_plan(canvas: Canvas, args, assignment: dict) -> QuizExportPlan | None:
    """Apply --section/--student/--by-section to a quiz export.

    The filters pick whose answers are kept: selected students who are
    assigned the quiz. With --by-section each of their sections gets a folder
    holding that section's answers plus a copy of the quiz content. Returns
    None when no selected student is assigned the quiz.
    """
    adir = assignment_folder(Path(args.out), assignment)
    if not (args.section or args.student or args.by_section):
        return QuizExportPlan([adir])
    roster = Roster(canvas.sections(args.course),
                    canvas.student_enrollments(args.course))
    student_ids, section_ids = select_students(roster, args)
    assigned = assigned_students(canvas, args.course, [assignment["id"]])
    chosen = assigned if student_ids is None else student_ids & assigned
    if student_ids is not None:
        print(f"{len(chosen)} of {len(student_ids)} selected student(s) are "
              "assigned this quiz.")
    if not chosen:
        return None
    selected = chosen if student_ids is not None else None
    if not args.by_section:
        return QuizExportPlan([adir], selected, None, roster)
    dir_of = {u: adir / slug((roster.primary_section(u, section_ids) or {}).get("name")
                             or "no-section", 40) for u in chosen}
    dirs = sorted(set(dir_of.values()), key=lambda d: d.name.casefold())
    return QuizExportPlan(dirs, selected, dir_of, roster)


# ---- student answers (New Quizzes student analysis report) -------------------
ANSWERS_STATE_KEY = "new_quiz_report:student_analysis:csv"
REPORT_REUSE_SECONDS = 30 * 60   # a finished report this recent may be reused


def find_student_column(header: list[str], rows: list[list[str]],
                        roster: Roster) -> tuple[int, str, dict] | None:
    """Which report column identifies the student, judged by its values.

    Instructure does not document the report's columns, so this does not
    rely on header names: it picks the column whose values match the course
    roster best -- Canvas user IDs first, then SIS IDs, logins, and finally
    names. Returns (column index, what it matched, value -> user id).
    """
    users = roster.users.values()
    by_name: dict[str, set[int]] = {}
    for u in users:
        for n in (u.get("name"), u.get("sortable_name")):
            if _letters(n):
                by_name.setdefault(_letters(n), set()).add(u["id"])
    lookups = [
        ("Canvas user ID", {str(u["id"]): u["id"] for u in users}, str.strip),
        ("SIS user ID", {str(u["sis_user_id"]): u["id"] for u in users
                         if u.get("sis_user_id")}, str.strip),
        ("login", {str(u["login_id"]).casefold(): u["id"] for u in users
                   if u.get("login_id")}, lambda v: v.strip().casefold()),
        ("name", {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1},
         _letters),
    ]
    hinted = ("id", "user", "student", "name", "login", "sis")
    for kind, mapping, norm in lookups:
        best = None
        for c, head in enumerate(header):
            vals = [r[c] for r in rows if c < len(r) and r[c].strip()]
            if not vals:
                continue
            rate = sum(norm(v) in mapping for v in vals) / len(vals)
            score = (rate, any(h in head.casefold() for h in hinted))
            if rate >= 0.6 and (best is None or score > best[0]):
                best = (score, c)
        if best:
            c = best[1]
            return c, kind, {v: mapping[norm(v)] for v in
                             {r[c] for r in rows if c < len(r)} if norm(v) in mapping}
    return None


def write_answers(raw: Path, plan: QuizExportPlan, name: str) -> tuple[list[Path], list[str]]:
    """Put the downloaded report into each output folder.

    No filters: the report is copied unchanged. With --section/--student or
    --by-section: only the selected students' rows are kept, split by section
    folder, under the report's own header. Every output folder gets a file,
    even if that section has no attempts yet.
    """
    if plan.selected is None and plan.dir_of is None:
        dest = plan.dirs[0] / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, dest)
        return [dest], []

    with open(raw, newline="", encoding="utf-8-sig") as fh:
        table = list(csv.reader(fh))
    if not table:
        raise ValueError("the student analysis report is empty")
    header, body = table[0], table[1:]
    notes: list[str] = []
    out: dict[Path, list[list[str]]] = {d: [] for d in plan.dirs}
    if body:
        found = find_student_column(header, body, plan.roster)
        if found is None:
            raise ValueError(
                "could not tell which report column identifies the student, so "
                "the answers can't be filtered by --section/--student/--by-section "
                "(nothing was written). Report columns: " + ", ".join(header))
        col, kind, uid_of = found
        print(f"  students identified by column '{header[col]}' ({kind})")
        if kind == "name":
            notes.append("students in the answers report were matched by name; "
                         "check the split if two students share a name")
        dropped = off_roster = 0
        for row in body:
            uid = uid_of.get(row[col]) if col < len(row) else None
            if uid is None:
                off_roster += 1
                continue
            if plan.selected is not None and uid not in plan.selected:
                dropped += 1
                continue
            dest = plan.dir_of.get(uid) if plan.dir_of is not None else plan.dirs[0]
            if dest is None:
                dropped += 1
                continue
            out[dest].append(row)
        if off_roster:
            notes.append(f"{off_roster} answer row(s) belong to people not on the "
                         "current student roster (e.g. Test Student, dropped "
                         "students) and were left out")
        if dropped:
            print(f"  {dropped} row(s) for students outside the selection left out")
    written = []
    for d, rows in out.items():
        d.mkdir(parents=True, exist_ok=True)
        dest = d / name
        tmp = dest.with_name(dest.name + ".part")
        with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        tmp.replace(dest)
        print(f"  {dest}: {len(rows)} row(s)")
        written.append(dest)
    return written, notes


def run_quiz_report(canvas: Canvas, course_id: int, assignment_id: int,
                    state_path: Path, dest: Path, timeout: float) -> Path:
    """Generate the student analysis report, wait for it, download it to dest.

    The Progress ID is saved to state_path as soon as Canvas returns it; a
    rerun resumes that job instead of starting another. Canvas answers 409
    while a report of this type is already being generated (by this tool or
    in the browser); that is waited out with the same capped, growing
    interval as polling, then requested again. A POST that fails any other
    way is never repeated.
    """
    state = _load_state(state_path)
    progress = None
    saved = state.get(ANSWERS_STATE_KEY)
    if saved and saved.get("course_id") == course_id \
            and saved.get("assignment_id") == assignment_id:
        try:
            progress = canvas.progress(saved["progress_id"])
        except requests.HTTPError:
            progress = None
        if progress:
            st = progress.get("workflow_state")
            age = time.time() - (parse_ts(progress.get("updated_at")) or
                                 datetime.fromtimestamp(0).astimezone()).timestamp()
            if st == "failed" or (st == "completed" and age > REPORT_REUSE_SECONDS):
                progress = None
        if progress:
            print(f"  resuming report job {progress['id']} "
                  f"({progress.get('workflow_state')})")

    deadline = time.monotonic() + timeout
    if progress is None:
        wait, told = POLL_START, False
        while True:
            try:
                progress = canvas.create_quiz_report(course_id, assignment_id)
                if progress.get("id", None):
                    break
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                remaining = deadline - time.monotonic()
                if status != 409:
                    raise RuntimeError(f"Canvas refused the student analysis report "
                                       f"({exc})") from exc
                if remaining <= 0:
                    raise TimeoutError("another student analysis report for this "
                                       "quiz was still being generated after "
                                       f"{timeout:.0f}s; try again later") from exc
                if not told:
                    print("  a student analysis report is already being generated; "
                          "waiting for it to finish")
                    told = True
                print(f"retrying in {min(wait, remaining)}")
                canvas.sleep(min(wait, remaining))
                wait = min(POLL_CAP, wait * POLL_FACTOR)
        state[ANSWERS_STATE_KEY] = {"course_id": course_id,
                                    "assignment_id": assignment_id,
                                    "progress_id": progress["id"]}
        _save_state(state_path, state)
        print(f"  started report job {progress['id']}")

    last = [progress.get("completion")]

    def report(p):
        if p.get("completion") != last[0] and p.get("completion") is not None:
            last[0] = p.get("completion")
            print(f"  report {p['id']}: {p.get('workflow_state')} {last[0]}%")

    progress, done = poll_until(
        lambda: canvas.progress(progress["id"]),
        lambda p: p.get("workflow_state") in ("completed", "failed"),
        max(0.0, deadline - time.monotonic()), sleep=canvas.sleep, on_poll=report)
    if not done:
        raise TimeoutError(f"report job {progress['id']} is still "
                           f"{progress.get('workflow_state')} after {timeout:.0f}s. "
                           "Rerun the same command to pick it up; no new job "
                           "will be started.")
    if progress.get("workflow_state") == "failed":
        state.pop(ANSWERS_STATE_KEY, None)
        _save_state(state_path, state)
        raise RuntimeError(f"Canvas reports the student analysis report failed"
                           + (f": {progress['message']}" if progress.get("message") else ""))
    results = progress.get("results")
    url = results.get("url") if isinstance(results, dict) else None
    if not url:
        raise RuntimeError("the report finished but Canvas gave no download link")
    dest.unlink(missing_ok=True)
    canvas.fetch_file(url, dest, auth=True)
    state.pop(ANSWERS_STATE_KEY, None)      # kept until now so a failed
    _save_state(state_path, state)          # download can resume the job
    return dest


# ---- content export jobs ------------------------------------------------------
def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


def _export_expired(export: dict) -> bool:
    from datetime import timezone, timedelta
    created = parse_ts(export.get("created_at"))
    return bool(created and datetime.now(timezone.utc) - created
                > timedelta(days=EXPORT_MAX_AGE_DAYS))


def _find_orphan_export(canvas: Canvas, course_id: int, export_type: str,
                        started) -> dict | None:
    """After a POST that errored: the one job it may have started anyway."""
    from datetime import timedelta
    try:
        me = canvas.self_user().get("id")
        recent = canvas.content_exports(course_id)
    except requests.RequestException:
        return None
    since = started - timedelta(seconds=ORPHAN_WINDOW_SECONDS)
    hits = [e for e in recent
            if e.get("export_type") == export_type and e.get("user_id") == me
            and e.get("workflow_state") != "failed"
            and (parse_ts(e.get("created_at")) or since) >= since]
    return hits[0] if len(hits) == 1 else None


def run_content_export(canvas: Canvas, course_id: int, export_type: str,
                       select: dict[str, list], state_path: Path,
                       dest: Path, timeout: float) -> Path:
    """Start (or resume) a content export, wait for it, download it to dest.

    Duplicate protection: the job ID is saved to state_path the moment Canvas
    returns it. A rerun after an interruption or timeout resumes that job
    instead of starting another; the entry is cleared once the file is
    downloaded. A POST that errors is never retried -- Canvas may have
    started the job anyway -- so the recent export list is checked for it.
    """
    from datetime import timezone
    key = f"{export_type}:" + json.dumps(select, sort_keys=True)
    state = _load_state(state_path)
    export = None
    saved = state.get(key)
    if saved and saved.get("course_id") == course_id:
        try:
            export = canvas.content_export(course_id, saved["export_id"])
        except requests.HTTPError:
            export = None
        if export and (export.get("workflow_state") == "failed" or _export_expired(export)):
            export = None
        if export:
            print(f"  resuming export {export['id']} started "
                  f"{fmt_ts(export.get('created_at'))} UTC (state "
                  f"{export.get('workflow_state')})")

    if export is None:
        started = datetime.now(timezone.utc)
        try:
            export = canvas.create_content_export(course_id, export_type, select)
        except requests.RequestException as exc:
            export = _find_orphan_export(canvas, course_id, export_type, started)
            if export is None:
                raise RuntimeError(
                    f"starting the {export_type} export failed ({exc}). Canvas may "
                    "still have started it: check Settings > Export Course Content "
                    "before rerunning.") from exc
            print(f"  the request errored, but Canvas started export {export['id']}; "
                  "using it")
        else:
            print(f"  started export {export['id']}")
        state[key] = {"course_id": course_id, "export_id": export["id"],
                      "created_at": export.get("created_at")}
        _save_state(state_path, state)

    last_state = [export.get("workflow_state")]

    def report(e):
        if e.get("workflow_state") != last_state[0]:
            last_state[0] = e.get("workflow_state")
            print(f"  export {e['id']}: {last_state[0]}")

    export, done = poll_until(
        lambda: canvas.content_export(course_id, export["id"]),
        lambda e: e.get("workflow_state") in EXPORT_FINAL_STATES,
        timeout, sleep=canvas.sleep, on_poll=report)
    if not done:
        raise TimeoutError(
            f"export {export['id']} is still {export.get('workflow_state')} after "
            f"{timeout:.0f}s. Rerun the same command to pick it up; no new job "
            "will be started.")
    if export.get("workflow_state") == "failed":
        state.pop(key, None)
        _save_state(state_path, state)
        raise RuntimeError(f"Canvas reports export {export['id']} failed")
    attachment = export.get("attachment") or {}
    if not attachment.get("url"):
        state.pop(key, None)
        _save_state(state_path, state)
        raise RuntimeError(f"export {export['id']} finished but has no download link")

    dest.unlink(missing_ok=True)            # never treat an old file as cached
    canvas.fetch_file(attachment["url"], dest, attachment.get("size"), auth=True)
    if not zipfile.is_zipfile(dest):
        raise IOError(f"export {export['id']} download is not a zip package")
    state.pop(key, None)
    _save_state(state_path, state)
    return dest


def package_contains_quiz(path: Path, quiz: dict, items: list[dict]) -> tuple[bool, str]:
    """Does a downloaded course export actually hold this quiz's questions?"""
    import html as _html
    title = (quiz.get("title") or "").strip()
    probes = [t for t in (
        strip_html((i.get("entry") or {}).get("item_body"))[:40]
        for i in items if i.get("entry_type") == "Item") if len(t) >= 12][:5]
    qti_files, title_hit, text_hit = [], False, False
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.file_size > 50 * 1024 * 1024:
                continue
            if not info.filename.lower().endswith((".xml", ".qti")):
                continue
            raw = zf.read(info).decode("utf-8", "replace")
            if "questestinterop" in raw or "<assessmentItem" in raw or "<assessmentTest" in raw:
                qti_files.append(info.filename)
            plain = " ".join(_html.unescape(_html.unescape(raw)).split())
            if title and title in plain:
                title_hit = True
            if any(p in plain for p in probes):
                text_hit = True
    if not qti_files:
        return False, "the course export has no quiz (QTI) files"
    if not (title_hit or text_hit):
        return False, "the course export's quiz files don't include this quiz"
    return True, f"{len(qti_files)} quiz file(s) inside"


# ---- File Upload answers (best effort, from the student analysis report) -----
# New Quizzes has no API for the files students upload to File Upload
# questions, and they are not attachments on the Canvas submission. The
# student analysis report is the only place they may surface, as links in
# the response cells; Instructure does not document that, so this looks for
# file links by value and reports what it found either way.
URL_RE = re.compile(r"https?://[^\s\"'<>\[\](){},;|]+")
CANVAS_FILE_ID_RE = re.compile(r"/files/(\d+)")
UPLOAD_HOST_HINTS = ("inst-fs", "inscloudgate", "instructure", "quiz-lti",
                     "amazonaws.com")


def _is_file_link(url: str, canvas_host: str) -> bool:
    host = requests.utils.urlparse(url).netloc.lower()
    return (host == canvas_host or any(h in host for h in UPLOAD_HOST_HINTS)
            or bool(CANVAS_FILE_ID_RE.search(url)))


def download_report_uploads(canvas: Canvas, raw: Path, plan: QuizExportPlan,
                            course_id: int, stem: str) -> tuple[int, list[str]]:
    """Download every file linked from the answers report into
    <folder>/<Quiz>_uploads/<Student>_<id>/. Returns (files saved, notes)."""
    with open(raw, newline="", encoding="utf-8-sig") as fh:
        table = list(csv.reader(fh))
    if len(table) < 2:
        return 0, ["file uploads: the student analysis report has no rows"]
    header, body = table[0], table[1:]
    canvas_host = requests.utils.urlparse(canvas.base).netloc.lower()

    roster = plan.roster or Roster(canvas.sections(course_id),
                                   canvas.student_enrollments(course_id))
    found = find_student_column(header, body, roster)
    col_student, _, uid_of = found if found else (None, None, {})

    links = []   # (row, column, url)
    for r, row in enumerate(body):
        for c, cell in enumerate(row):
            if c == col_student:
                continue
            for url in URL_RE.findall(cell or ""):
                url = url.rstrip(".")
                if _is_file_link(url, canvas_host):
                    links.append((r, c, url))
    if not links:
        upload_cells = sum(1 for row in body for cell in row
                           if "file" in (cell or "").casefold()
                           and "upload" in (cell or "").casefold())
        return 0, ["file uploads: the student analysis report contains no file "
                   "links, so the uploads can't be fetched this way"
                   + (f" ({upload_cells} cell(s) mention File Upload, so the "
                      "report lists those answers without a link)"
                      if upload_cells else "")
                   + ". Report columns: " + ", ".join(header)]

    print(f"  {len(links)} file link(s) found in the report")
    saved, notes, log = 0, [], []
    seen: set[tuple[int | None, str]] = set()
    for r, c, url in links:
        row = body[r]
        uid = uid_of.get(row[col_student]) if col_student is not None else None
        if plan.selected is not None and uid not in plan.selected:
            continue
        key = (uid, url)
        if key in seen:
            continue
        seen.add(key)
        if uid is not None:
            u = roster.users.get(uid) or {}
            who = f"{slug(u.get('sortable_name') or u.get('name') or 'student', 45)}_{uid}"
            base = (plan.dir_of or {}).get(uid, plan.dirs[0])
        else:
            who, base = "unmatched", plan.dirs[0]
        folder = base / f"{stem}_uploads" / who
        question = slug(header[c] if c < len(header) else f"col{c}", 30)
        status, fname = "", ""
        try:
            m = CANVAS_FILE_ID_RE.search(url)
            host = requests.utils.urlparse(url).netloc.lower()
            if m and host == canvas_host:
                meta = canvas.file(m.group(1))
                fname = safe_filename(meta.get("display_name") or meta.get("filename")
                                      or m.group(1))
                target = folder / f"{question}__{fname}"
                fresh = canvas.fetch_file(meta["url"], target, meta.get("size"))
            else:
                fname = safe_filename(requests.utils.unquote(
                    requests.utils.urlparse(url).path.rsplit("/", 1)[-1]) or "file")
                target = folder / f"{question}__{fname}"
                fresh = canvas.fetch_file(url, target, auth=(host == canvas_host))
            saved += 1
            status = "downloaded" if fresh else "cached"
            print(f"    {status} {target.relative_to(base)}")
        except (requests.RequestException, OSError, KeyError) as exc:
            status = f"failed: {exc}"
            print(f"    ! {who}: {url}: {exc}")
        log.append({"student_folder": who, "user_id": uid or "",
                    "report_column": header[c] if c < len(header) else c,
                    "url": url, "file": fname, "status": status})

    if col_student is None:
        notes.append("file uploads: could not tell which report column is the "
                     "student, so files were saved under 'unmatched'")
    failed = sum(1 for x in log if x["status"].startswith("failed"))
    if failed:
        notes.append(f"file uploads: {failed} link(s) could not be downloaded "
                     "(see the uploads log)")
    for d in plan.dirs:
        rows = [x for x in log if (plan.dir_of or {}).get(x["user_id"] or None,
                                                          plan.dirs[0]) == d]
        if not rows:
            continue
        p = d / f"{stem}_uploads" / "uploads_log.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return saved, notes


# ---- File Upload answers via a real browser (Playwright) ----------------------
# Found by recording SpeedGrader (HAR): for a New Quiz, SpeedGrader embeds
# the New Quizzes grading view, which calls the quiz API at
#   https://<school>.quiz-api-<region>-prod.instructure.com
#     /api/quiz_sessions/<quiz_session_id>/results/<result_id>/session_item_results
# For a File Upload item, that JSON carries
#   scored_data.value = [{"name": ..., "size": ..., "url": <file in S3>}, ...]
# The Canvas submission links to the same quiz_session_id (its LTI launch
# URL), so every file is matched to its student exactly. The quiz API only
# accepts the short-lived token New Quizzes gets inside the browser, which is
# why a browser is needed: this mode signs in once with a saved profile,
# opens each student in SpeedGrader and reads that response as it loads.
QUIZ_RESULTS_RE = re.compile(r"/api/quiz_sessions/(\d+)/results/\d+/session_item_results")
QUIZ_SESSION_RE = re.compile(r"/api/quiz_sessions/(\d+)(?:\?|$)")
LAUNCH_SESSION_RE = re.compile(r"quiz_session_id(?:=|%3D)(\d+)")


def submission_quiz_session(sub: dict) -> str | None:
    """The New Quizzes quiz_session_id in a submission's LTI launch URL."""
    m = LAUNCH_SESSION_RE.search(json.dumps(sub))
    return m.group(1) if m else None


def uploads_in_results(results) -> list[dict]:
    """File Upload answers in a session_item_results response."""
    out = []
    for r in results if isinstance(results, list) else []:
        value = ((r or {}).get("scored_data") or {}).get("value")
        if not isinstance(value, list):
            continue
        for f in value:
            if isinstance(f, dict) and f.get("url"):
                out.append({"position": r.get("position"), "item_id": r.get("item_id"),
                            "name": f.get("name") or "file", "size": f.get("size"),
                            "url": f["url"]})
    return out


def browser_quiz_uploads(canvas: Canvas, args) -> int:
    """--browser-uploads: download a New Quiz's File Upload answers through
    SpeedGrader in a Playwright-driven browser."""
    if not args.assignment or len(args.assignment) != 1:
        raise SystemExit("--browser-uploads needs exactly one --assignment "
                         "(the quiz's assignment ID).")
    cid, aid = args.course, args.assignment[0]
    try:
        assignment = canvas.assignment(cid, aid)
    except requests.HTTPError as exc:
        raise SystemExit(f"Assignment {aid} not found in course {cid} ({exc}).")
    if quiz_kind(assignment) != "new":
        raise SystemExit(f"Assignment {aid} ({assignment.get('name')}) is not a "
                         "New Quiz; use a normal download run instead.")
    print(f"[{aid}] {assignment.get('name')}  (New Quiz)")

    plan = quiz_export_plan(canvas, args, assignment)
    if plan is None:
        print("None of the selected students are assigned this quiz.", file=sys.stderr)
        return 1
    roster = plan.roster or Roster(canvas.sections(cid), canvas.student_enrollments(cid))
    stem = slug(assignment.get("name") or str(aid), 50)

    todo = []
    for sub in canvas.submissions(cid, aid):
        uid = sub.get("user_id")
        if sub.get("workflow_state") == "unsubmitted" or not sub.get("submitted_at"):
            continue
        if plan.selected is not None and uid not in plan.selected:
            continue
        if uid not in roster.users:          # Test Student, dropped students
            continue
        todo.append((uid, sub, submission_quiz_session(sub)))
    todo.sort(key=lambda t: (roster.users[t[0]].get("sortable_name") or "").casefold())
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} submitted student(s) to visit.")
    if not todo:
        return 1

    def student_folder(uid: int) -> tuple[Path, Path, str]:
        u = roster.users.get(uid) or {}
        who = f"{slug(u.get('sortable_name') or u.get('name') or 'student', 45)}_{uid}"
        base = (plan.dir_of or {}).get(uid, plan.dirs[0])
        return base, base / f"{stem}_uploads" / who, who

    if args.dry_run:
        for uid, _, sess in todo:
            _, folder, _ = student_folder(uid)
            print(f"  {folder}   quiz session {sess or '? (matched by page load)'}")
        print("Dry run: no browser opened, nothing downloaded.")
        return 0

    try:
        from playwright.sync_api import sync_playwright, Error as PWError
    except ImportError:
        raise SystemExit("Playwright is not installed: pip install playwright "
                         "(then 'playwright install chromium' if you use "
                         "--browser-channel chromium).")

    log: list[dict] = []
    saved = failed = no_files = 0
    profile = Path(args.browser_profile).expanduser().resolve()
    channel = None if args.browser_channel == "chromium" else args.browser_channel

    with sync_playwright() as pw:
        attached = bool(args.connect_browser)
        if attached:
            # A browser the user started with --remote-debugging-port: sign-in
            # (SSO, CAC certificate prompt, 2FA) behaves exactly as normal,
            # because Playwright did not launch it.
            print(f"Connecting to your browser at {args.connect_browser} ...")
            try:
                browser = pw.chromium.connect_over_cdp(args.connect_browser)
            except PWError as exc:
                raise SystemExit(
                    f"Could not connect to {args.connect_browser}: {exc}\n"
                    "Start the browser first, e.g. (Windows, Chrome):\n"
                    '  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                    "--remote-debugging-port=9222 --user-data-dir=C:\\canvas-browser-profile\n"
                    "and keep it open.")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            print(f"Starting {args.browser_channel} with profile {profile} ...")
            ctx = pw.chromium.launch_persistent_context(
                str(profile), channel=channel, headless=args.headless,
                accept_downloads=True, viewport={"width": 1400, "height": 900})
        captured: dict[str, dict] = {}

        def on_response(resp):
            m = QUIZ_RESULTS_RE.search(resp.url)
            if m and resp.status == 200:
                try:
                    captured.setdefault(m.group(1), {})["results"] = resp.json()
                except Exception:
                    pass
                return
            m = QUIZ_SESSION_RE.search(resp.url)
            if m and resp.status == 200 and "quiz-api" in resp.url:
                try:
                    meta = (resp.json() or {}).get("metadata") or {}
                    captured.setdefault(m.group(1), {})["name"] = meta.get("user_full_name")
                except Exception:
                    pass

        ctx.on("response", on_response)
        # Any route turns off the HTTP cache for matching requests, so a
        # rerun never gets an empty "304 Not Modified" instead of the JSON.
        ctx.route("**/api/quiz_sessions/**", lambda route: route.continue_())
        # Our own tab, so an attached browser's existing tabs are left alone.
        page = ctx.new_page() if attached or not ctx.pages else ctx.pages[0]
        course_url = f"{canvas.base}/courses/{cid}"

        def signed_in_page():
            for pg in ctx.pages:
                try:
                    u = pg.url
                except PWError:
                    continue
                if u.startswith(course_url) or (u.startswith(canvas.base)
                                                and "/login" not in u):
                    return pg
            return None

        print("Opening Canvas ...")
        try:
            # "commit" returns as soon as the server answers, so an SSO
            # redirect chain or certificate prompt can't block this call.
            page.goto(course_url, wait_until="commit", timeout=60_000)
        except PWError as exc:
            print(f"  (first page load did not finish: {str(exc).splitlines()[0]})")
        page.wait_for_timeout(2000)
        if signed_in_page() is None:
            print("Sign in to Canvas in the browser window (SSO / CAC / 2FA as "
                  "usual). This continues by itself once Canvas has loaded; "
                  f"waiting up to {args.signin_timeout:.0f}s.")
            deadline = time.monotonic() + args.signin_timeout
            last_note = time.monotonic()
            # Polling with wait_for_timeout keeps Playwright processing
            # events while you sign in (a blocking input() would not).
            while signed_in_page() is None and time.monotonic() < deadline:
                page.wait_for_timeout(1000)
                if time.monotonic() - last_note > 30:
                    last_note = time.monotonic()
                    urls = []
                    for pg in ctx.pages:
                        try:
                            urls.append(requests.utils.urlparse(pg.url).netloc or pg.url)
                        except PWError:
                            pass
                    print(f"  still waiting; open tab(s): {', '.join(urls) or 'none'}")
            found = signed_in_page()
            if found is None:
                raise SystemExit(
                    "Not signed in to Canvas after "
                    f"{args.signin_timeout:.0f}s. If the sign-in page never "
                    "finished (common with CAC certificate prompts in a browser "
                    "Playwright starts), use --connect-browser instead; see "
                    "--help.")
            if found is not page:
                page = found
        print("Signed in.")

        for n, (uid, sub, sess) in enumerate(todo, 1):
            base, folder, who = student_folder(uid)
            print(f"  [{n}/{len(todo)}] {who}", end="", flush=True)
            before = set(captured)
            url = (f"{canvas.base}/courses/{cid}/gradebook/speed_grader"
                   f"?assignment_id={aid}&student_id={uid}")
            got = None
            try:
                page.goto(url, wait_until="domcontentloaded")
                deadline = time.monotonic() + args.page_timeout
                while time.monotonic() < deadline:
                    if sess and "results" in captured.get(sess, {}):
                        got = sess
                        break
                    if not sess:
                        fresh = [s for s in captured if s not in before
                                 and "results" in captured[s]]
                        if fresh:
                            got = fresh[0]
                            break
                    page.wait_for_timeout(250)
            except PWError as exc:
                print(f"  ! page error: {exc}")
            if got is None:
                failed += 1
                print(f"  ! quiz results did not load within {args.page_timeout:.0f}s")
                log.append({"student_folder": who, "user_id": uid, "quiz_session": sess or "",
                            "question": "", "file": "", "size": "", "status":
                            "failed: quiz results did not load"})
                continue
            name_seen = captured[got].get("name")
            if not sess and name_seen and not name_matches(name_seen, roster.users[uid]):
                failed += 1
                print(f"  ! loaded quiz belongs to {name_seen!r}; skipped")
                log.append({"student_folder": who, "user_id": uid, "quiz_session": got,
                            "question": "", "file": "", "size": "",
                            "status": f"failed: page showed {name_seen}"})
                continue

            files = uploads_in_results(captured[got]["results"])
            if not files:
                no_files += 1
                print("  (no uploaded files)")
                log.append({"student_folder": who, "user_id": uid, "quiz_session": got,
                            "question": "", "file": "", "size": "", "status": "no files"})
                continue
            print(f"  {len(files)} file(s)")
            for f in files:
                fname = f"Q{f['position']}__{safe_filename(f['name'])}"
                target = folder / fname
                status = ""
                if target.exists() and (f["size"] is None
                                        or target.stat().st_size == f["size"]):
                    status = "cached"
                else:
                    try:
                        r = ctx.request.get(f["url"], timeout=120_000)
                        if not r.ok:
                            raise RuntimeError(f"HTTP {r.status}")
                        body = r.body()
                        folder.mkdir(parents=True, exist_ok=True)
                        tmp = target.with_name(target.name + ".part")
                        tmp.write_bytes(body)
                        tmp.replace(target)
                        status = "downloaded"
                        if f["size"] is not None and len(body) != f["size"]:
                            status += f" (size {len(body)}, quiz listed {f['size']})"
                    except Exception as exc:
                        # Fall back to clicking the file link in the grading view.
                        try:
                            frame = next(fr for fr in page.frames if "quiz-lti" in fr.url)
                            with page.expect_download(timeout=60_000) as dl:
                                frame.get_by_text(f["name"], exact=True).first.click()
                            folder.mkdir(parents=True, exist_ok=True)
                            dl.value.save_as(target)
                            status = "downloaded (via click)"
                        except Exception as exc2:
                            status = f"failed: {exc}; click: {exc2}"
                if status.startswith("failed"):
                    failed += 1
                else:
                    saved += 1
                print(f"      {status:<11} {target.relative_to(base)}")
                log.append({"student_folder": who, "user_id": uid, "quiz_session": got,
                            "question": f["position"], "file": f["name"],
                            "size": f["size"] or "", "status": status})
            page.wait_for_timeout(args.delay * 1000)
        if attached:
            page.close()          # leave the user's browser and tabs open
        else:
            ctx.close()

    for d in plan.dirs:
        rows = [x for x in log if (plan.dir_of or {}).get(x["user_id"], plan.dirs[0]) == d]
        if rows:
            p = d / f"{stem}_uploads" / "uploads_log.csv"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            print(f"Log: {p}")
    print(f"\n{saved} file(s) saved, {no_files} student(s) with no upload, "
          f"{failed} problem(s).")
    return 0 if not failed else 3


def export_quiz(canvas: Canvas, args) -> int:
    """--export-quiz: download one quiz's student answers and its content."""
    if not args.assignment or len(args.assignment) != 1:
        raise SystemExit("--export-quiz needs exactly one --assignment "
                         "(the quiz's assignment ID; see --list-assignments).")
    cid, aid = args.course, args.assignment[0]
    try:
        assignment = canvas.assignment(cid, aid)
    except requests.HTTPError as exc:
        raise SystemExit(f"Assignment {aid} not found in course {cid} ({exc}).")
    kind = quiz_kind(assignment)
    if kind is None:
        raise SystemExit(f"Assignment {aid} ({assignment.get('name')}) is not a quiz.")
    print(f"[{aid}] {assignment.get('name')}  "
          f"({'New Quiz' if kind == 'new' else 'Classic Quiz'})")

    plan = quiz_export_plan(canvas, args, assignment)
    if plan is None:
        print("None of the selected students are assigned this quiz; nothing "
              "exported.", file=sys.stderr)
        return 1
    adir = assignment_folder(Path(args.out), assignment)
    primary = plan.dirs[0]
    stem = slug(assignment.get("name") or str(aid), 50)
    state_path = adir / EXPORT_STATE_FILE
    shared: list[Path] = []      # written once, copied into every folder
    per_dir: list[Path] = []     # already written into each folder
    warnings: list[str] = []
    answers_missing = False      # exit 3
    course_incomplete = False    # exit 2

    if kind == "classic":
        quiz_id = assignment.get("quiz_id")
        if not quiz_id:
            raise SystemExit("Classic quiz with no quiz_id on its assignment.")
        if args.dry_run:
            print(f"Dry run: would export Classic quiz {quiz_id} as QTI to {primary}")
            return 0
        dest = primary / f"{stem}_qti.zip"
        run_content_export(canvas, cid, "qti", {"quizzes": [quiz_id]}, state_path,
                           adir / f".{stem}_qti.download", args.export_timeout
                           ).replace(dest)
        shared.append(dest)
        if not args.no_answers:
            warnings.append("student answers are only implemented for New Quizzes; "
                            "this Classic Quiz was exported without them")
            answers_missing = True
    else:
        quiz = canvas.new_quiz(cid, aid)
        items = canvas.new_quiz_items(cid, aid)
        ident = "g" + __import__("hashlib").md5(f"{cid}:{aid}".encode()).hexdigest()
        builder = QtiBuilder(quiz, ident)
        for it in QtiBuilder.ordered(items):
            builder.add(it)
        in_qti = sum(1 for r in builder.report if r["In QTI"] == "yes")
        print(f"  {len(items)} item(s); {in_qti} converted to QTI")
        for r in builder.report:
            mark = " " if r["In QTI"] == "yes" else "!"
            label = r["Question Type"] or r["Entry Type"]
            note = f"  -- {r['Notes']}" if r["Notes"] else ""
            print(f"   {mark} {str(r['Position']):>3}  {label:<16} "
                  f"{(r['Title'] or '')[:40]}{note}")
        if args.dry_run:
            what = [] if args.no_answers else ["request the student analysis report"]
            if not args.no_course_export:
                what.append("start a course export")
            print("Dry run: nothing written" + (", did not " + " or ".join(what)
                                               if what else "") + ".")
            print("Output folder(s): " + ", ".join(str(d) for d in plan.dirs))
            return 0
        if not items:
            warnings.append("the quiz has no items")

        primary.mkdir(parents=True, exist_ok=True)
        json_path = primary / f"{stem}_new-quiz.json"
        tmp = json_path.with_name(json_path.name + ".part")
        tmp.write_text(json.dumps({
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "canvas_host": args.base_url, "course_id": cid, "assignment_id": aid,
            "assignment_name": assignment.get("name"),
            "quiz": quiz, "items": items}, indent=2, ensure_ascii=False),
            encoding="utf-8")
        tmp.replace(json_path)
        json.loads(json_path.read_text(encoding="utf-8"))    # round-trip check
        shared.append(json_path)

        qti_path = primary / f"{stem}_qti.zip"
        builder.write_zip(qti_path)
        verify_qti_zip(qti_path, in_qti)
        shared.append(qti_path)

        report_path = primary / f"{stem}_qti-report.csv"
        with open(report_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=QTI_REPORT_COLUMNS)
            w.writeheader()
            w.writerows(builder.report)
        shared.append(report_path)
        if in_qti < len(items):
            warnings.append(f"{len(items) - in_qti} item(s) are in the JSON but not "
                            f"the QTI; see {report_path.name}")

        if not args.no_answers:
            print("Student answers (student analysis report):")
            raw = adir / f".{stem}_student-answers.download"
            try:
                run_quiz_report(canvas, cid, aid, state_path, raw, args.export_timeout)
                files, notes = write_answers(raw, plan, f"{stem}_student-answers.csv")
                per_dir += files
                warnings += notes
                if args.quiz_uploads:
                    print("File Upload answers (links in the report):")
                    try:
                        n, notes = download_report_uploads(canvas, raw, plan, cid, stem)
                        warnings += notes
                        if n:
                            print(f"  {n} uploaded file(s) saved under "
                                  f"{stem}_uploads/")
                    except (OSError, ValueError, csv.Error,
                            requests.RequestException) as exc:
                        warnings.append(f"file uploads: {exc}")
            except (RuntimeError, TimeoutError, OSError, ValueError, csv.Error,
                    requests.RequestException) as exc:
                warnings.append(f"student answers: {exc}")
                answers_missing = True
            finally:
                raw.unlink(missing_ok=True)    # the unfiltered report never stays

        if not args.no_course_export:
            print("Course export (Common Cartridge) of this quiz's assignment:")
            tmp_cc = adir / f".{stem}_course-export.download"
            try:
                run_content_export(canvas, cid, "common_cartridge",
                                   {"assignments": [aid]}, state_path, tmp_cc,
                                   args.export_timeout)
                ok, why = package_contains_quiz(tmp_cc, quiz, items)
                if ok:
                    cc_path = primary / f"{stem}_course-export.imscc"
                    tmp_cc.replace(cc_path)
                    shared.append(cc_path)
                    print(f"  kept: {why}")
                else:
                    warnings.append(f"course export not kept: {why}")
            except (RuntimeError, TimeoutError, OSError,
                    requests.RequestException) as exc:
                warnings.append(f"course export: {exc}")
                course_incomplete = True
            finally:
                tmp_cc.unlink(missing_ok=True)

    if state_path.exists() and not _load_state(state_path):
        state_path.unlink()
    for extra in plan.dirs[1:]:
        extra.mkdir(parents=True, exist_ok=True)
        for f in shared:
            shutil.copy2(f, extra / f.name)

    print("\nExported:")
    names = [f.name for f in shared] + sorted({f.name for f in per_dir})
    for d in plan.dirs:
        for n in names:
            p = d / n
            if p.exists():
                print(f"  {p}  ({p.stat().st_size:,} bytes)")
    for w_ in warnings:
        print(f"  ! {w_}", file=sys.stderr)
    print(f"API use: {canvas.rate_summary()}")
    if answers_missing:
        return 3
    return 2 if course_incomplete else 0


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
    p.add_argument("--base-url",
                   help="e.g. https://yourschool.instructure.com "
                        "(not needed with --organize)")
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
                        "the plan, but post nothing. With --organize: show "
                        "where everything would go, change nothing. With "
                        "--export-quiz: fetch the quiz and show how each item "
                        "converts and where files would go, but write nothing "
                        "and start no report or export job.")
    g.add_argument("--yes", action="store_true",
                   help="With --post-grades: skip the confirmation prompt")
    g.add_argument("--allow-duplicate-comments", action="store_true",
                   help="Post a comment even if the same text is already on the "
                        "submission")
    g2 = p.add_argument_group("creating grade files")
    g2.add_argument("--make-grade-files", action="store_true",
                    help="Write a blank grade file per --section (default: every "
                         "section), with each student's name and Canvas ID filled in")
    g2.add_argument("--assignment-label", metavar="NAME",
                    help="Assignment part of the filename. Default: the first word "
                         "of the Canvas assignment name. Required without --assignment.")
    g2.add_argument("--ay", metavar="YY",
                    help="Academic year for the filename. Default: read from the "
                         "course's term name.")
    g2.add_argument("--term", metavar="N",
                    help="Semester for the filename. Default: read from the "
                         "course's term name.")
    g2.add_argument("--grade-file-dir", default=".", metavar="DIR",
                    help="Where to write the grade files (default: current directory)")
    g2.add_argument("--force", action="store_true",
                    help="Overwrite grade files that already exist")
    g3 = p.add_argument_group("exporting the roster")
    g3.add_argument("--roster-csv", metavar="FILE",
                    help="Write a CSV of students (name, Canvas ID, first/last "
                         "name, instructor, section, section ID), sorted by last "
                         "name, and exit. Honours --section, --student and "
                         "--assignment.")
    g4 = p.add_argument_group("sorting submissions into section folders")
    g4.add_argument("--organize", metavar="DIR",
                    help="Folder of student sub-folders (or an --out folder of "
                         "assignment folders) to sort into one folder per section, "
                         "using --roster. Works offline.")
    g4.add_argument("--roster", metavar="FILE",
                    help="With --organize: a CSV written by --roster-csv")
    g4.add_argument("--organize-to", metavar="DIR",
                    help="With --organize: copy into this folder instead of "
                         "moving in place")
    g5 = p.add_argument_group("exporting quiz questions and answers")
    g5.add_argument("--export-quiz", action="store_true",
                    help="Download one New Quiz's student answers plus its "
                         "content (--assignment is the quiz's assignment ID) into "
                         "its folder under --out. --section/--student choose whose "
                         "answers are kept; --by-section writes one folder per "
                         "section, each with a copy of the quiz content.")
    g5.add_argument("--no-answers", action="store_true",
                    help="With --export-quiz: export the quiz content only, "
                         "without student answers")
    g5.add_argument("--quiz-uploads", action="store_true",
                    help="With --export-quiz (New Quizzes): also download the "
                         "files students uploaded to File Upload questions, "
                         "found as links in the student analysis report, into "
                         "<Quiz>_uploads/<Student>/. Best effort: New Quizzes "
                         "has no API for these files.")
    g6 = p.add_argument_group("New Quiz file uploads through the browser (Playwright)")
    g6.add_argument("--browser-uploads", action="store_true",
                    help="Download a New Quiz's File Upload answers by opening each "
                         "submitted student in SpeedGrader in a browser. Needs "
                         "--assignment; honours --section/--student/--by-section.")
    g6.add_argument("--browser-profile", default="./canvas-browser-profile", metavar="DIR",
                    help="Browser profile folder that keeps you signed in between "
                         "runs (default ./canvas-browser-profile). Keep it private.")
    g6.add_argument("--browser-channel", default="chrome",
                    choices=["chrome", "msedge", "chromium"],
                    help="Installed Chrome (default), Edge, or Playwright's own Chromium")
    g6.add_argument("--connect-browser", metavar="URL",
                    help="Use a Chrome/Edge you started yourself with "
                         "--remote-debugging-port, e.g. http://localhost:9222, "
                         "instead of launching one. Use this if sign-in (e.g. "
                         "CAC) hangs in the browser the script starts.")
    g6.add_argument("--signin-timeout", type=float, default=600, metavar="SECONDS",
                    help="How long to wait for you to sign in (default 600)")
    g6.add_argument("--headless", action="store_true",
                    help="Hide the browser window (only once the profile is signed in)")
    g6.add_argument("--page-timeout", type=float, default=45, metavar="SECONDS",
                    help="How long to wait for each student's quiz to load (default 45)")
    g6.add_argument("--delay", type=float, default=1.0, metavar="SECONDS",
                    help="Pause between students (default 1)")
    g6.add_argument("--limit", type=int, metavar="N",
                    help="Only the first N students (alphabetical) -- for a trial run")
    g5.add_argument("--no-course-export", action="store_true",
                    help="With --export-quiz: skip the Common Cartridge course "
                         "export attempt (the slowest, heaviest part)")
    g5.add_argument("--export-timeout", type=float, default=900, metavar="SECONDS",
                    help="With --export-quiz: how long to wait for each Canvas "
                         "report or export job (default 900). A rerun resumes a "
                         "job that timed out.")
    args = p.parse_args()
    modes = [m for m, on in (("--post-grades", args.post_grades),
                             ("--make-grade-files", args.make_grade_files),
                             ("--roster-csv", args.roster_csv),
                             ("--organize", args.organize),
                             ("--export-quiz", args.export_quiz),
                             ("--browser-uploads", args.browser_uploads)) if on]
    if len(modes) > 1:
        p.error(" and ".join(modes) + " cannot be combined")
    if args.organize:
        if not args.roster:
            p.error("--organize needs --roster FILE (make one with --roster-csv)")
        return organize_submissions(args)
    if args.quiz_uploads and (not args.export_quiz or args.no_answers):
        p.error("--quiz-uploads needs --export-quiz (and the answers report, "
                "so not --no-answers)")
    if (args.roster or args.organize_to) and not args.organize:
        p.error("--roster and --organize-to are only used with --organize")
    if not args.base_url:
        p.error("--base-url is required")
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

    if args.make_grade_files:
        return make_grade_files(canvas, args)

    if args.roster_csv:
        return export_roster_csv(canvas, args)

    if args.export_quiz:
        return export_quiz(canvas, args)

    if args.browser_uploads:
        return browser_quiz_uploads(canvas, args)

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
    new_quizzes_without_files: list[dict] = []

    for idx, assign in enumerate(assignments, start=1):
        adir = out_root / f"{idx:02d}_{slug(assign['name'])}"
        due = DueDates(assign)
        base_str = fmt_ts(due.base, tz) or "no due date"
        is_new_quiz = quiz_kind(assign) == "new"
        print(f"\n[{assign['id']}] {assign['name']}  (due {base_str})"
              + ("  [New Quiz]" if is_new_quiz else ""))
        submitted = with_files = 0

        for sub in canvas.submissions(args.course, assign["id"], args.history):
            if student_ids is not None and sub.get("user_id") not in student_ids:
                continue
            if sub.get("workflow_state") == "unsubmitted":
                continue
            submitted += 1
            attachments = collect_attachments(sub, args.history)
            if not attachments:
                continue
            with_files += 1

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
                    fresh = download(canvas, att["url"], target, att.get("size"))
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

        if is_new_quiz and not with_files:
            # New Quiz submissions are LTI launches (basic_lti_launch): the
            # files from File Upload questions stay inside New Quizzes and
            # never appear as attachments on the Canvas submission.
            new_quizzes_without_files.append(assign)
            print(f"  {submitted} submitted, but New Quizzes keeps File Upload "
                  "answers inside the quiz tool, not on the Canvas submission, "
                  "so there are no attachments to download here.")

    if new_quizzes_without_files:
        print("\nNew Quiz file uploads can't be fetched with the Submissions API. "
              "To try pulling them from the quiz's answers report instead, run:")
        for a in new_quizzes_without_files:
            print(f"  --course {args.course} --assignment {a['id']} "
                  "--export-quiz --quiz-uploads --no-course-export")

    if rows:
        out_root.mkdir(parents=True, exist_ok=True)
        manifest = out_root / "manifest.csv"
        with open(manifest, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n{len(rows)} file(s). Manifest: {manifest}")
    else:
        print("\nNo submission files found."
              + (" (New Quizzes skipped for the reason above.)"
                 if new_quizzes_without_files else ""))

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