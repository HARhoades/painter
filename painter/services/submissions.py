"""Download run: listings, submission files, manifest and run log."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from painter.canvas.client import Canvas
from painter.domain.assignments import assignment_folder, quiz_kind
from painter.domain.duedates import DueDates, fmt_lateness, fmt_ts, parse_tz
from painter.domain.naming import attachment_filenames, flat_filename, slug, student_dir_name
from painter.domain.roster import Roster
from painter.domain.selection import Selection
from painter.errors import Cancelled
from painter.events import NULL, ItemDone, Note, Reporter, Stage, emit, watches_canvas
from painter.storage.files import ARCHIVE_SUFFIXES, download, extract
from painter.storage.runlog_xlsx import RunInfo, log_filename, write_run_log
from painter.storage.tabular import read_records, write_csv


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


def write_manifest(path: Path, rows: list[dict]) -> int:
    """Merge this run's rows into manifest.csv, keyed by saved path.

    A run of one assignment or one section no longer erases the rows from
    earlier runs; a file fetched again replaces its old row. Written with a
    BOM like every other CSV here (review finding 13). Returns the row count.
    """
    merged: dict[str, dict] = {}
    columns: list[str] = []
    if path.exists():
        columns, old_rows = read_records(path)
        for old in old_rows:
            merged[old.get("path") or f"#{len(merged)}"] = old
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
        merged[str(row["path"])] = row
    write_csv(path, columns, merged.values())
    return len(merged)


# --------------------------------------------------------------------------
# Listings (--list-sections, --list-students, --list-assignments)
# --------------------------------------------------------------------------
def section_listing(roster: Roster) -> list[dict]:
    """Sections sorted by name, each with its student count."""
    return [{"id": s["id"], "sis_section_id": s.get("sis_section_id"),
             "name": s.get("name", ""),
             "students": len(roster.users_of_section.get(s["id"], set()))}
            for s in sorted(roster.sections, key=lambda x: x.get("name") or "")]


@dataclass
class StudentListing:
    users: list[dict]                     # sorted by sortable name
    in_course: int                        # students in the whole course
    filtered: bool                        # a filter narrowed the list
    notes: list[Note] = field(default_factory=list)


def student_listing(canvas: Canvas, course_id: int, roster: Roster,
                    selection: Selection = Selection(),
                    assignment_ids: tuple[int, ...] = ()) -> StudentListing:
    """Same selection rules as a download run: (--section OR --student), then
    narrowed to students who have one of assignment_ids, if given."""
    chosen = selection.resolve_assigned(canvas, roster, course_id, assignment_ids)
    users = [u for u in roster.users.values()
             if chosen.student_ids is None or u["id"] in chosen.student_ids]
    users.sort(key=lambda x: x.get("sortable_name") or "")
    return StudentListing(users, len(roster.users),
                          chosen.student_ids is not None or bool(assignment_ids),
                          chosen.notes)


# --------------------------------------------------------------------------
# Downloading submission files
# --------------------------------------------------------------------------
@dataclass
class DownloadRequest:
    course_id: int
    out_root: Path
    assignment_ids: tuple[int, ...] = ()   # empty: every assignment
    selection: Selection = field(default_factory=Selection)
    by_section: bool = False               # a folder per section
    flat: bool = False                     # no per-student folders
    extract: bool = True                   # unpack zip/tar attachments
    history: bool = False                  # earlier attempts too
    tz: str | None = None                  # IANA zone for displayed times
    excel_log: bool = True
    log_dir: Path | None = None            # default: out_root
    run_started: datetime = field(default_factory=datetime.now)


@dataclass
class DownloadResult:
    rows: list[dict]                       # one per attachment, as in manifest.csv
    failures: int                          # attachments that could not be fetched
    new_quizzes_without_files: list[dict]  # New Quizzes: uploads not reachable here
    manifest: Path | None = None
    log_path: Path | None = None


@dataclass
class _DownloadRun:
    """One download run in progress: what the per-assignment, per-submission
    and per-attachment steps share."""
    canvas: Canvas
    req: DownloadRequest
    reporter: Reporter
    tz: object
    roster: Roster | None
    student_ids: set[int] | None           # None: no filter
    section_ids: set[int]
    rows: list[dict] = field(default_factory=list)
    failures: int = 0
    stopped: bool = False                  # cancelled; finish and raise
    stage_done: int = 0                    # files done / to do in this assignment
    stage_total: int = 0
    new_quizzes_without_files: list[dict] = field(default_factory=list)


@watches_canvas()
def download_submissions(canvas: Canvas, req: DownloadRequest,
                         reporter: Reporter = NULL) -> DownloadResult:
    """Download submission files, then write manifest.csv and the Excel log.

    A file that fails is recorded with status "failed: ..." and counted in
    result.failures; the run carries on. Cancellation is checked before
    each file and leaves the tree as a rerun expects (no partial files).
    """
    run, assignments = _start_download(canvas, req, reporter)
    for n, assign in enumerate(assignments, start=1):
        _download_assignment(run, assign, n, len(assignments))
        if run.stopped:
            break
    return _finish_download(run)


def _start_download(canvas: Canvas, req: DownloadRequest,
                    reporter: Reporter) -> tuple[_DownloadRun, list[dict]]:
    """Roster and filters (only if needed), and the assignments to fetch."""
    tz = parse_tz(req.tz)
    # The roster is needed for any filtering and for --by-section. Built
    # once, two API calls.
    roster = (Roster.load(canvas, req.course_id)
              if req.selection.active or req.by_section else None)
    assignments = canvas.assignments(req.course_id)

    # None means "no filter" -- the all-students pass stays the default.
    student_ids, section_ids = None, set()
    if roster:
        chosen = req.selection.resolve(roster)
        emit(chosen.notes, reporter)
        student_ids, section_ids = chosen.student_ids, chosen.section_ids
    if student_ids is not None:
        reporter.info(f"Filtering to {len(student_ids)} student(s).")

    if req.assignment_ids:
        wanted = set(req.assignment_ids)
        assignments = [a for a in assignments if a["id"] in wanted]
    return _DownloadRun(canvas, req, reporter, tz, roster, student_ids, section_ids), assignments


def _download_assignment(run: _DownloadRun, assign: dict, step: int, steps: int) -> None:
    req, reporter = run.req, run.reporter
    adir, note = assignment_folder(Path(req.out_root), assign)
    if note:
        reporter.warning(note)
    due = DueDates(assign)
    base_str = fmt_ts(due.base, run.tz) or "no due date"
    is_new_quiz = quiz_kind(assign) == "new"
    reporter.info(f"\n[{assign['id']}] {assign['name']}  (due {base_str})"
                  + ("  [New Quiz]" if is_new_quiz else ""))
    submitted = 0
    todo = []                 # (submission, attachments): counted before any download
    for sub in run.canvas.submissions(req.course_id, assign["id"], req.history):
        if run.student_ids is not None and sub.get("user_id") not in run.student_ids:
            continue
        if sub.get("workflow_state") == "unsubmitted":
            continue
        submitted += 1
        attachments = collect_attachments(sub, req.history)
        if attachments:
            todo.append((sub, attachments))
    with_files = len(todo)
    run.stage_done, run.stage_total = 0, sum(len(a) for _, a in todo)
    reporter.event(Stage(f"Downloading {assign['name']}", total=run.stage_total,
                         step=step, steps=steps))
    reporter.progress(0, run.stage_total, assign["name"])

    for sub, attachments in todo:
        _download_submission(run, assign, adir, due, sub, attachments)
        if run.stopped:
            return

    if is_new_quiz and not with_files:
        # New Quiz submissions are LTI launches (basic_lti_launch): the
        # files from File Upload questions stay inside New Quizzes and
        # never appear as attachments on the Canvas submission.
        run.new_quizzes_without_files.append(assign)
        reporter.info(f"  {submitted} submitted, but New Quizzes keeps File Upload "
                      "answers inside the quiz tool, not on the Canvas submission, "
                      "so there are no attachments to download here.")


def _download_submission(run: _DownloadRun, assign: dict, adir: Path, due: DueDates,
                         sub: dict, attachments: list[dict]) -> None:
    """One student's submission: where it goes, how late it is, its files."""
    req, roster, tz = run.req, run.roster, run.tz
    uid = sub["user_id"]
    section = roster.primary_section(uid, run.section_ids) if roster else None
    section_label = (section or {}).get("name", "")
    user_sections = roster.sections_of_user.get(uid, []) if roster else []
    due_at, due_source = due.effective(uid, user_sections)
    lateness = fmt_lateness(sub.get("seconds_late"))
    policy = sub.get("late_policy_status") or ""

    sdir = adir
    if req.by_section:
        sdir = sdir / slug(section_label or "no-section", 40)
    if not req.flat:
        sdir = sdir / student_dir_name(sub)
    flag = f"  [LATE +{lateness}]" if lateness else ""
    if policy == "excused":
        flag = "  [EXCUSED]"
    where = (sdir.relative_to(adir) / student_dir_name(sub)
             if req.flat else sdir.relative_to(adir))
    run.reporter.info(f"  {where}"
                      f"  submitted {fmt_ts(sub.get('submitted_at'), tz) or '-'}{flag}")

    common = {
        "assignment": assign["name"],
        "assignment_id": assign["id"],
        "student": (sub.get("user") or {}).get("sortable_name", ""),
        "user_id": sub.get("user_id"),
        "section": section_label,
        "all_sections": "; ".join(roster.section_names(uid)) if roster else "",
        "due_at": fmt_ts(due_at, tz),
        "due_source": due_source,
        "submitted_at": fmt_ts(sub.get("submitted_at"), tz),
        "attempt": sub.get("attempt") or "",
        "late": sub.get("late", False),
        "late_by": lateness,
        "late_policy_status": policy,
        "missing": sub.get("missing", False),
        "graded_at": fmt_ts(sub.get("graded_at"), tz),
        "score": sub.get("score") if sub.get("score") is not None else "",
        "workflow_state": sub.get("workflow_state", ""),
    }
    for att, fname in zip(attachments, attachment_filenames(attachments)):
        if run.reporter.cancelled():
            run.stopped = True    # finish below: manifest and log still written
            return
        if req.flat:
            fname = flat_filename(sub, fname)
        try:
            status_text, target, extracted_to = _download_attachment(run, att, sdir, fname)
        except Cancelled:          # during a retry pause: this file is not saved
            run.stopped = True
            return
        run.rows.append({**common, "filename": fname, "status": status_text,
                         "path": str(target), "extracted_to": extracted_to})
        run.stage_done += 1
        run.reporter.progress(run.stage_done, run.stage_total, fname)
        run.reporter.event(ItemDone("file", fname, status_text,
                                    common["student"], target))


