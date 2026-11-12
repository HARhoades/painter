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
  domain/     roster, matching, due dates, naming, assignments
  qti/        QTI 1.2 builder and package check
  storage/    attachment download, archive extraction, Excel run log
  services/   one module per workflow: submissions, roster_export, organize,
              grade_files, grading, quiz_plan, quiz_export, quiz_uploads
  cli/        argument parsing and dispatch
canvas_fetch_submissions.py   shim: keeps old commands and imports working
tests/                        pytest suite; a fake Canvas, no network
```

## Tests

```
pip install -e .[dev]
pytest
```
