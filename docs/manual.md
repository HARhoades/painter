# Painter manual

Painter automates Canvas chores for instructors: downloading submissions,
rosters, grade files and grade posting, and quiz export. It runs on your own
machine with your own Canvas API token.

```
painter <command> [options]
python -m painter <command> [options]
python canvas_fetch_submissions.py <command> [options]     (the old script name)
```

`painter --help` and `painter <command> --help` list every option.

## Contents

1. [Setup](#setup)
2. [Commands at a glance](#commands-at-a-glance)
3. [Options every command takes](#options-every-command-takes)
4. [Choosing students: --section, --student and --exclude](#choosing-students---section---student-and---exclude)
5. [painter list](#painter-list)
6. [painter download](#painter-download)
7. [painter roster](#painter-roster)
8. [painter organize](#painter-organize)
9. [painter grades new](#painter-grades-new)
10. [painter grades post](#painter-grades-post)
11. [painter quiz export](#painter-quiz-export)
12. [painter quiz uploads](#painter-quiz-uploads)
13. [Exit status](#exit-status)
14. [Stopping a run, errors, rate limits](#stopping-a-run-errors-rate-limits)
15. [Old options to new commands](#old-options-to-new-commands)
16. [The window: painter-gui](#the-window-painter-gui)

## Setup

1. In Canvas: Account > Settings > "+ New Access Token". Copy the token.
2. Put it in the environment:
   `set CANVAS_API_TOKEN=...` (Windows) or `export CANVAS_API_TOKEN='...'`.
3. Install: `pip install -e .[xlsx]` (add `,browser` for `painter quiz uploads`,
   which also needs `playwright install chromium` if you use `--channel chromium`).

The token is only ever sent to your Canvas host, and only over https.

## Commands at a glance

| Command | What it does |
|---|---|
| `painter list assignments` | assignment IDs and names |
| `painter list sections` | section IDs, SIS IDs, sizes, names |
| `painter list students` | the roster: Canvas IDs, SIS IDs or logins, names, sections |
| `painter download` | download submission files, unpack archives, write a manifest and an Excel log |
| `painter roster FILE` | write the roster as a CSV (used by `organize`) |
| `painter organize FOLDER --roster FILE` | sort downloaded folders into one folder per section (offline) |
| `painter grades new` | write a blank grade file per section |
| `painter grades post FILE...` | post grade files: plan, confirm, post, verify |
| `painter quiz export` | a quiz's content and the students' answers |
| `painter quiz uploads` | a New Quiz's File Upload answers, through a browser |

## Options every command takes

| Option | Meaning |
|---|---|
| `--base-url URL` | your Canvas address, e.g. `https://school.instructure.com` (https only) |
| `--course ID` | the course (optional for `grades post`; not used by `organize`) |
| `--tz ZONE` | IANA time zone for times shown and logged, e.g. `America/New_York` (default: UTC, as Canvas returns them) |
| `--debug` | on an unexpected error, print the full traceback instead of saving a crash report |

These may go before or after the command: `painter --course 12345 download`
and `painter download --course 12345` are the same. Every other option belongs
to one command and must come after it; an option a command doesn't take is an
error. A single-valued option such as `--assignment` on `quiz export` may be
given only once.

## Choosing students: --section, --student and --exclude

`download`, `list students`, `roster`, `quiz export` and `quiz uploads` take:

- `--section SPEC` (repeatable): a section's Canvas ID, SIS section ID or name.
- `--student SPEC` (repeatable): a student's Canvas ID, SIS user ID, login or name.
- `--exclude SPEC` (repeatable): a student to leave out, matched like `--student`.

Specs are matched in tiers, stopping at the first tier with a hit: exact ID,
then exact name (ignoring case), then part of a name. So `A1` selects section
"A1" and not "A1-8" or "A10-3"; `ann` selects the student whose login is `ann`
rather than everyone named Ann. An empty spec is an error. A spec that matches
nothing stops the run and says so.

With both options, everyone in either is selected (a union). `--exclude` then
removes students from that selection; on its own it means everyone except
them. An `--exclude` that matches nobody is an error, like any other spec. Commands that
take `--assignment` also narrow the selection to students who have that
assignment (including "assign to" overrides).

When a student is in several sections, `--by-section` and `organize` file them
under the section you selected, otherwise their first real section. A
course-wide default section that holds every student never wins over a real
one.

## painter list

```
painter list assignments --base-url URL --course 12345
painter list sections    --base-url URL --course 12345
painter list students    --base-url URL --course 12345 [--section SPEC] [--student SPEC] [--assignment ID]
```

`list students` honours the same selection as a download: this lists everyone
in "Lab 002" plus Nguyen, among students assigned 67890:

```
painter list students --base-url URL --course 12345 --section "Lab 002" --student Nguyen --assignment 67890
```

## painter download

```
painter download --base-url URL --course 12345 [--assignment ID ...] [--section SPEC ...] [--student SPEC ...]
                 [--out DIR] [--by-section] [--flat] [--no-extract] [--history] [--no-xlsx] [--log-dir DIR]
```

| Option | Meaning |
|---|---|
| `--assignment ID` | only this assignment (repeatable; default: every assignment) |
| `--section`, `--student` | only these students (see above) |
| `--out DIR` | output folder (default `./submissions`) |
| `--by-section` | a folder per section inside each assignment folder |
| `--flat` | no folder per student: files go straight into the assignment (or section) folder, prefixed with the student |
| `--no-extract` | leave .zip/.tar/.gz/.bz2/.xz attachments packed |
| `--history` | also fetch earlier attempts (resubmissions) |
| `--no-xlsx` | skip the Excel run log |
| `--log-dir DIR` | where the Excel log goes (default `--out`) |

Output layout:

```
out/
  manifest.csv                     every file of every run, one row each
  submission_log_20261112_143005.xlsx
  Homework-1_67890/                <Assignment name>_<assignment id>
    Doe-Jane_884321/               <Last-First>_<Canvas user id>
      analysis.zip
      analysis/                    unpacked archive
        main.py
```

With `--by-section --flat`:

```
out/
  Homework-1_67890/
    Lab-002/
      Doe-Jane_884321__analysis.zip
      Doe-Jane_884321__analysis/
      Roe-Rick_884399__analysis.zip
```

- Assignment folders are named `<Name>_<assignment id>`, the same in every run
  whatever the filters, and different for two assignments with the same name.
  An old `NN_<Name>` folder from an earlier version is renamed the first time
  if exactly one matches; several are left alone with a note.
- Two attachments with the same name in one student folder get the attachment
  ID added (`essay__a123.pdf`, `essay__a456.pdf`) instead of overwriting each
  other.
- Reruns are cheap: a file already there at the size Canvas lists is kept
  ("cached"), and an archive unpacked before is not unpacked again. Files are
  written to `<name>.part` and renamed when complete, so an interrupted run
  never leaves a truncated file.
- Archive members that would land outside their folder are skipped.
- New Quiz submissions have no attachments (the files stay inside New
  Quizzes); the run says so and suggests `painter quiz export --uploads`.

`manifest.csv` has one row per attachment, including failures, with a
`status` column: `downloaded`, `cached`, `failed: <reason>`, or with
`; extract failed` added. Each run merges its rows into the existing manifest
(a file fetched again replaces its row), so a run of one assignment doesn't
erase the others. If any file fails, the run still finishes and exits with
status 1.

The Excel log (needs openpyxl) has four sheets: Files (one row per
attachment), By Student, By Section and Run Summary. Counts are formulas over
the Files sheet, so they follow any rows you sort, filter or delete there.
Failed files are listed but not counted as downloaded.

All CSVs Painter writes are UTF-8 with a BOM, so Excel shows accented names
correctly.

## painter roster

```
painter roster roster.csv --base-url URL --course 12345 [--section SPEC ...] [--student SPEC ...] [--assignment ID ...]
```

One line per student per section, sorted by last name. Columns: Student Full
Name, Student Canvas ID, Student First Name, Student Last Name, Instructor
Last Name, Section Name, Section Canvas ID. A section with several teachers
lists their surnames separated by "; "; TAs are used only for a section with
no teacher.

## painter organize

```
painter organize FOLDER --roster roster.csv [--to DIR] [--section SPEC ...] [--dry-run]
```

Sorts a folder of student sub-folders (or an `--out` folder of assignment
folders) into one folder per section, using a CSV from `painter roster`. It
needs no Canvas access.

| Option | Meaning |
|---|---|
| `--roster FILE` | the roster CSV (required) |
| `--to DIR` | copy into this folder instead of moving in place |
| `--section SPEC` | only these sections (repeatable) |
| `--dry-run` | show where everything would go; change nothing |

Every section in the roster gets a folder, except a course-wide default
section. A student folder or `--flat` file is matched by the Canvas ID in its
name (`Last-First_884321`, or Canvas's own bulk-download names such as
`lastfirst_884321_...`), and failing that by the student's name (letters
only, so punctuation and spacing don't matter). Anything unmatched, or
matching several students, is left in place and reported. Each run writes
`organize_log_<time>.csv`.

## painter grades new

```
painter grades new --base-url URL --course 12345 [--assignment ID] [--section SPEC ...]
                   [--label NAME] [--ay YY] [--term N] [--dir DIR] [--force]
```

Writes one grade file per section (default: every section), with each
student's name and Canvas ID filled in:
`<Section><Number>-<LABEL>_Grading-<AY>-<SEMESTER>.txt`, e.g.
`A1-DATE_Grading-27-1.txt` for section "A1-8".

| Option | Meaning |
|---|---|
| `--assignment ID` | fills in the assignment's title and id; without it they are left blank |
| `--section SPEC` | only these sections (repeatable) |
| `--label NAME` | the assignment part of the file name (default: first word of the assignment name; required without `--assignment`) |
| `--ay YY`, `--term N` | academic year and semester (default: read from the course's term name) |
| `--dir DIR` | where to write the files (default: current folder) |
| `--force` | overwrite existing files |

`instructor=` is the section's teacher (TAs only where there is no teacher).
Two sections whose names start the same (A2-8, A2-9) don't overwrite each
other: the second keeps its full section name.

## painter grades post

```
painter grades post FILE... --base-url URL [--course 12345] [--dry-run] [--yes]
                            [--allow-duplicate-comments] [--log-dir DIR]
```

Checks every file against Canvas and shows what would change; nothing is
posted if any file has an error (exit status 2). Then it asks for
confirmation (`--yes` skips it; without a terminal `--yes` is required), posts
each file with one bulk request, reads the grades back and verifies them.
Each run writes `grade_post_log_<time>.csv` next to the first file (or in
`--log-dir`).

| Option | Meaning |
|---|---|
| `--dry-run` | check and show the plan; post nothing |
| `--yes` | post without asking |
| `--allow-duplicate-comments` | post a comment even if the same text is already on the submission |
| `--log-dir DIR` | where the post log goes |

Grade file format (one assignment and one section per file):

```
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
```

- `id=` may be the Canvas user ID, SIS user ID or login. If it is blank the
  student is found by name (every word of the name must appear in the Canvas
  name, so "Jane Doe" and "Doe, Jane" both work); if both are given they must
  agree.
- `grade=` is whatever Canvas accepts for the grading type (points, 85%, A-,
  pass/complete...). `EX` or `excused` excuses the student. Blank sends only a
  comment.
- `comments=` may continue onto following lines. Blank sends only a grade.
- Unused `[STUDENT]` blocks are ignored. `--course` is optional: it is found
  from the section ID.
- A comment already on the submission word for word is not posted again, so a
  rerun doesn't duplicate comments. "Replaces existing grade" is only flagged
  when the value really changes (9 and 9.0 are the same).

## painter quiz export

```
painter quiz export --base-url URL --course 12345 --assignment ID [--section SPEC ...] [--student SPEC ...]
                    [--by-section] [--out DIR] [--no-answers] [--uploads] [--no-course-export]
                    [--timeout SECONDS] [--dry-run]
```

Exports one quiz into its assignment folder under `--out` (the folder
`painter download` uses for that assignment).

| Option | Meaning |
|---|---|
| `--assignment ID` | the quiz's assignment ID (required) |
| `--section`, `--student` | whose answers are kept |
| `--by-section` | a folder per section, each with its students' answers and its own copy of the content |
| `--out DIR` | output folder (default `./submissions`) |
| `--no-answers` | content only |
| `--uploads` | also download File Upload answers linked from the answers report |
| `--no-course-export` | skip the Common Cartridge course export (the slowest part) |
| `--timeout SECONDS` | how long to wait for each Canvas job (default 900); a rerun resumes a job that timed out |
| `--dry-run` | read the quiz and show how each question converts and where files would go; write nothing, start no job |

Every output folder gets:

| File | What it is |
|---|---|
| `<Quiz>_student-answers.csv` | Canvas's New Quizzes "student analysis" report; with filters only the selected students' rows are kept |
| `<Quiz>_new-quiz.json` | every question, choice, answer and feedback as the New Quizzes API returns them, plus the settings |
| `<Quiz>_qti.zip` | a QTI 1.2 package built from that JSON, in the Classic Quizzes layout Canvas imports |
| `<Quiz>_qti-report.csv` | one line per question: converted or not, and why |
| `<Quiz>_course-export.imscc` | a Common Cartridge export of the quiz's assignment, kept only if it really holds the quiz |

- The answers report's columns are undocumented, so rows are matched to
  students by value: whichever column best matches the roster's Canvas IDs,
  then SIS IDs, logins, names. The unfiltered report is deleted once split.
- Converted to QTI: multiple choice, true/false, multiple answer, essay, file
  upload, numeric, matching, fill in the blank (typed and drop-down), and
  stimuli (as text). Ordering, categorization, hot spot and formula questions
  have no Classic equivalent and stay in the JSON only. Questions drawn from
  an item bank can't be exported (the API returns only the bank's name).
- A Classic Quiz is exported with Canvas's own QTI export; student answers are
  only implemented for New Quizzes.
- `--uploads` saves files linked from the report into
  `<Quiz>_uploads/<Last-First>_<id>/` with `uploads_log.csv`. Only links to
  your Canvas host or Instructure's file stores, over https, are fetched;
  anything else students typed is ignored. New Quizzes has no API for these
  files, so this is best effort; `painter quiz uploads` is the reliable route.
- Canvas jobs are never started twice: report and export job IDs are saved in
  the quiz folder (`.quiz_export_state.json`) as soon as Canvas returns them,
  and a rerun resumes them. If another report is being generated (Canvas
  answers 409), the run waits for it.

Exit status: 0 everything delivered; 1 the answers or the course export were
not delivered (the reason is printed; rerun to resume a job); 3 none of the
selected students has the quiz.

## painter quiz uploads

```
painter quiz uploads --base-url URL --course 12345 --assignment ID [--section SPEC ...] [--student SPEC ...]
                     [--by-section] [--out DIR] [--profile DIR] [--channel chrome|msedge|chromium]
                     [--connect URL] [--headless] [--signin-timeout SECONDS] [--page-timeout SECONDS]
                     [--delay SECONDS] [--limit N] [--dry-run]
```

Opens each submitted student in SpeedGrader in a real browser (needs
Playwright) and saves their File Upload answers as
`<Quiz>_uploads/<Last-First>_<id>/Q<n>__<file>`, with `uploads_log.csv`.
Files are matched to students by quiz session ID, not by name. Reruns skip
files already saved.

| Option | Meaning |
|---|---|
| `--assignment ID` | the New Quiz's assignment ID (required) |
| `--section`, `--student`, `--by-section`, `--out` | as for `quiz export` |
| `--profile DIR` | browser profile that keeps you signed in (default: a local, not synced app-data folder; on Windows `%LOCALAPPDATA%\painter\browser-profile`). Keep it private |
| `--channel` | installed Chrome (default), Edge, or Playwright's Chromium |
| `--connect URL` | attach to a browser you started with `--remote-debugging-port` |
| `--headless` | hide the window (only once the profile is signed in) |
| `--signin-timeout SECONDS` | how long to wait for you to sign in (default 600) |
| `--page-timeout SECONDS` | how long to wait for each student's quiz (default 45) |
| `--delay SECONDS` | pause between students (default 1) |
| `--limit N` | only the first N students (alphabetical), for a trial run |
| `--dry-run` | list who would be visited; open no browser |

The first run opens the browser; sign in to Canvas there (SSO, CAC, 2FA as
usual) and the run carries on once Canvas loads. If sign-in hangs (CAC
certificate prompts often never appear in a browser Playwright starts), start
the browser yourself and attach to it:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\canvas-browser-profile
painter quiz uploads ... --connect http://localhost:9222
```

Exit status: 0 done; 1 some students or files had problems (see the log);
3 no submitted students to visit.

## Exit status

| Code | Meaning |
|---|---|
| 0 | done (also a dry run, nothing to post, or answering no at the prompt) |
| 1 | finished with problems: some files failed, grades not verified, quiz answers missing or the course export unfinished |
| 2 | bad input: wrong or misplaced options, a `--section`/`--student`/`--assignment` that matches nothing, errors in a grade file, `--yes` needed without a terminal |
| 3 | nothing matched: none of the selected students has the quiz |
| 4 | Canvas could not be used: bad token, no permission, not found, down or unreachable |
| 5 | local setup: `CANVAS_API_TOKEN` not set, a package (openpyxl, playwright) or the browser missing, a file that can't be written |
| 6 | failed, cause unknown: a crash report is saved and its path printed |
| 130 | interrupted with Ctrl+C |

## Stopping a run, errors, rate limits

- **Ctrl+C**: the first press asks the running task to stop at its next safe
  point. A download still writes its manifest and log, `organize` its log,
  grade posting finishes the file it is posting and writes its log, and saved
  Canvas jobs stay saved so a rerun resumes them. Exit status 130. A second
  Ctrl+C stops at once.
- **Unexpected errors** print one line and save the full details to
  `crash_<time>.txt` in Painter's local app-data folder (on Windows
  `%LOCALAPPDATA%\painter\logs`); the path is printed. `--debug` prints the
  details instead.
- **Canvas errors** say which kind: a rejected token (401), no permission
  (403), not found (404), or Canvas down. Only a 404 is reported as "not found".
- **Rate limits**: requests are sequential; throttled responses (429, or 403
  "Rate Limit Exceeded") are retried with backoff capped at 60 s, honouring
  Retry-After; requests slow down before Canvas's budget runs out; background
  jobs are polled at a growing interval capped at 30 s. A write (posting
  grades, starting an export) is retried only when it was throttled, never
  after a server error.

## Old options to new commands

The old single command with mode flags was replaced by subcommands in phase 4.

| Old | New |
|---|---|
| `--list-assignments` | `painter list assignments` |
| `--list-sections` | `painter list sections` |
| `--list-students` | `painter list students` |
| (no mode flag: download) | `painter download` |
| `--roster-csv FILE` | `painter roster FILE` |
| `--organize DIR --roster FILE` | `painter organize DIR --roster FILE` |
| `--organize-to DIR` | `painter organize ... --to DIR` |
| `--make-grade-files` | `painter grades new` |
| `--assignment-label NAME` | `painter grades new --label NAME` |
| `--grade-file-dir DIR` | `painter grades new --dir DIR` |
| `--post-grades FILE` (repeatable) | `painter grades post FILE...` |
| `--export-quiz` | `painter quiz export` |
| `--quiz-uploads` | `painter quiz export --uploads` |
| `--export-timeout SECONDS` | `painter quiz export --timeout SECONDS` |
| `--browser-uploads` | `painter quiz uploads` |
| `--browser-profile DIR` | `painter quiz uploads --profile DIR` |
| `--browser-channel NAME` | `painter quiz uploads --channel NAME` |
| `--connect-browser URL` | `painter quiz uploads --connect URL` |

Everything else (`--assignment`, `--section`, `--student`, `--out`,
`--by-section`, `--flat`, `--tz`, `--dry-run`, ...) keeps its name, but now
belongs to the commands that use it.

## The window: painter-gui

The two most common tasks, downloading submissions and posting grades, also
run in a window. Everything else stays on the command line for now (the
sidebar lists those tasks as "later").

```
pip install -e .[gui]
painter-gui
```

**Connect (Settings).** On first run, give your Canvas address and an access
token. Tick "Remember on this computer" to keep the token in Windows
Credential Manager (never in a file). You can save several tokens, each with
an optional name and expiration date; pick one from "Saved tokens", and use
Remove to forget an expired or invalid one. A saved token that has expired,
or expires within 7 days, shows a warning when you pick it. If
`CANVAS_API_TOKEN` is set, it is offered in the same list; you can still pick
a saved token or type a new one. The address, the last course, the token
last used (by its id, not the token), folders and download options are
remembered in `%LOCALAPPDATA%\painter\settings.json`. Settings (top right)
comes back here; the button is highlighted while you are on this page, and
pressing it again ("Close settings") returns to your courses.

**Choose a course.** Courses where you are a teacher or a TA, current term
first, with a filter by name, term and role. A TA can do whatever their
Canvas role allows; when Canvas refuses something, the window says so.

**Download submissions.**
1. Tick assignments. New Quizzes are listed but can't be ticked: their file
   uploads come via `painter quiz uploads`.
2. Pick sections (chips), add anyone else by name or ID ("Also include"), and
   open "Choose individual students" to leave someone out of a chosen section
   (the same as `--exclude`).
3. Choose the folder and the layout: "A folder per student" or "Flat: one
   folder", plus "A folder per section" (on by default; a line under it shows
   the result, such as Assignment › Section › Student › files). Choose
   whether to unpack archives. "More options" has earlier attempts, the Excel
   log and the time zone. The default folder is `submissions/` inside the
   Painter folder, which `.gitignore` keeps out of git; the window warns if
   you pick a folder inside the Painter folder that git would not ignore.

"Select all" above the section chips chooses every section at once (it
becomes "Clear all" when every section is chosen).

While you choose, the window counts the files a download would fetch. The
running screen shows one progress bar for the whole download, filled by the
percent of files done, and a thinner bar under it for the student being
downloaded (their files done out of the files they submitted). It also shows
Canvas's rate-limit pauses, every file
(✓ downloaded, ↺ already here, ✕ failed) and, folded, the same log the
command line prints. "Stop after this file" stops cleanly: the manifest and
log are written and running again picks up where it left off. The finished
screen lists what failed and why, and opens the folder, Excel log and
manifest.

**Saved course data.** So screens open at once, Painter keeps the last
assignment list, roster and per-student file counts for each course on this
computer, and shows them straight away. A small tag by each says how old it
is: "✓ Up to date · checked 2 min ago", or "⟳ From 3 days ago · checking…"
while Painter asks Canvas in the background (the list updates in place; what
you ticked stays ticked), or "● From … · not checked yet", or "⚠ Couldn't
confirm" if Canvas could not be reached. A value is rechecked automatically
when it is older than 10 minutes (assignments and file counts) or 1 day
(rosters). The small ↻ button beside a tag checks with Canvas right now.
Changing which sections or students are chosen never asks Canvas again; the
counts are worked out from what is already saved. The course list on the
Choose-a-course page has the same tag (1 hour) and its own Refresh link.

The files live in `.painter-cache/` inside the Painter folder (or in
`%LOCALAPPDATA%\painter\cache` if Painter is installed elsewhere), one
folder per kind: `assignments/`, `rosters/` (student names and IDs, kept apart
from everything else) and `filecounts/`. They are in `.gitignore`, as is
`submissions/`. Grades and grade comments are never saved: they are asked for
each time and forgotten when Painter closes. Settings has "Clear saved course
data" to delete these files; downloaded submissions are not touched.

**Buttons** that use the beige colouring lighten or darken slightly when the
pointer is over them.

**Post grades.**
1. Drop or choose grade files. Each is read at once; a file that can't be
   read shows the line and the problem, and must be fixed or removed first.
2. "Check against Canvas" reads only. Review shows one card per file: every
   student's grade before and after, the comment, and warnings (a grade that
   will change, a student not in the file's section). Any error blocks
   posting.
3. Confirm, and the window posts each file, reads every grade back and shows
   what Canvas has. A log is saved next to the grade files. For rows that
   didn't take, "Post again" checks just those students against Canvas again
   (so a comment that did arrive isn't sent twice) and asks you to confirm.

**One task at a time.** While a download or a post runs, the other task waits.
Closing the window during a download asks first and then stops cleanly;
during a post it waits for the file being posted to finish.

**Errors** are shown in words on the screen where they happened. Anything
unexpected also saves a crash report under `%LOCALAPPDATA%\painter\logs`
("Copy details" copies its path).