def _download_attachment(run: _DownloadRun, att: dict, sdir: Path,
                         fname: str) -> tuple[str, Path, str]:
    """Fetch one file (and unpack it if it is an archive).
    Returns (status, saved path, extracted-to folder or "")."""
    reporter = run.reporter
    target = sdir / fname
    extracted_to = ""
    # Every attachment gets a row, including failures, so the manifest and
    # Excel log never make a partial run look complete (review finding 4).
    try:
        fresh = download(run.canvas, att["url"], target, att.get("size"))
        if fresh.note:
            reporter.warning(fresh.note)
    except Cancelled:
        raise
    except Exception as exc:
        run.failures += 1
        reporter.info(f"    ! failed {fname}: {exc}")
        return f"failed: {exc}", target, ""
    status_text = "downloaded" if fresh else "cached"
    reporter.info(f"    {status_text} {fname}")
    if run.req.extract and target.suffix.lower() in ARCHIVE_SUFFIXES:
        unpack_dir = sdir / target.stem
        if not fresh and unpack_dir.is_dir():
            extracted_to = str(unpack_dir)   # done on an earlier run
        else:
            unpacked = extract(target, unpack_dir)
            for note in unpacked.notes:
                reporter.info(note)
            if unpacked:
                extracted_to = str(unpack_dir)
                reporter.info(f"      extracted -> {unpack_dir.name}/")
            else:
                status_text += "; extract failed"
    return status_text, target, extracted_to


