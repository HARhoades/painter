#!/usr/bin/env python3
"""
Download (and optionally extract) student submission files from a Canvas course.

Setup
-----
1. In Canvas: Account -> Settings -> "+ New Access Token". Copy the token.
2. export CANVAS_API_TOKEN='...'         (Windows: set CANVAS_API_TOKEN=...)
3. pip install requests

Usage
-----
  # list assignments so you can find the IDs
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-assignments

  # download everything for the course (unchanged default)
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --out ./submissions

  # just one assignment, no auto-extract
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --assignment 67890 --no-extract

  # only certain students -- by Canvas ID, SIS ID, login, or name fragment
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --student 884321 --student "Nguyen" --student jdoe2

  # see the roster (IDs, SIS IDs, logins, sections) to build those filters
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-students

  # --list-students honours the same filters: this lists everyone in
  # "Lab 002" plus Nguyen, limited to students assigned assignment 67890
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-students --section "Lab 002" --student Nguyen \
      --assignment 67890

  # whole sections, by ID / SIS ID / name fragment
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --section "Lab 002" --section 45678 --by-section

  # union: everyone in one section, plus one extra student elsewhere
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --section "Lab 002" --student 884321

  # sections as folders, but every file directly inside the section folder
  # (no per-student sub-folders); filenames are prefixed with the student
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --by-section --flat

  # see the sections
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --list-sections

Creating grade files
--------------------
  # one file per section, students pre-filled from the Canvas roster
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --make-grade-files --assignment 280869 \
      --section 27425 --section 27440 --grade-file-dir ./grading

  Writes <Section><Number>-<ASSIGNMENT>_Grading-AY<YY>-<SEMESTER>.txt, e.g.
  A1-DATE_Grading-27-1.txt for section "A1-8". The assignment part of the name
  is the first word of the Canvas assignment name (override with
  --assignment-label); the AY and semester are read from the course's term
  name (override with --ay 27 --term 1).

  --section is repeatable and accepts a section ID, SIS ID or name fragment;
  with none given, every section in the course gets a file. title= and
  instructor= come from Canvas for each section, and each [STUDENT] block is
  filled in with the student's name and Canvas user ID, leaving grade= and
  comments= for you. --assignment is optional: without it the [ASSIGNMENT]
  title and id are left blank to fill in before posting. Existing files are
  never overwritten unless you pass --force.

Exporting the roster
--------------------
  # one CSV line per student, sorted by last name
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --roster-csv roster.csv

  # just some sections (and/or students), same filters as a download run
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --roster-csv roster.csv --section A2-8 --section 27440

  Columns: Student Full Name (First Last), Student Canvas ID, Student First
  Name, Student Last Name, Instructor Last Name, Section Name, Section Canvas
  ID. A student enrolled in several sections gets one line per section (with
  --section, only the selected ones). A section with several teachers lists
  their surnames separated by "; "; TAs are used only when a section has no
  teacher. The file is UTF-8 with a BOM so Excel shows accented names correctly.

Sorting submissions into section folders
----------------------------------------
  # move each student folder into a folder for their section (no Canvas
  # access needed -- everything comes from the roster CSV above)
  python canvas_fetch_submissions.py --organize ./submissions/DATE-Scenario_67890 \
      --roster roster.csv

  # preview first; or copy into a new tree and leave the original untouched
  python canvas_fetch_submissions.py --organize ./submissions/DATE-Scenario_67890 \
      --roster roster.csv --dry-run
  python canvas_fetch_submissions.py --organize ./submissions/DATE-Scenario_67890 \
      --roster roster.csv --organize-to ./by_section

  Every section in the roster gets a folder named for it (e.g. A2-8), even if
  nobody in it submitted -- except a section that holds the whole roster
  (a course-wide default section), which would always be empty. Each student sub-folder (or --flat file) is matched
  to a roster line by the Canvas ID in its name -- Last-First_884321 as this
  script writes it, or the lastfirst_884321_... names in Canvas's own bulk
  download -- and, failing that, by the student's name. Pointing --organize at
  the --out folder of a whole run sorts every assignment folder inside it.
  --section limits the run to those sections (by name or ID). Anything that
  can't be matched, or matches more than one student, is left where it is and
  reported. A student listed in two sections goes to the one that isn't shared
  by the whole roster; if that doesn't settle it, the first is used with a
  warning (pass --section to choose). Each run writes organize_log_*.csv.

Posting grades and comments
---------------------------
  # check a grade file against Canvas without posting anything
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --post-grades A2-DATE_Grading-27-1.txt --dry-run

  # post it (shows the plan, then asks for confirmation; --yes skips the prompt)
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --post-grades A2-DATE_Grading-27-1.txt --post-grades A2-DATE_Grading-27-2.txt

  Grade file format (one assignment and one section per file):

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

  * id= may be the Canvas user ID, SIS user ID, or login. If it is blank the
    student is matched by name ("Jane Doe" and "Doe, Jane" both work); if both
    are given they must agree.
  * grade= is whatever Canvas accepts for the assignment's grading type
    (points, 85%, A-, pass/complete...). EX or excused excuses the student.
    Leave it blank to send only a comment.
  * comments= may continue onto following lines. Leave it blank to send
    only a grade.
  * Unused [STUDENT] blocks (every field blank) are ignored.
  * --course is optional here: it is looked up from the section ID.

  Everything is posted through the bulk update_grades endpoint, one request
  per file. Nothing is posted if any file has an error. A comment that is
  already on the student's submission word-for-word is not posted again, so a
  rerun does not duplicate comments. Each run writes grade_post_log_*.csv.

Exporting quiz answers and content
----------------------------------
  # every student's answers to one New Quiz, plus the quiz itself, in the
  # quiz's folder under --out (the folder a download run with this
  # --assignment uses)
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --assignment 280869 --export-quiz

  # just two sections' answers, one folder per section; each folder also
  # gets its own copy of the quiz content
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --assignment 280869 --export-quiz \
      --section "Lab 001" --section "Lab 002" --by-section

  # preview: shows how each question converts and where files would go;
  # writes nothing and starts no report or export job
  python canvas_fetch_submissions.py --base-url https://school.instructure.com \
      --course 12345 --assignment 280869 --export-quiz --dry-run

  Every output folder gets:

    <Quiz>_student-answers.csv   Canvas's New Quizzes "student analysis"
                                 report: what each student answered. Without
                                 filters it is kept exactly as Canvas made it;
                                 with --section/--student/--by-section only the
                                 selected students' rows are kept, under the
                                 report's own header (skip it: --no-answers)
    <Quiz>_new-quiz.json         the quiz content: every question, answer
                                 choice, correct answer and feedback exactly
                                 as the New Quizzes API returns them, plus the
                                 quiz settings
    <Quiz>_qti.zip               QTI 1.2 package built from that JSON, in the
                                 Classic Quizzes layout Canvas imports
    <Quiz>_qti-report.csv        one line per question: converted or not, why
    <Quiz>_course-export.imscc   a Common Cartridge course export of the quiz's
                                 assignment -- kept only if it really contains
                                 the quiz (skip it: --no-course-export)

  Instructure does not document the answers report's columns, so rows are
  matched to students by value, not header name: whichever column best
  matches the course roster's Canvas user IDs (then SIS IDs, logins, names).
  If none does, filtered answers are not written and the run says why. The
  unfiltered report is deleted once it has been split.

  Canvas's API has no QTI export for New Quizzes (only the quiz's Build >
  Exports tab in the browser), which is why the QTI zip is built here.
  Converted to QTI: multiple choice, true/false, multiple answer, essay, file
  upload, numeric, matching, fill in the blank (typed and drop-down), and
  stimuli (as text-only questions). Ordering, categorization, hot spot and
  formula questions have no Classic equivalent and stay in the JSON only.
  Questions drawn at random from an item bank cannot be exported: the API
  returns only the bank's name. Each limit is listed in the report CSV.

  New Quiz File Upload answers: a New Quiz submission is an LTI launch with
  no attachments, so a normal download run finds no files for it (it says
  so). Add --quiz-uploads to --export-quiz to download any file links the
  student analysis report contains into <Quiz>_uploads/<Student>_<id>/, with
  an uploads_log.csv. New Quizzes has no API for these files, so this is
  best effort; if the report has no links the run says so and lists the
  report's columns.

  The reliable route is --browser-uploads, which uses a real browser
  (pip install playwright) because the New Quizzes API only accepts the
  token the quiz tool gets inside the browser:

    python canvas_fetch_submissions.py --base-url https://school.instructure.com \
        --course 12345 --assignment 290440 --browser-uploads --limit 3

  The first run opens Chrome; sign in to Canvas there (SSO/CAC as usual)
  and the run carries on by itself once Canvas loads. The session is kept in
  ./canvas-browser-profile (keep that folder private), so later runs start
  signed in.

  If sign-in hangs (CAC certificate prompts often never appear in a browser
  that Playwright starts), start the browser yourself and let the script
  attach to it:

    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
        --remote-debugging-port=9222 --user-data-dir=C:\\canvas-browser-profile
    (Edge: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe")

  Sign in to Canvas in that window, then run with
  --browser-uploads --connect-browser http://localhost:9222

  Each submitted student is opened in SpeedGrader, their File Upload files
  are read from the quiz's own results and saved as <Quiz>_uploads/<Last-First>_<id>/Q<n>__<file>,
  with uploads_log.csv. Files are matched to students by quiz session ID,
  not by name. Reruns skip files already saved. --dry-run lists who would
  be visited without opening a browser.

  A Classic Quiz's content is exported with Canvas's own QTI content export;
  student answers are only implemented for New Quizzes.

  Jobs are never started twice: the report and export job IDs are saved in
  the quiz folder (.quiz_export_state.json) as soon as Canvas returns them,
  and a rerun after a timeout or interruption resumes them. If a report is
  already being generated (Canvas answers 409), the tool waits for it. Files
  are downloaded as soon as each job finishes.

  Exit status: 0 = everything delivered; 1 = nothing exported (no selected
  student has the quiz); 2 = answers and content delivered but the course
  export did not finish (rerun to resume); 3 = the student answers were not
  delivered (the reason is printed; the quiz content still was).

Rate limits
-----------
  Canvas throttles each API token with a leaky bucket. Every request here is
  sequential; throttled responses (429, or 403 "Rate Limit Exceeded") are
  retried with exponential backoff capped at 60 s, honouring Retry-After;
  requests slow down before the bucket runs dry, based on the
  X-Rate-Limit-Remaining header; and background jobs are polled at a growing
  interval capped at 30 s. Retries for a write (posting grades, starting an
  export) happen only for throttling, never after a server error.

Each download run also writes an Excel log named for the run's start time, e.g.
submission_log_20260819_143005.xlsx, with sheets: Files (one row per
downloaded file), By Student, By Section, and Run Summary. Requires
openpyxl (pip install openpyxl); use --no-xlsx to skip it.

Output layout
-------------
  out/
    Homework-1_67890/
      Doe-Jane_884321/
        analysis.zip
        analysis/            <- extracted contents
          main.py
      manifest.csv

  With --by-section --flat:
  out/
    Homework-1_67890/
      Lab-002/
        Doe-Jane_884321__analysis.zip
        Doe-Jane_884321__analysis/    <- extracted contents (omit with --no-extract)
        Roe-Rick_884399__analysis.zip
    manifest.csv
"""
# This file is kept so existing commands and imports keep working.
# The code now lives in the painter package; see painter/cli/main.py.
# ruff: noqa: F401

