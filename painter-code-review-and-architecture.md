# Painter: code review and proposed architecture

Reviewed: `canvas_fetch_submissions.py` (4,435 lines, one file, last modified 9 Nov 2026).
Method: full read of the source. Nothing was run against Canvas, so the bugs below are found by reading, not reproduced.

## 1. Summary

The code is careful where it matters most: the HTTP layer, the grade-posting flow and the job-resume logic are well thought out. The problems are structural. One file holds nine tools, almost every function prints, exits and reads `argparse` flags directly, and the core download workflow lives inline in `main()`. None of that can be called from a GUI as it stands.

The refactor is therefore mostly about separating "what the tool does" from "how the command line talks to it". Once that is done, a GUI is a second front end on the same functions.

## 2. What is good and should survive the refactor

- **HTTP client** (`Canvas._request`, lines 427-479): throttling retried, writes never retried after a 5xx, pacing before the bucket empties, `Retry-After` honoured.
- **Atomic downloads**: `.part` then rename, so an interrupted run leaves no truncated file.
- **Grade posting is already plan → confirm → execute → verify** (`plan_grade_file`, `post_grade_plan`, `verify_posted`). This is the shape every destructive action should have, and the shape a GUI needs.
- **Job resume**: report and export job IDs are saved before polling, so a rerun never starts a duplicate job.
- **Archive extraction** refuses members that escape the destination folder.
- **Token handling**: read from the environment, sent only to the Canvas host, dropped for pre-signed URLs.
- Comments explain *why* (Canvas quirks), which is the part worth keeping.

## 3. Findings

### 3.1 Bugs and risks (fix in their own commits, after tests exist)

| # | Severity | Where | Problem |
|---|---|---|---|
| 1 | High | 2671-2675 | `run_quiz_report`: if Canvas answers 2xx without an `id`, the `while True` loop re-POSTs immediately with no sleep and no deadline check. It can create report jobs in a tight loop. |
| 2 | High | 2893-2896, 2899+ | `--quiz-uploads` fetches any URL found in any report cell, including essay text students typed. `_is_file_link` accepts a host that merely *contains* "instructure" or "amazonaws.com", or any host at all if the path has `/files/<n>`. A student can make the instructor's machine request an arbitrary address, including internal ones. The bearer token is not sent off-host, so this is unwanted fetching, not token theft. Fix: allow-list exact hosts and suffixes, https only. |
| 3 | High | 4304-4305 | Assignment folder is `NN_<name>` where NN is the position in the *filtered* list. The same assignment is `03_DATE-Scenario` in a full run and `01_DATE-Scenario` with `--assignment`. Two different assignments with the same name, fetched one at a time, share one folder. `assignment_folder()` (2464) exists to paper over this. Fix: stable name from Canvas position or assignment ID. |
| 4 | Medium | 4352-4356 | A failed download is printed and skipped. It is not in the manifest or Excel log and the run still exits 0. A partial download looks like a complete one. |
| 5 | Medium | 1141-1154 vs 1645-1656 | Two different rules for "which section is this student in". Download `--by-section` uses the first enrollment, which can be a course-wide default section. `--organize` deliberately skips that catch-all. The two modes can file the same student differently. |
| 6 | Medium | 1426-1434 vs 1507-1521 | Two instructor lookups. Roster CSV prefers teachers over TAs. Grade files mix them and take whichever came first, so a TA's name can land in `instructor=`. |
| 7 | Medium | 511, 4349 | Files are keyed by display name only. Two attachments with the same name in one student folder (likely with `--history`) overwrite each other, and each rerun re-downloads the other one. Same name and same size is treated as cached. |
| 8 | Medium | 4166 | Browser profile defaults to `./canvas-browser-profile`, relative to wherever the script is run. The tool lives under OneDrive, so signed-in Canvas session cookies can be synced to the cloud. Default it to a per-user local app-data folder. |
| 9 | Medium | 1277, 1400, 3047, 3317, 3790 | Every `HTTPError` on an assignment lookup is reported as "not found", including 401 (bad token), 403 and 5xx. Elsewhere an expired token produces a raw traceback, because there is no top-level error handling. |
| 10 | Low | 1168 | Section and student specs fall through to substring match even when another section matched by exact ID. `--section ""` matches every section. `A1` matches `A1-8` and `A10-3`. |
| 11 | Low | 1077, 1091, 3261 | Archive members and browser-downloaded uploads are read fully into memory. `.gz`, `.bz2`, `.xz` are listed as archives but only tar variants are handled; the rest fail silently. Archives are re-extracted on every rerun. |
| 12 | Low | 822-824 | Excel formulas depend on hard-coded column letters that must be edited by hand if `LOG_COLUMNS` changes. Derive them from the list. |
| 13 | Low | 4040, 4409 | `manifest.csv` and the grade-post log are plain UTF-8; every other CSV has a BOM. Accented names will be garbled in Excel in those two. `manifest.csv` is also overwritten each run. |
| 14 | Low | 1365 | Without `--assignment` the grade file's `title=` is filled with the label; the docs say it is left blank. |
| 15 | Low | 2690 | Leftover debug print (`retrying in ...`). |
| 16 | Low | — | `--base-url http://...` is accepted, which would send the token unencrypted. Require https. |
| 17 | Low | 3836+ | "replaces existing grade" compares strings, so `9` vs `9.0` warns. |

