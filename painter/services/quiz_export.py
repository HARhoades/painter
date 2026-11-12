"""Quiz export: content (JSON, QTI, course export) and student answers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import shutil
import time
import zipfile

import requests

from painter.storage.atomic import atomic_write
from painter.canvas.client import Canvas
from painter.domain.selection import Selection
from painter.errors import Cancelled, InvalidInput, NotFound
from painter.events import NULL, ItemDone, Reporter, Stage, watches_canvas
from painter.canvas.jobs import (
    POLL_CAP, POLL_FACTOR, POLL_START, ResumableJob, discard_if_empty, poll_until,
)
from painter.domain.assignments import assignment_folder, quiz_kind, require_one
from painter.domain.duedates import fmt_ts, parse_ts
from painter.domain.naming import slug
from painter.qti.builder import QTI_REPORT_COLUMNS, QtiBuilder, strip_html
from painter.qti.verify import verify_qti_zip
from painter.services.quiz_plan import (
    QuizExportPlan, find_student_column, quiz_export_plan,
)
from painter.services.quiz_uploads import download_report_uploads
from painter.storage.tabular import CsvError, read_table, write_csv


EXPORT_STATE_FILE = ".quiz_export_state.json"


EXPORT_FINAL_STATES = {"exported", "failed"}


EXPORT_MAX_AGE_DAYS = 30        # Canvas deletes export packages after this


ORPHAN_WINDOW_SECONDS = 180     # how far back to look for a job a failed POST started


# ---- student answers (New Quizzes student analysis report) -------------------
ANSWERS_STATE_KEY = "new_quiz_report:student_analysis:csv"


REPORT_REUSE_SECONDS = 30 * 60   # a finished report this recent may be reused


def write_answers(raw: Path, plan: QuizExportPlan, name: str,
                  reporter: Reporter = NULL) -> tuple[list[Path], list[str]]:
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

    table = read_table(raw)
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
        reporter.info(f"  students identified by column '{header[col]}' ({kind})")
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
            reporter.info(f"  {dropped} row(s) for students outside the selection left out")
    written = []
    for d, rows in out.items():
        dest = write_csv(d / name, header, rows)
        reporter.info(f"  {dest}: {len(rows)} row(s)")
        written.append(dest)
    return written, notes


def run_quiz_report(canvas: Canvas, course_id: int, assignment_id: int,
                    state_path: Path, dest: Path, timeout: float,
                    reporter: Reporter = NULL) -> Path:
    """Generate the student analysis report, wait for it, download it to dest.

    The Progress ID is saved to state_path as soon as Canvas returns it; a
    rerun resumes that job instead of starting another. Canvas answers 409
    while a report of this type is already being generated (by this tool or
    in the browser); that is waited out with the same capped, growing
    interval as polling, then requested again. A POST that fails any other
    way is never repeated.
    """
    job = ResumableJob(state_path, ANSWERS_STATE_KEY,
                       {"course_id": course_id, "assignment_id": assignment_id})
    progress = _resumable_report(canvas, job, reporter)
    deadline = time.monotonic() + timeout
    if progress is None:
        progress = _start_report(canvas, course_id, assignment_id, deadline, timeout,
                                 reporter)
        job.save(progress_id=progress["id"])
        reporter.info(f"  started report job {progress['id']}")
    return _finish_report(canvas, job, progress, deadline, timeout, dest, reporter)


def _resumable_report(canvas: Canvas, job: ResumableJob, reporter: Reporter) -> dict | None:
    """The saved report job, if Canvas still has it and it is worth resuming:
    not failed, and if finished, recent enough to reuse."""
    saved = job.saved()
    if not saved:
        return None
    try:
        progress = canvas.progress(saved["progress_id"])
    except NotFound:          # job expired; a bad token is not this
        return None
    if progress:
        st = progress.get("workflow_state")
        age = time.time() - (parse_ts(progress.get("updated_at")) or
                             datetime.fromtimestamp(0).astimezone()).timestamp()
        if st == "failed" or (st == "completed" and age > REPORT_REUSE_SECONDS):
            return None
        reporter.info(f"  resuming report job {progress['id']} "
              f"({progress.get('workflow_state')})")
    return progress or None


def _start_report(canvas: Canvas, course_id: int, assignment_id: int, deadline: float,
                  timeout: float, reporter: Reporter) -> dict:
    """POST the report request once; while Canvas answers 409 (another
    report is being generated) wait with a growing interval and ask again."""
    wait, told = POLL_START, False
    while True:
        try:
            progress = canvas.create_quiz_report(course_id, assignment_id)
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
                reporter.info("  a student analysis report is already being generated; "
                      "waiting for it to finish")
                told = True
            canvas.wait(min(wait, remaining),
                        "another student analysis report is being generated")
            wait = min(POLL_CAP, wait * POLL_FACTOR)
            continue
        # A POST that succeeded is never repeated: it may have started a job
        # even if the reply carries no id (review finding 1).
        if not isinstance(progress, dict) or not progress.get("id"):
            raise RuntimeError("Canvas accepted the student analysis report "
                               "request but returned no job id "
                               f"({progress!r}); not retrying")
        return progress


def _finish_report(canvas: Canvas, job: ResumableJob, progress: dict, deadline: float,
                   timeout: float, dest: Path, reporter: Reporter) -> Path:
    """Wait for the report job, then download its CSV to dest. The saved job
    is cleared only once the file is down, so a failed download resumes."""
    last = [progress.get("completion")]

    def report(p):
        if p.get("completion") != last[0] and p.get("completion") is not None:
            last[0] = p.get("completion")
            reporter.info(f"  report {p['id']}: {p.get('workflow_state')} {last[0]}%")

    progress, done = poll_until(
        lambda: canvas.progress(progress["id"]),
        lambda p: p.get("workflow_state") in ("completed", "failed"),
        max(0.0, deadline - time.monotonic()), on_poll=report,
        sleep=lambda s: canvas.wait(s, "waiting for the student analysis report", last[0]))
    if not done:
        raise TimeoutError(f"report job {progress['id']} is still "
                           f"{progress.get('workflow_state')} after {timeout:.0f}s. "
                           "Rerun the same command to pick it up; no new job "
                           "will be started.")
    if progress.get("workflow_state") == "failed":
        job.clear()
        raise RuntimeError(f"Canvas reports the student analysis report failed"
                           + (f": {progress['message']}" if progress.get("message") else ""))
    results = progress.get("results")
    url = results.get("url") if isinstance(results, dict) else None
    if not url:
        raise RuntimeError("the report finished but Canvas gave no download link")
    dest.unlink(missing_ok=True)
    got = canvas.fetch_file(url, dest, auth=True)
    if got.note:
        reporter.warning(got.note)
    job.clear()                     # kept until now so a failed download can resume
    return dest


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
                       dest: Path, timeout: float, reporter: Reporter = NULL) -> Path:
    """Start (or resume) a content export, wait for it, download it to dest.

    Duplicate protection: the job ID is saved to state_path the moment Canvas
    returns it. A rerun after an interruption or timeout resumes that job
    instead of starting another; the entry is cleared once the file is
    downloaded. A POST that errors is never retried -- Canvas may have
    started the job anyway -- so the recent export list is checked for it.
    """
    from datetime import timezone
    job = ResumableJob(state_path, f"{export_type}:" + json.dumps(select, sort_keys=True),
                       {"course_id": course_id})
    export = None
    saved = job.saved()
    if saved:
        try:
            export = canvas.content_export(course_id, saved["export_id"])
        except NotFound:
            export = None
        if export and (export.get("workflow_state") == "failed" or _export_expired(export)):
            export = None
        if export:
            reporter.info(f"  resuming export {export['id']} started "
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
            reporter.info(f"  the request errored, but Canvas started export {export['id']}; "
                  "using it")
        else:
            reporter.info(f"  started export {export['id']}")
        job.save(export_id=export["id"], created_at=export.get("created_at"))

    last_state = [export.get("workflow_state")]

    def report(e):
        if e.get("workflow_state") != last_state[0]:
            last_state[0] = e.get("workflow_state")
            reporter.info(f"  export {e['id']}: {last_state[0]}")

    export, done = poll_until(
        lambda: canvas.content_export(course_id, export["id"]),
        lambda e: e.get("workflow_state") in EXPORT_FINAL_STATES,
        timeout, on_poll=report,
        sleep=lambda s: canvas.wait(s, f"waiting for the {export_type} export"))
    if not done:
        raise TimeoutError(
            f"export {export['id']} is still {export.get('workflow_state')} after "
            f"{timeout:.0f}s. Rerun the same command to pick it up; no new job "
            "will be started.")
    if export.get("workflow_state") == "failed":
        job.clear()
        raise RuntimeError(f"Canvas reports export {export['id']} failed")
    attachment = export.get("attachment") or {}
    if not attachment.get("url"):
        job.clear()
        raise RuntimeError(f"export {export['id']} finished but has no download link")

    dest.unlink(missing_ok=True)            # never treat an old file as cached
    got = canvas.fetch_file(attachment["url"], dest, attachment.get("size"), auth=True)
    if got.note:
        reporter.warning(got.note)
    if not zipfile.is_zipfile(dest):
        raise IOError(f"export {export['id']} download is not a zip package")
    job.clear()
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


# QuizExportResult.outcome (the CLI's exit codes)
EXPORTED, NOTHING_SELECTED, COURSE_EXPORT_INCOMPLETE, ANSWERS_MISSING = 0, 1, 2, 3


@dataclass
class QuizExportRequest:
    course_id: int
    assignment_ids: tuple[int, ...]        # exactly one: the quiz's assignment
    out_root: Path
    selection: Selection = field(default_factory=Selection)
    by_section: bool = False               # a folder per section
    answers: bool = True                   # the student analysis report
    uploads: bool = False                  # files linked from that report
    course_export: bool = True             # Common Cartridge package
    timeout: float = 900                   # per Canvas job
    dry_run: bool = False                  # read the quiz, write and start nothing


@dataclass
class QuizExportResult:
    outcome: int                           # EXPORTED ... ANSWERS_MISSING
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _ExportRun:
    """One quiz export in progress: what the stages share."""
    canvas: Canvas
    req: QuizExportRequest
    reporter: Reporter
    assignment: dict
    kind: str                              # "new" or "classic"
    plan: QuizExportPlan
    adir: Path                             # the assignment's folder (job state lives here)
    stem: str                              # file-name prefix from the quiz name
    shared: list[Path] = field(default_factory=list)    # written once, copied to every folder
    per_dir: list[Path] = field(default_factory=list)   # already written into each folder
    warnings: list[str] = field(default_factory=list)
    answers_missing: bool = False
    course_incomplete: bool = False

    @property
    def cid(self) -> int:
        return self.req.course_id

    @property
    def aid(self) -> int:
        return self.req.assignment_ids[0]

    @property
    def primary(self) -> Path:
        return self.plan.dirs[0]

    @property
    def state_path(self) -> Path:
        return self.adir / EXPORT_STATE_FILE


@watches_canvas()
def export_quiz(canvas: Canvas, req: QuizExportRequest,
                reporter: Reporter = NULL) -> QuizExportResult:
    """Download one quiz's student answers and its content.

    Stages, in order: plan (which quiz, which students, which folders),
    content (Classic QTI export, or New Quiz JSON + QTI + report), student
    answers (+ uploads linked from them), course export, and the summary.
    """
    run = _plan_export(canvas, req, reporter)
    if isinstance(run, QuizExportResult):
        return run
    reporter.event(Stage("Quiz content"))
    if run.kind == "classic":
        if _classic_content(run):
            return QuizExportResult(EXPORTED)                 # dry run
    else:
        content = _new_quiz_content(run)
        if content is None:
            return QuizExportResult(EXPORTED)                 # dry run
        quiz, items = content
        if req.answers:
            _answers_stage(run)
        if req.course_export:
            _course_export_stage(run, quiz, items)
    return _finish_export(run)


def _plan_export(canvas: Canvas, req: QuizExportRequest,
                 reporter: Reporter) -> _ExportRun | QuizExportResult:
    assignment = require_one(canvas, req.course_id, req.assignment_ids,
                             "quiz export needs exactly one --assignment "
                             "(the quiz's assignment ID; see `painter list assignments`).")
    aid = req.assignment_ids[0]
    kind = quiz_kind(assignment)
    if kind is None:
        raise InvalidInput(f"Assignment {aid} ({assignment.get('name')}) is not a quiz.")
    reporter.info(f"[{aid}] {assignment.get('name')}  "
          f"({'New Quiz' if kind == 'new' else 'Classic Quiz'})")

    plan = quiz_export_plan(canvas, req.course_id, req.out_root, assignment,
                            req.selection, req.by_section, reporter)
    if plan is None:
        reporter.warning("None of the selected students are assigned this quiz; nothing "
              "exported.")
        return QuizExportResult(NOTHING_SELECTED)
    adir, note = assignment_folder(Path(req.out_root), assignment)
    if note:
        reporter.warning(note)
    return _ExportRun(canvas, req, reporter, assignment, kind, plan, adir,
                      slug(assignment.get("name") or str(aid), 50))


def _classic_content(run: _ExportRun) -> bool:
    """Classic Quiz: Canvas's own QTI export. Returns True for a dry run."""
    quiz_id = run.assignment.get("quiz_id")
    if not quiz_id:
        raise InvalidInput("Classic quiz with no quiz_id on its assignment.")
    if run.req.dry_run:
        run.reporter.info(f"Dry run: would export Classic quiz {quiz_id} as QTI to "
                          f"{run.primary}")
        return True
    dest = run.primary / f"{run.stem}_qti.zip"
    run_content_export(run.canvas, run.cid, "qti", {"quizzes": [quiz_id]}, run.state_path,
                       run.adir / f".{run.stem}_qti.download", run.req.timeout,
                       run.reporter).replace(dest)
    run.shared.append(dest)
    if run.req.answers:
        run.warnings.append("student answers are only implemented for New Quizzes; "
                            "this Classic Quiz was exported without them")
        run.answers_missing = True
    return False