def _finish_download(run: _DownloadRun) -> DownloadResult:
    """The New Quiz hint, manifest.csv and the Excel log; then raise
    Cancelled (with the result) if the run was stopped."""
    req, reporter, rows = run.req, run.reporter, run.rows
    out_root = Path(req.out_root)
    result = DownloadResult(rows, run.failures, run.new_quizzes_without_files)
    if run.new_quizzes_without_files:
        reporter.info("\nNew Quiz file uploads can't be fetched with the Submissions API. "
                      "To try pulling them from the quiz's answers report instead, run:")
        for a in run.new_quizzes_without_files:
            reporter.info(f"  --course {req.course_id} --assignment {a['id']} "
                          "--export-quiz --quiz-uploads --no-course-export")

    if rows:
        out_root.mkdir(parents=True, exist_ok=True)
        result.manifest = out_root / "manifest.csv"
        total = write_manifest(result.manifest, rows)
        reporter.info(f"\n{len(rows)} file(s). Manifest: {result.manifest}"
                      + (f" ({total} row(s) including earlier runs)"
                         if total != len(rows) else ""))
        if run.failures:
            reporter.warning(f"{run.failures} file(s) could not be downloaded; they are "
                             "listed in the manifest with status 'failed'.")
    else:
        reporter.info("\nNo submission files found."
                      + (" (New Quizzes skipped for the reason above.)"
                         if run.new_quizzes_without_files else ""))

    # The Excel log is written even on an empty run, so there is a record
    # that the run happened and matched nothing.
    if req.excel_log:
        log_dir = Path(req.log_dir) if req.log_dir else out_root
        log_path = log_dir / log_filename(req.run_started)
        try:
            write_run_log(rows, log_path, RunInfo(
                req.run_started, req.course_id, run.canvas.base, out_root,
                tuple(req.assignment_ids), req.selection.sections,
                req.selection.students, req.tz))
            result.log_path = log_path
            reporter.info(f"Excel log: {log_path}")
        except ImportError:
            reporter.warning("Excel log skipped: openpyxl is not installed "
                             "(pip install openpyxl, or pass --no-xlsx).")
        except Exception as exc:
            reporter.warning(f"Excel log failed: {exc}")
    if run.stopped:
        raise Cancelled(f"stopped after {len(rows)} file(s); manifest written, "
                        "rerun to resume", result)
    return result
