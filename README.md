# Painter

Automates Canvas chores for instructors: bulk submission downloads, rosters,
grade files and grade posting, and quiz export.

## Use

```
set CANVAS_API_TOKEN=...            (macOS/Linux: export CANVAS_API_TOKEN='...')
pip install -e .[xlsx]              (add ,browser for `painter quiz uploads`)
painter list assignments --base-url https://school.instructure.com --course 12345
painter download --base-url https://school.instructure.com --course 12345 --assignment 67890
```

There's also a window for downloading submissions and posting grades:
`pip install -e .[gui]`, then `painter-gui` (see "The window" in the manual).

Commands: `list`, `download`, `roster`, `organize`, `grades new`, `grades post`,
`quiz export`, `quiz uploads`. `painter --help` and `painter <command> --help`
list every option; [docs/manual.md](docs/manual.md) is the full manual, with
file formats, output layout, exit codes, and a table from the old `--flag`
options to the new commands. `python -m painter` and `python
canvas_fetch_submissions.py` run the same commands.

## Layout

```
painter/
  canvas/     client.py (HTTP, retry, pacing, cancellable waits), jobs.py (polling, ResumableJob)
  domain/     roster, selection (--section/--student), matching (every ID and name rule),
              due dates, naming, assignments
  qti/        QTI 1.2 builder and package check
  storage/    atomic.py (write-then-rename), tabular.py (CSV), files.py (downloads,
              archives), runlog_xlsx.py (Excel log)
  services/   one module per workflow: submissions, roster_export, organize,
              grade_files, grading, quiz_plan, quiz_export, quiz_uploads
  events.py   Reporter, typed events (Stage, ItemDone, Waiting, ActionNeeded),
              QueueReporter for a GUI, watch() for the Canvas client
  errors.py   PainterError and subclasses (AuthFailed, NotFound, InvalidInput, Cancelled, ...)
  config.py   token variable, local app-data folders
  cli/        main.py (subcommands), commands.py (options -> requests),
              console.py (printing reporter, Ctrl+C), exit_codes.py (one table)
  gui/        the window (PySide6): app.py (main window), session.py, worker.py
              (TaskRunner), style.py (palette, stylesheet), views/ (one per screen),
              widgets.py, student_picker.py; fonts/ (OFL)
  credentials.py  token in the OS credential store (keyring), env var first
  crash.py    crash reports, shared by the CLI and the window
canvas_fetch_submissions.py   the old script name; runs the same commands
docs/manual.md                the manual
tests/                        pytest suite; a fake Canvas, no network
```

Only `cli/` prints, prompts, exits or reads command-line options, and only
`gui/` imports Qt; tests enforce both, and others enforce that each piece of shared logic has one
home and no function is over 80 lines. Everything else takes a request
dataclass, reports through a `Reporter`, returns a result dataclass and raises
`painter.errors` exceptions, so another front end (a GUI) can call it
directly (painter/gui does exactly this):

```python
from pathlib import Path
import threading
from painter.canvas.client import Canvas
from painter.domain.selection import Selection
from painter.events import QueueReporter
from painter.services.submissions import DownloadRequest, download_submissions

canvas = Canvas("https://school.instructure.com", token)
req = DownloadRequest(course_id=12345, out_root=Path("submissions"),
                      assignment_ids=(67890,), selection=Selection.of(["Lab 002"]))
reporter = QueueReporter()          # the GUI thread reads reporter.queue; reporter.cancel() stops
threading.Thread(target=download_submissions, args=(canvas, req, reporter)).start()
```

Typed events say what a GUI needs to show: `Stage` (a step starts, with its
item count), `ItemDone` (a file, grade, folder or upload finished), `Waiting`
(rate limit, retry or a Canvas job still running, with its percent) and
`ActionNeeded` (sign in in the browser window). Every long wait can be
cancelled; a service that has already changed something still writes its log
and raises `Cancelled` with what it did on `.result`.

Anything that changes Canvas or moves files is two calls: `plan_grades` then
`post_grade_plans`, `plan_organize` then `execute_organize`. Confirming is the
caller's job.

## Tests

```
pip install -e .[dev]
pytest
```

The window's tests (tests/gui) need `pip install -e .[gui-test]` and run
headless with `QT_QPA_PLATFORM=offscreen`; without PySide6 they are skipped.
