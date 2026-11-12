"""New Quiz File Upload answers: from report links, or through a real browser."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import sys
import time

import requests

from painter.canvas.client import Canvas
from painter.domain.assignments import quiz_kind
from painter.domain.matching import name_matches
from painter.domain.naming import safe_filename, slug
from painter.domain.roster import Roster
from painter.services.quiz_plan import (
    QuizExportPlan, find_student_column, quiz_export_plan,
)


# ---- File Upload answers (best effort, from the student analysis report) -----
# New Quizzes has no API for the files students upload to File Upload
# questions, and they are not attachments on the Canvas submission. The
# student analysis report is the only place they may surface, as links in
# the response cells; Instructure does not document that, so this looks for
# file links by value and reports what it found either way.
URL_RE = re.compile(r"https?://[^\s\"'<>\[\](){},;|]+")


CANVAS_FILE_ID_RE = re.compile(r"/files/(\d+)")


# Report cells hold text students typed, so a link is only fetched if it
# points at the Canvas host itself or at a host under one of these domains
# (Instructure's file stores and the S3 buckets they hand out pre-signed
# links to). Matched as whole domain suffixes, https only, default port, no
# user-info: "instructure.evil.example" or "http://10.0.0.5/files/1" are
# not followed (review finding 2).
TRUSTED_HOST_SUFFIXES = (".instructure.com", ".inscloudgate.net", ".amazonaws.com")


def _is_file_link(url: str, canvas_host: str) -> bool:
    try:
        u = requests.utils.urlparse(url)
        port = u.port
    except ValueError:
        return False
    if u.scheme != "https" or u.username or u.password or port not in (None, 443):
        return False
    host = (u.hostname or "").lower()
    if not host:
        return False
    return host == canvas_host or any(host.endswith(s) for s in TRUSTED_HOST_SUFFIXES)


def download_report_uploads(canvas: Canvas, raw: Path, plan: QuizExportPlan,
                            course_id: int, stem: str) -> tuple[int, list[str]]:
    """Download every file linked from the answers report into
    <folder>/<Quiz>_uploads/<Student>_<id>/. Returns (files saved, notes)."""
    with open(raw, newline="", encoding="utf-8-sig") as fh:
        table = list(csv.reader(fh))
    if len(table) < 2:
        return 0, ["file uploads: the student analysis report has no rows"]
    header, body = table[0], table[1:]
    canvas_host = (requests.utils.urlparse(canvas.base).hostname or "").lower()

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
            # _is_file_link has already required https on a trusted host, so
            # the token is only ever sent to the Canvas host over https.
            host = (requests.utils.urlparse(url).hostname or "").lower()
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