### 3.2 Structural problems (what the refactor addresses)

- **Logic is welded to the CLI.** 120 `print` calls, 25 `SystemExit` raises inside logic, 131 reads of `args.*`, one `input()` (4026). A GUI cannot capture progress, show an error dialog or ask for confirmation.
- **The main feature has no function.** The submission download is 170 lines inside `main()` (4250-4420), so it cannot be tested or called.
- **Modes are flags, not commands.** Nine modes share one flat flag namespace. Irrelevant flags are silently ignored (`--flat` with `--export-quiz`, `--tz` with `--post-grades`). `--dry-run` means four different things.
- **Exit codes differ by mode.** Download always returns 0; quiz export uses 0-3; posting uses 0/1.
- **No project scaffolding.** No git repository, no tests (the code has test seams such as `Canvas.sleep`, but no tests are in the folder), no `pyproject.toml` or pinned dependencies. The user manual is a 300-line docstring.
- **Oversized functions.** `browser_quiz_uploads` is 270 lines; `export_quiz` 170; `write_run_log` 180.

### 3.3 Duplicated code to consolidate

| Duplicated thing | Occurrences | Becomes |
|---|---|---|
| `Roster(canvas.sections(c), canvas.student_enrollments(c))` | 7 | `Roster.load(canvas, course_id)`, cached per run |
| Write to `.part`, then rename | 6 | `atomic_write()` context manager |
| CSV write boilerplate, inconsistent encoding | 7 | `write_csv(path, columns, rows)` |
| Student folder name `<Last-First>_<id>` | 3 | `student_folder_name(user)` |
| Matching a student by ID / SIS / login | 3 | one `StudentMatcher` |
| Matching by name (substring, letters-only, word-set) | 3 different rules | one module, rules named explicitly |
| Section spec matching (API roster and CSV roster) | 2 | one function over a common `Section` type |
| Primary-section choice | 2, different | one rule (see finding 5) |
| Instructor map | 2, different | `section_instructors()` only |
| "Exactly one `--assignment`, fetch it or exit" | 3 | `require_assignment()` |
| Select students, then intersect with assigned | 3 | `Selection.resolve()` |
| Start-or-resume job, poll, download, clear state | 2 | `ResumableJob` |
| `uploads_log.csv` per output folder | 2 | shared writer |

## 4. Proposed architecture

Three layers. Dependencies point downward only.

```
front ends      cli/            gui/ (later)
                   \            /
use cases        services/   one module per workflow
                      |
foundations      canvas/   domain/   qti/   storage/
```

```
painter/
  canvas/
    client.py        transport: auth, retry, pacing, pagination, fetch_file
    endpoints.py     typed calls: assignments, sections, enrollments, submissions, quizzes, exports
    jobs.py          poll_until, Progress waiting, ResumableJob + state file
  domain/
    roster.py        Roster (from API or from CSV), one primary-section rule
    selection.py     --section / --student / assigned-to filters
    matching.py      ID and name matching, all rules in one place
    duedates.py      DueDates, timestamp formatting
    naming.py        slug, safe_filename, student and assignment folder names
  qti/
    builder.py       QtiBuilder, QtiItemWriter (already pure; moves as-is)
    verify.py
  storage/
    files.py         atomic_write, extract
    tabular.py       CSV read/write with one encoding policy
    runlog_xlsx.py   Excel run log
  services/
    submissions.py   download submissions
    roster_export.py roster CSV
    organize.py      sort folders into sections
    grade_files.py   create and parse grade files
    grading.py       plan, post, verify grades
    quiz_export.py   quiz content + answers report
    quiz_uploads.py  file uploads (report links, browser)
  events.py          Reporter protocol and event types
  errors.py          PainterError hierarchy (replaces SystemExit)
  config.py          base URL, token source, timezone, default folders
  cli/
    main.py          argparse subcommands, console Reporter, exit codes
canvas_fetch_submissions.py   thin shim so existing commands keep working
tests/
```

