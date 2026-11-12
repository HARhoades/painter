"""Canvas REST client: auth, retry, rate-limit pacing, pagination, downloads."""
from __future__ import annotations

from pathlib import Path
import random
import sys
import time

import requests

from painter.canvas.jobs import poll_until
from painter.errors import InvalidInput, error_for_status


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


# --------------------------------------------------------------------------
# Canvas API client
# --------------------------------------------------------------------------
def check_base_url(base_url: str) -> str:
    """The Canvas address, normalised; https only, since every request
    carries the API token (review finding 16)."""
    parsed = requests.utils.urlparse((base_url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise InvalidInput(f"--base-url must be an https:// address, e.g. "
                         f"https://yourschool.instructure.com (got {base_url!r})")
    return base_url.strip().rstrip("/")


class Canvas:
    def __init__(self, base_url: str, token: str, per_page: int = 100):
        self.base = check_base_url(base_url)
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
            err = error_for_status(resp)
            if err is not None:
                raise err
            self._pace(remaining)
            return resp
        err = error_for_status(last)
        if err is not None:
            raise err
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