def _new_quiz_content(run: _ExportRun) -> tuple[dict, list[dict]] | None:
    """New Quiz: the items as JSON, a QTI package and a conversion report.
    Returns (quiz, items), or None for a dry run."""
    canvas, cid, aid, reporter = run.canvas, run.cid, run.aid, run.reporter
    quiz = canvas.new_quiz(cid, aid)
    items = canvas.new_quiz_items(cid, aid)
    ident = "g" + __import__("hashlib").md5(f"{cid}:{aid}".encode()).hexdigest()
    builder = QtiBuilder(quiz, ident)
    for it in QtiBuilder.ordered(items):
        builder.add(it)
    in_qti = sum(1 for r in builder.report if r["In QTI"] == "yes")
    reporter.info(f"  {len(items)} item(s); {in_qti} converted to QTI")
    for r in builder.report:
        mark = " " if r["In QTI"] == "yes" else "!"
        label = r["Question Type"] or r["Entry Type"]
        note = f"  -- {r['Notes']}" if r["Notes"] else ""
        reporter.info(f"   {mark} {str(r['Position']):>3}  {label:<16} "
              f"{(r['Title'] or '')[:40]}{note}")
    if run.req.dry_run:
        what = ["request the student analysis report"] if run.req.answers else []
        if run.req.course_export:
            what.append("start a course export")
        reporter.info("Dry run: nothing written" + (", did not " + " or ".join(what)
                                           if what else "") + ".")
        reporter.info("Output folder(s): " + ", ".join(str(d) for d in run.plan.dirs))
        return None
    if not items:
        run.warnings.append("the quiz has no items")

    json_path = run.primary / f"{run.stem}_new-quiz.json"
    with atomic_write(json_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "canvas_host": canvas.base, "course_id": cid, "assignment_id": aid,
            "assignment_name": run.assignment.get("name"),
            "quiz": quiz, "items": items}, indent=2, ensure_ascii=False))
    json.loads(json_path.read_text(encoding="utf-8"))    # round-trip check
    run.shared.append(json_path)

    qti_path = run.primary / f"{run.stem}_qti.zip"
    builder.write_zip(qti_path)
    verify_qti_zip(qti_path, in_qti)
    run.shared.append(qti_path)

    report_path = write_csv(run.primary / f"{run.stem}_qti-report.csv",
                            QTI_REPORT_COLUMNS, builder.report)
    run.shared.append(report_path)
    if in_qti < len(items):
        run.warnings.append(f"{len(items) - in_qti} item(s) are in the JSON but not "
                            f"the QTI; see {report_path.name}")
    return quiz, items