### The contract that makes a GUI possible

Every service follows the same rules:

1. **Input is a dataclass, not `args`.** For example `DownloadRequest(course_id, assignment_ids, selection, layout, extract, history)`.
2. **Output is a dataclass, not printed text.** For example `DownloadResult(files, failures, skipped_new_quizzes)`. Failures are data (fixes finding 4).
3. **Progress goes through a `Reporter`**: `info`, `warning`, `progress(done, total)`, and `cancelled()`. The CLI's reporter prints; a GUI's reporter updates a progress bar and log pane.
4. **Errors are exceptions** from `errors.py` (`NotFound`, `AuthFailed`, `InvalidInput`, `CanvasUnavailable`). The CLI maps them to messages and exit codes; a GUI maps them to dialogs.
5. **Anything that changes Canvas or moves files is two calls**: `plan()` returns what would happen, `execute(plan)` does it. Grade posting already works this way; organize and download dry-run adopt it. Confirmation becomes the front end's job, which removes `input()` from the logic.

### CLI shape

Subcommands replace mode flags: `painter download`, `list`, `roster`, `organize`, `grades new`, `grades post`, `quiz export`, `quiz uploads`. Each accepts only the flags that apply to it. The old script stays as a shim that translates the old flags, so nothing in current use breaks.

## 5. GUI: web app or desktop

This decision can wait until phase 3 is done, because both options call the same services. The recommendation now is a **desktop app (PySide6)**:

- The tool is about local folders: output trees, grade files, roster CSVs. A browser page cannot hand back a real folder path, so a web UI would need its own file picker.
- A local web app means a server listening on a port while holding a Canvas token. It would need origin and CSRF protection, and may draw firewall prompts on a managed machine.
- Qt worker threads and signals map directly onto the `Reporter` events and cancellation.
- The browser-uploads mode already drives a separate Chrome window; a desktop app launching it is less confusing than a browser tab launching another browser.

The case for a local web UI (for example NiceGUI): faster to build, easier to make look good, and no Qt packaging. It is the better choice if installing or distributing a packaged executable on the target machines is harder than running Python.

A hosted web app is not recommended: it would have to store instructors' Canvas tokens and student work on a server.

Open question that decides it: what can be installed on the machines this will run on, and will anyone other than the author use it?

## 6. Way forward

| Phase | Work | Done when |
|---|---|---|
| 0. Safety net | `git init`; `pyproject.toml` with pinned `requests`, `openpyxl`, optional `playwright`; tests for the pure parts (grade file parser, `grade_fields`, `DueDates`, `RosterIndex.match`, `slug`, QTI builder against a saved quiz JSON); recorded HTTP fixtures for the client | Tests pass against the unmodified file |
| 1. Mechanical split | Move code into the package layout above with no behaviour change; old script becomes a shim | Same tests pass; same CLI output |
| 2. Bug fixes | Findings 1-4 and 8 first, then the rest, one commit each with a test | Each finding has a failing-then-passing test |
| 3. Decouple | Request/Result dataclasses, `Reporter`, `errors.py`; extract the download loop from `main()`; remove `print`/`SystemExit`/`input` from everything outside `cli/` | `grep` finds no `print(` or `args.` outside `cli/` |
| 4. Consolidate | Apply the table in 3.3; unify roster and matching rules; subcommand CLI | Each duplicated item has one definition |
| 5. GUI slice | One workflow end to end (pick course → pick assignment and sections → download with progress and cancel), then grade posting with plan preview and confirm | An instructor can do both without a terminal |

Phases 0-1 are low risk and unblock everything else. Phase 3 is the one the GUI depends on.

Token storage for the GUI (environment variable today) should move to the OS credential store (`keyring`) in phase 5.
