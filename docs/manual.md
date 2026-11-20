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
                   [--label NAME] [--prefix short|full|instructor]
                   [--ay YY] [--term N] [--no-term] [--dir DIR] [--force]
```

Writes one grade file per section (default: every section), with each
student's name and Canvas ID filled in.

### File names

A grade file is named `<prefix>-<base>[-<AY>-<semester>].txt`:

| Part | What it is | Example for section "A1-8", assignment "DATE Scenario", AY27-1 |
|---|---|---|
| prefix | always there; from the section (`--prefix`) | `A1` (short, the default), `A1-8` (full), `A1-Rhoades` (instructor) |
| base | the assignment name, or what `--label` gives | `DATE-Scenario` |
| AY and semester | optional; left out with `--no-term` | `-27-1` |

So the default is `A1-DATE-Scenario-27-1.txt`; with `--prefix full --no-term`
it is `A1-8-DATE-Scenario.txt`. Names are made safe for Windows: characters
such as `: / ? *` are dropped, spaces become `-`, and the base is cut to 40
characters. The instructor prefix uses the section's teacher's surname (a TA
only where there is no teacher), and just the short prefix when a section has
neither.

The prefix comes from the section itself. A Canvas section name such as
`AI105    A1 8  - RHOADES, H` has the course code in front and the
instructor behind; both are left out, so short is `A1` and full is `A1-8`.
The course code is recognised as the word every section in the course starts
with, or a course-number shape such as `AI105`.

Names never clash. When chosen sections would share a prefix (A1 5 and A1 8
are both "A1"), every one of them uses the longer form (`A1-5`, `A1-8`; with
the instructor style `A1-5-Hicks`), so no file is named differently from the
others; if even that is shared, the section ID is added. Names that differ
only in capitals count as the same, as they do on Windows.

| Option | Meaning |
|---|---|
| `--assignment ID` | fills in the assignment's title and id; without it they are left blank |
| `--section SPEC` | only these sections (repeatable) |
| `--label NAME`, `--base NAME` | the base of the file name (default: the assignment name; required without `--assignment`) |
| `--prefix STYLE` | the section part of the file name: `short` (default), `full` or `instructor` |
| `--ay YY`, `--term N` | academic year and semester (default: read from the course's term name) |
| `--no-term` | leave the academic year and semester out of the file names (`--ay`/`--term` are then not needed) |
| `--dir DIR` | where to write the files (default: current folder) |
| `--force` | overwrite existing files |

`instructor=` in the file is the section's teacher (TAs only where there is
no teacher). An existing file is never overwritten without `--force`. What a
file is for comes from its contents, not its name, so renaming a grade file
never changes what is posted.

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

Downloading submissions, making grade files and posting grades also run in a
window. Everything else stays on the command line for now (the
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

Settings › **Grade files** holds the defaults for naming new grade files (the
prefix, and whether the academic year and semester are added) for courses
where you haven't chosen yet in Make grade files, and "Ask before saving
changes to a grade file" (on at first). Two greyed-out boxes, the due date and
points possible in the preview, are placeholders for later; the preview
doesn't ask Canvas for anything today.

**Choose a course.** Courses where you are a teacher or a TA, current term
first, with a filter by name, term and role. A TA can do whatever their
Canvas role allows; when Canvas refuses something, the window says so.

**Searching lists.** Every list you choose from has a search bar: the
assignments, the sections (by section name or instructor), the students under
"Choose individual students" (by name, SIS ID, login or Canvas ID), and the
saved grade files in Post grades. Type any words in any order; Esc or ✕
clears it. "Select all" then reads "Select all shown" and picks only what
matches, and a note says when something you chose is hidden by the search
("1 chosen not shown"); it stays chosen.

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
becomes "Clear all" when every section is chosen). Each chip shows the
section's instructor, and the "Instructor" list shows only that instructor's
sections; "Select all for <name>" then picks all of theirs. Sections chosen
earlier stay chosen while hidden, and a note says how many. If Canvas
doesn't list instructors to you, there is no filter.

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

When the download finishes, "Details: lateness and submissions" gives one
line (how many submissions, how many late and the longest, how many
submitted more than once) and opens to two tables: one row per assignment,
and one per student with the section, when they submitted, how many
submissions Canvas has from them, how late (or "excused") and how many
files. The student table sorts by any heading (latest first to start) and
has "Late only". It comes from the same rows as the manifest and Excel log;
scores are not shown. The progress bar starts at 0% and fills as files
arrive.

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

**Make grade files.** Tick one or more assignments and one or more sections
(each list has "Select all"), and Painter writes one blank file per section
for each assignment, with every student's name and Canvas ID filled in. The
same "Instructor" filter narrows the sections.

File names follow the rules in [File names](#file-names), set in box 3:
- **File name** (a column in the assignment list) is the base, filled in with
  the assignment's name. Double-click it to change it for one assignment;
  clear it to go back to the name. It is cleaned for disk as you type.
- **Starts with** picks the prefix: the short section (A1), the full section
  name (A1-8), or the section and instructor (A1-Rhoades). A prefix is always
  there.
- **Add the academic year and semester** puts `-27-1` on the end. Painter
  fills them from the course's term name (as the command line does); when the
  name doesn't say (e.g. "Fall 2026") type them in, like `--ay 27 --term 1`,
  or untick the box.
- **These files will be made** lists the exact names before anything is
  written, including any section that had to use its full name to avoid a
  clash.

All of these are remembered for each course. A course you haven't set yet
starts from the defaults in Settings › Grade files. By
default they go in `grade-files/<course code>/` inside the Painter folder, which
`.gitignore` keeps out of git because filled-in files hold grades (outside a
checkout: `Documents\Painter\grade-files`). A file already there is kept
unless you tick "Replace files that already exist", so grades you have typed
in are never overwritten. "Saved to" takes any folder (Browse…); Painter
remembers it for that course, warns if it is inside the Painter folder where
git could commit it, and Post grades lists the files there too. "Use
Painter's grade-files folder" goes back to the default. Two chosen
assignments never get the same base: the later one gets its assignment ID
added. This is the window's version of `painter grades new`.

**Post grades.**
1. Tick files under "Saved grade files" (the grade-files folder, this
   course first, each showing how many students are filled in), or drop or
   choose grade files kept elsewhere. Each is read at once; a file that can't be
   read shows the line and the problem, and must be fixed or removed first.
   When two of the chosen files are for the same assignment and section, a
   warning names them: both would be posted, the later file's grades
   replacing the earlier's. Remove the one you don't mean.
2. **Preview and edit** shows each file as it is saved, without asking
   Canvas: its assignment and section (with IDs), instructor, folder, when it
   was last changed and its size, then one card per student with name, Canvas
   ID, grade and comment. A student with no grade and no comment is shaded
   raspberry and marked "No grade or comment"; a card you have changed turns
   marigold until it is saved. With one file the cards are open; with several,
   "Show N students" opens each.
   - Type a new grade or comment straight into a card. Simple checks show on
     the card (e.g. "9o mixes digits and letters"); Review checks the grade
     properly against Canvas.
   - **Save changes to file…** asks first, then rewrites only those students'
     `grade=` and `comments=` lines; every other line of the file stays
     exactly as it was. "Undo changes" puts the saved values back. Settings ›
     Grade files › "Ask before saving changes to a grade file" turns the
     question off.
   - A comment line that the file would read as something else is refused
     with the reason: one that starts with `name=`, `id=`, `grade=` or
     `comments=`, or one that is a block header such as `[STUDENT]`. Reword
     it (e.g. "Your grade= …" is fine).
   - If another program (Notepad, OneDrive) changed the file after Painter
     read it, saving asks: reload it from disk (your changes here are
     dropped), or write your changes into it (its other changes are kept,
     except these students' grades and comments).
   - Leaving the screen, Back, or "Check against Canvas" with unsaved changes
     asks to save them, discard them, or stay; with the question turned off
     they are saved. Saving is written all the way to disk before Painter
     reads the files again for Review, so **what is posted is always what is
     saved in the files.**
3. "Check against Canvas" reads only. Review shows one card per file: every
   student's grade before and after, the comment, and warnings (a grade that
   will change, a student not in the file's section). Any error blocks
   posting. Back returns to Preview and edit, which shows any file changed
   on disk in the meantime.
4. Confirm, and the window posts each file, reads every grade back and shows
   what Canvas has. A log is saved next to the grade files. For rows that
   didn't take, "Post again" checks just those students against Canvas again
   (so a comment that did arrive isn't sent twice) and asks you to confirm.

**One task at a time.** While a download or a post runs, the other task waits.
Closing the window during a download asks first and then stops cleanly;
during a post it waits for the file being posted to finish.

**Errors** are shown in words on the screen where they happened. Anything
unexpected also saves a crash report under `%LOCALAPPDATA%\painter\logs`
("Copy details" copies its path).

