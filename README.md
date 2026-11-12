# Painter

Automates Canvas pain points for instructors: bulk submission downloads,
rosters, grade files, grade posting, and New Quiz export.

## Use

```
set CANVAS_API_TOKEN=...            (macOS/Linux: export CANVAS_API_TOKEN='...')
pip install -e .[xlsx]              (add ,browser for --browser-uploads)
python canvas_fetch_submissions.py --base-url https://school.instructure.com --course 12345 --list-assignments
```

`python canvas_fetch_submissions.py --help` lists every option. The full manual
(modes, file formats, output layout) is the docstring at the top of
`canvas_fetch_submissions.py`. `python -m painter` and the `painter` command
run the same program.

## Layout

```
painter/
  canvas/     client.py (HTTP, retry, pacing, pagination), jobs.py (polling, resume state)
  domain/     roster, selection (--section/--student), matching, due dates, naming, assignments
  qti/        QTI 1.2 builder and package check
  storage/    attachment download, archive extraction, Excel run log
  services/   one module per workflow: submissions, roster_export, organize,
              grade_files, grading, quiz_plan, quiz_export, quiz_uploads
  events.py   Reporter: how services report progress (info, warning, progress, cancelled)
  errors.py   PainterError and subclasses (AuthFailed, NotFound, InvalidInput, Cancelled, ...)
  config.py   token variable, default folders
  cli/        main.py (flags, exit codes), commands.py (flags -> requests),
              console.py (printing reporter, plan formatting)
canvas_fetch_submissions.py   shim: keeps old commands and imports working
tests/                        pytest suite; a fake Canvas, no network
```

Only `cli/` prints, prompts, exits or reads command-line flags; a test
enforces this. Everything else takes a request dataclass, reports through a
`Reporter`, returns a result dataclass and raises `painter.errors`
exceptions, so another front end (a GUI) can call it directly:

```python
from pathlib import Path
from painter.canvas.client import Canvas
from painter.domain.selection import Selection
from painter.events import RecordingReporter
from painter.services.submissions import DownloadRequest, download_submissions

canvas = Canvas("https://school.instructure.com", token)
req = DownloadRequest(course_id=12345, out_root=Path("submissions"),
                      assignment_ids=(67890,), selection=Selection.of(["Lab 002"]))
result = download_submissions(canvas, req, RecordingReporter())
print(result.failures, result.manifest)
```

Anything that changes Canvas or moves files is two calls: `plan_grades` then
`post_grade_plans`, `plan_organize` then `execute_organize`. Confirming is the
caller's job.

## Tests

```
pip install -e .[dev]
pytest
```
