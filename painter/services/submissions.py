"""Download run: listings, submission files, manifest and run log."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import sys

from painter.canvas.client import Canvas
from painter.domain.assignments import assignment_folder, quiz_kind
from painter.domain.duedates import DueDates, fmt_lateness, fmt_ts
from painter.domain.naming import flat_filename, safe_filename, slug, student_dir_name
from painter.domain.roster import Roster, assigned_students, select_students
from painter.storage.files import ARCHIVE_SUFFIXES, download, extract
from painter.storage.runlog_xlsx import log_filename, write_run_log


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
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            for old in reader:
                merged[old.get("path") or f"#{len(merged)}"] = old
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
        merged[str(row["path"])] = row
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(merged.values())
    tmp.replace(path)
    return len(merged)


def run_download(canvas: Canvas, args, run_started: datetime) -> int:
    """The default mode: --list-*, or download submission files for the course."""
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
    failures = 0
    new_quizzes_without_files: list[dict] = []

    for assign in assignments:
        adir = assignment_folder(out_root, assign)
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
                extracted_to = ""
                # Every attachment gets a row, including failures, so the
                # manifest and Excel log never make a partial run look
                # complete (review finding 4).
                try:
                    fresh = download(canvas, att["url"], target, att.get("size"))
                except Exception as exc:
                    failures += 1
                    status_text = f"failed: {exc}"
                    print(f"    ! failed {fname}: {exc}")
                else:
                    status_text = "downloaded" if fresh else "cached"
                    print(f"    {status_text} {fname}")
                    if not args.no_extract and target.suffix.lower() in ARCHIVE_SUFFIXES:
                        unpack_dir = sdir / target.stem
                        if extract(target, unpack_dir):
                            extracted_to = str(unpack_dir)
                            print(f"      extracted -> {unpack_dir.name}/")
                        else:
                            status_text += "; extract failed"

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
                    "status": status_text,
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
        total = write_manifest(manifest, rows)
        print(f"\n{len(rows)} file(s). Manifest: {manifest}"
              + (f" ({total} row(s) including earlier runs)" if total != len(rows) else ""))
        if failures:
            print(f"{failures} file(s) could not be downloaded; they are listed "
                  "in the manifest with status 'failed'.", file=sys.stderr)
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
    # 1 = finished, but some files are missing (same meaning as --post-grades).
    return 1 if failures else 0