def _answers_stage(run: _ExportRun) -> None:
    """The student analysis report, split per folder; uploads linked from it."""
    reporter = run.reporter
    if reporter.cancelled():
        raise Cancelled("stopped before the student analysis report")
    reporter.info("Student answers (student analysis report):")
    reporter.event(Stage("Student answers"))
    raw = run.adir / f".{run.stem}_student-answers.download"
    try:
        run_quiz_report(run.canvas, run.cid, run.aid, run.state_path, raw,
                        run.req.timeout, reporter)
        files, notes = write_answers(raw, run.plan, f"{run.stem}_student-answers.csv",
                                     reporter)
        run.per_dir += files
        run.warnings += notes
        if run.req.uploads:
            _report_uploads_stage(run, raw)
    except (RuntimeError, TimeoutError, OSError, ValueError, CsvError,
            requests.RequestException) as exc:
        run.warnings.append(f"student answers: {exc}")
        run.answers_missing = True
    finally:
        raw.unlink(missing_ok=True)    # the unfiltered report never stays


def _report_uploads_stage(run: _ExportRun, raw: Path) -> None:
    run.reporter.info("File Upload answers (links in the report):")
    try:
        n, notes = download_report_uploads(run.canvas, raw, run.plan, run.cid, run.stem,
                                           run.reporter)
        run.warnings += notes
        if n:
            run.reporter.info(f"  {n} uploaded file(s) saved under {run.stem}_uploads/")
    except (OSError, ValueError, CsvError, requests.RequestException) as exc:
        run.warnings.append(f"file uploads: {exc}")