from painter.config import (  # noqa: F401
    TOKEN_ENV,
)
from painter.canvas.client import (  # noqa: F401
    BACKOFF_BASE, BACKOFF_CAP, Canvas, DOWNLOAD_ATTEMPTS, MAX_ATTEMPTS, PACE_CAP,
    RATE_LOW_WATER, RATE_REFILL_PER_SEC, backoff_delay, is_throttled,
    retry_after_seconds,
)
from painter.canvas.jobs import (  # noqa: F401
    POLL_CAP, POLL_FACTOR, POLL_START, _load_state, _save_state, poll_until,
)
from painter.domain.duedates import (  # noqa: F401
    DueDates, fmt_lateness, fmt_ts, parse_ts,
)
from painter.domain.naming import (  # noqa: F401
    flat_filename, safe_filename, slug, student_dir_name,
)
from painter.domain.matching import (  # noqa: F401
    _letters, _name_tokens, name_matches,
)
from painter.domain.roster import (  # noqa: F401
    Roster, assigned_students, instructor_label, match_section, match_student,
    resolve_sections, resolve_students, section_instructors, select_students,
    split_name,
)
from painter.domain.assignments import (  # noqa: F401
    assignment_dir_name, assignment_folder, quiz_kind,
)
from painter.storage.files import (  # noqa: F401
    ARCHIVE_SUFFIXES, download, extract,
)
from painter.storage.runlog_xlsx import (  # noqa: F401
    COL_ASSIGN_ID, COL_LATE, COL_NEW_SUB, FONT, HEAD_FILL, LOG_COLUMNS, _yn,
    log_filename, write_run_log,
)
from painter.qti.builder import (  # noqa: F401
    CANVAS_META_NS, CC_NS, QTI_NS, QTI_REPORT_COLUMNS, QtiBuilder, QtiItemWriter,
    Unsupported, XSI_NS, _el, _escape, _mattext, _num, _xml_bytes, strip_html,
)
from painter.qti.verify import (  # noqa: F401
    verify_qti_zip,
)
from painter.services.submissions import (  # noqa: F401
    collect_attachments, run_download,
)
from painter.services.grade_files import (  # noqa: F401
    GRADE_FILE_KEYS, GradeEntry, GradeFile, GradeFileError, TERM_PATTERNS,
    grade_file_name, make_grade_files, parse_grade_file, parse_term_name,
    render_grade_file, section_prefix,
)
from painter.services.roster_export import (  # noqa: F401
    ROSTER_CSV_COLUMNS, export_roster_csv,
)
from painter.services.organize import (  # noqa: F401
    RosterIndex, organize_submissions, read_roster_csv,
)
from painter.services.grading import (  # noqa: F401
    EXCUSED_WORDS, GradePlan, PASS_FAIL_WORDS, PlannedGrade, _grade_before,
    _norm_comment, _preview, grade_fields, plan_grade_file, post_grade_plan,
    post_grades, print_grade_plan, resolve_grade_entry, verify_posted,
)
from painter.services.quiz_plan import (  # noqa: F401
    QuizExportPlan, find_student_column, quiz_export_plan,
)
from painter.services.quiz_uploads import (  # noqa: F401
    CANVAS_FILE_ID_RE, LAUNCH_SESSION_RE, QUIZ_RESULTS_RE, QUIZ_SESSION_RE,
    TRUSTED_HOST_SUFFIXES, URL_RE, _is_file_link, browser_quiz_uploads,
    download_report_uploads, submission_quiz_session, uploads_in_results,
)
from painter.services.quiz_export import (  # noqa: F401
    ANSWERS_STATE_KEY, EXPORT_FINAL_STATES, EXPORT_MAX_AGE_DAYS, EXPORT_STATE_FILE,
    ORPHAN_WINDOW_SECONDS, REPORT_REUSE_SECONDS, _export_expired,
    _find_orphan_export, export_quiz, package_contains_quiz, run_content_export,
    run_quiz_report, write_answers,
)
from painter.cli.main import (  # noqa: F401
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