def _course_export_stage(run: _ExportRun, quiz: dict, items: list[dict]) -> None:
    """A Common Cartridge export of the quiz's assignment, kept only if it
    really holds this quiz."""
    reporter = run.reporter
    if reporter.cancelled():
        raise Cancelled("stopped before the course export")
    reporter.info("Course export (Common Cartridge) of this quiz's assignment:")
    reporter.event(Stage("Course export"))
    tmp_cc = run.adir / f".{run.stem}_course-export.download"
    try:
        run_content_export(run.canvas, run.cid, "common_cartridge",
                           {"assignments": [run.aid]}, run.state_path, tmp_cc,
                           run.req.timeout, reporter)
        ok, why = package_contains_quiz(tmp_cc, quiz, items)
        if ok:
            cc_path = run.primary / f"{run.stem}_course-export.imscc"
            tmp_cc.replace(cc_path)
            run.shared.append(cc_path)
            reporter.info(f"  kept: {why}")
        else:
            run.warnings.append(f"course export not kept: {why}")
    except (RuntimeError, TimeoutError, OSError, requests.RequestException) as exc:
        run.warnings.append(f"course export: {exc}")
        run.course_incomplete = True
    finally:
        tmp_cc.unlink(missing_ok=True)


def _finish_export(run: _ExportRun) -> QuizExportResult:
    """Copy shared files into every folder, list what was written, sum up."""
    reporter, plan = run.reporter, run.plan
    discard_if_empty(run.state_path)
    for extra in plan.dirs[1:]:
        extra.mkdir(parents=True, exist_ok=True)
        for f in run.shared:
            shutil.copy2(f, extra / f.name)

    reporter.info("\nExported:")
    names = [f.name for f in run.shared] + sorted({f.name for f in run.per_dir})
    exported: list[Path] = []
    for d in plan.dirs:
        for n in names:
            p = d / n
            if p.exists():
                exported.append(p)
                reporter.info(f"  {p}  ({p.stat().st_size:,} bytes)")
                reporter.event(ItemDone("file", p.name, "exported", str(d), p))
    for w_ in run.warnings:
        reporter.warning(f"  ! {w_}")
    reporter.info(f"API use: {run.canvas.rate_summary()}")
    outcome = (ANSWERS_MISSING if run.answers_missing else
               COURSE_EXPORT_INCOMPLETE if run.course_incomplete else EXPORTED)
    return QuizExportResult(outcome, exported, run.warnings)
