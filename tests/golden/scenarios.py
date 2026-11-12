"""CLI scenarios whose full behaviour is pinned by golden transcripts.

Each scenario gets a Ctx and runs the command line one or more times. The
harness (tests/test_golden.py) records, per run: exit code, stdout, stderr,
the Canvas requests made and the grade forms posted; and at the end, every
file under the scenario's folder. Paths and timestamps are normalised.

Regenerate after an intended behaviour change with:
    PAINTER_GOLDEN_RECORD=1 python -m pytest tests/test_golden.py
and review the diff of tests/golden/transcripts/ before committing.
"""
from __future__ import annotations

import csv

from conftest import BASE, FILES, make_response

COMMON = ("--base-url", BASE, "--course", "100")

GRADES = """\
[ASSIGNMENT]
title=DATE Scenario
id=7001

[SECTION]
title=A2-8
instructor=Smith
id=12

[STUDENT]
name=Roe, Rick
id=502
grade=8.5
comments=Already said this.

[STUDENT]
name=De La Cruz, Ana
id=
grade=EX
comments=Excused for
  the field exercise.
"""

ROSTER_ROWS = [
    ("Jane Doe", "501", "Jane", "Doe", "A1-8", "11"),
    ("Jane Doe", "501", "Jane", "Doe", "AI105 All", "10"),
    ("Rick Roe", "502", "Rick", "Roe", "A2-8", "12"),
    ("Rick Roe", "502", "Rick", "Roe", "AI105 All", "10"),
]


def write_roster(path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Student Full Name", "Student Canvas ID", "Student First Name",
                    "Student Last Name", "Section Name", "Section Canvas ID"])
        w.writerows(ROSTER_ROWS)
    return path


def make_tree(root):
    (root / "Doe-Jane_501").mkdir(parents=True)
    (root / "Doe-Jane_501" / "essay.pdf").write_text("x")
    (root / "Roe-Rick_502").mkdir()
    (root / "Stranger_999").mkdir()


def add_new_quiz(fake, report_rows="Name,ID,Q1\r\nJane Doe,501,True\r\nRick Roe,502,False\r\n"):
    fake.assignments.append({"id": 7003, "name": "Quiz 1", "is_quiz_lti_assignment": True,
                             "submission_types": ["external_tool"]})
    fake.submissions[7003] = {uid: {"user_id": uid, "workflow_state": "submitted",
                                    "submitted_at": "2026-09-01T00:00:00Z",
                                    "url": f"https://x/launch?quiz_session_id={uid}0"}
                              for uid in (501, 502, 503)}
    q = "/api/quiz/v1/courses/100/quizzes/7003"
    fake.extra[("GET", q)] = {"title": "Quiz 1", "quiz_settings": {}}
    fake.extra[("GET", f"{q}/items")] = [
        {"id": "1", "position": 1, "entry_type": "Item", "points_possible": 1,
         "entry": {"title": "TF", "item_body": "<p>Sky is blue</p>",
                   "interaction_type_slug": "true-false", "interaction_data": {},
                   "scoring_data": {"value": True}}},
        {"id": "2", "position": 2, "entry_type": "Item", "points_possible": 1,
         "entry": {"title": "Order", "interaction_type_slug": "ordering"}}]
    fake.extra[("POST", f"{q}/reports")] = {"id": 5, "workflow_state": "queued"}
    fake.extra[("GET", "/api/v1/progress/5")] = {
        "id": 5, "workflow_state": "completed", "completion": 100,
        "results": {"url": f"{BASE}/files/report.csv"}}
    fake.extra[("GET", "/files/report.csv")] = report_rows.encode("utf-8-sig")


def status(fake, method, path, code):
    fake.extra[(method, path)] = make_response(f"{BASE}{path}", code, {"errors": "x"})


SCENARIOS = {}


def scenario(fn):
    SCENARIOS[fn.__name__] = fn
    return fn


# ---- listings ------------------------------------------------------------------
@scenario
def list_assignments(c):
    c.run(*COMMON, "--list-assignments")


@scenario
def list_sections(c):
    c.run(*COMMON, "--list-sections")


@scenario
def list_students_all_and_filtered(c):
    c.run(*COMMON, "--list-students")
    c.run(*COMMON, "--list-students", "--section", "A2")
    c.run(*COMMON, "--list-students", "--student", "Doe", "--assignment", "7001")


@scenario
def list_students_bad_section(c):
    c.run(*COMMON, "--list-students", "--section", "nope")
    c.run(*COMMON, "--list-students", "--section", "")


@scenario
def list_students_unknown_assignment(c):
    c.run(*COMMON, "--list-students", "--assignment", "9999")


# ---- download ------------------------------------------------------------------
@scenario
def download_default_then_cached(c):
    c.run(*COMMON, "--out", str(c.tmp / "out"))
    c.run(*COMMON, "--out", str(c.tmp / "out"), "--no-xlsx")


@scenario
def download_by_section_flat_tz(c):
    c.run(*COMMON, "--out", str(c.tmp / "o"), "--assignment", "7001", "--section", "A2",
          "--by-section", "--flat", "--no-extract", "--no-xlsx", "--tz", "America/New_York")


@scenario
def download_by_section_nested(c):
    c.run(*COMMON, "--out", str(c.tmp / "o"), "--by-section", "--log-dir", str(c.tmp / "logs"))


@scenario
def download_student_filter_and_history(c):
    c.fake.submissions[7001][501]["submission_history"] = [
        {"attachments": [{"id": 3, "display_name": "essay.pdf", "url": f"{FILES}/f/3",
                          "size": 5}]}]
    c.fake.file_bodies["/f/3"] = b"draft"
    c.run(*COMMON, "--out", str(c.tmp / "o"), "--student", "jdoe2", "--history", "--no-xlsx")


@scenario
def download_failure(c):
    del c.fake.file_bodies["/f/1"]
    c.run(*COMMON, "--out", str(c.tmp / "o"), "--no-xlsx")


@scenario
def download_nothing_submitted(c):
    c.run(*COMMON, "--out", str(c.tmp / "o"), "--assignment", "7002", "--no-xlsx")


@scenario
def download_new_quiz_hint(c):
    add_new_quiz(c.fake)
    c.run(*COMMON, "--out", str(c.tmp / "o"), "--assignment", "7003", "--no-xlsx")


@scenario
def download_legacy_folder_renamed(c):
    (c.tmp / "o" / "03_DATE-Scenario" / "Doe-Jane_501").mkdir(parents=True)
    c.run(*COMMON, "--out", str(c.tmp / "o"), "--assignment", "7001", "--no-xlsx",
          "--no-extract")


@scenario
def download_bad_token(c):
    status(c.fake, "GET", "/api/v1/courses/100/assignments", 401)
    c.run(*COMMON, "--out", str(c.tmp / "o"))


@scenario
def download_bad_timezone(c):
    c.run(*COMMON, "--out", str(c.tmp / "o"), "--tz", "Mars/Olympus")


# ---- roster CSV ------------------------------------------------------------------
@scenario
def roster_csv_all(c):
    c.run(*COMMON, "--roster-csv", str(c.tmp / "roster.csv"))


@scenario
def roster_csv_filtered(c):
    c.run(*COMMON, "--roster-csv", str(c.tmp / "r.csv"), "--section", "A2",
          "--assignment", "7001")


# ---- grade files -------------------------------------------------------------------
@scenario
def grade_files_with_assignment_then_force(c):
    d = str(c.tmp / "g")
    c.run(*COMMON, "--make-grade-files", "--assignment", "7001", "--grade-file-dir", d)
    c.run(*COMMON, "--make-grade-files", "--assignment", "7001", "--grade-file-dir", d)
    c.run(*COMMON, "--make-grade-files", "--assignment", "7001", "--grade-file-dir", d,
          "--force", "--section", "A1")


@scenario
def grade_files_label_only(c):
    c.run(*COMMON, "--make-grade-files", "--assignment-label", "DATE",
          "--grade-file-dir", str(c.tmp / "g"), "--ay", "2027", "--term", "2")


@scenario
def grade_files_errors(c):
    c.run(*COMMON, "--make-grade-files", "--grade-file-dir", str(c.tmp / "g"))
    c.run(*COMMON, "--make-grade-files", "--assignment", "7001", "--assignment", "7002",
          "--grade-file-dir", str(c.tmp / "g"))
    c.run(*COMMON, "--make-grade-files", "--assignment", "9999",
          "--grade-file-dir", str(c.tmp / "g"))
    c.fake.course["term"]["name"] = "Fall"
    c.run(*COMMON, "--make-grade-files", "--assignment", "7001",
          "--grade-file-dir", str(c.tmp / "g"))


# ---- posting grades ------------------------------------------------------------------
def _grade_file(c, text=GRADES, name="A2-DATE_Grading-27-1.txt"):
    p = c.tmp / name
    p.write_text(text, encoding="utf-8")
    return str(p)


@scenario
def post_grades_dry_run(c):
    c.run("--base-url", BASE, "--post-grades", _grade_file(c), "--dry-run")


@scenario
def post_grades_yes(c):
    c.run("--base-url", BASE, "--post-grades", _grade_file(c), "--yes")


@scenario
def post_grades_prompt_yes_and_no(c):
    gf = _grade_file(c)
    c.monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    c.monkeypatch.setattr("builtins.input", lambda prompt="": (print(prompt, end=""), "n")[1])
    c.run("--base-url", BASE, "--post-grades", gf)
    c.monkeypatch.setattr("builtins.input", lambda prompt="": (print(prompt, end=""), "y")[1])
    c.run("--base-url", BASE, "--post-grades", gf, "--log-dir", str(c.tmp / "logs"))


@scenario
def post_grades_no_terminal(c):
    c.monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    c.run("--base-url", BASE, "--post-grades", _grade_file(c))


@scenario
def post_grades_errors(c):
    c.run("--base-url", BASE, "--post-grades",
          _grade_file(c, GRADES.replace("id=502", "id=999"), "bad.txt"), "--yes")
    c.run("--base-url", BASE, "--post-grades", _grade_file(c, "nonsense\n", "junk.txt"))
    c.run("--base-url", BASE, "--post-grades", str(c.tmp / "missing.txt"))


@scenario
def post_grades_nothing_to_post(c):
    text = GRADES.replace("grade=8.5", "grade=").replace("comments=Already said this.",
                                                        "comments=")
    text = text.replace("grade=EX", "grade=").replace(
        "comments=Excused for\n  the field exercise.", "comments=")
    c.run("--base-url", BASE, "--post-grades", _grade_file(c, text), "--yes")


@scenario
def post_grades_two_files_with_course(c):
    a = _grade_file(c)
    b = _grade_file(c, GRADES.replace("title=A2-8", "title=A1-8").replace("id=12", "id=11")
                    .replace("name=Roe, Rick\nid=502", "name=Doe, Jane\nid=501")
                    .replace("instructor=Smith", "instructor=Rhoades"), "A1.txt")
    c.run("--base-url", BASE, "--course", "100", "--post-grades", a, "--post-grades", b,
          "--dry-run",
          "--allow-duplicate-comments")


# ---- organize ------------------------------------------------------------------------
@scenario
def organize_dry_run_move_and_copy(c):
    src = c.tmp / "DATE-Scenario_7001"
    make_tree(src)
    roster = str(write_roster(c.tmp / "roster.csv"))
    c.run("--organize", str(src), "--roster", roster, "--dry-run")
    c.run("--organize", str(src), "--roster", roster, "--organize-to", str(c.tmp / "copy"))
    c.run("--organize", str(src), "--roster", roster)
    c.run("--organize", str(src), "--roster", roster)


@scenario
def organize_section_filter_and_errors(c):
    src = c.tmp / "s"
    make_tree(src)
    roster = str(write_roster(c.tmp / "roster.csv"))
    c.run("--organize", str(src), "--roster", roster, "--section", "A1", "--dry-run")
    c.run("--organize", str(src), "--roster", roster, "--section", "zzz")
    c.run("--organize", str(src), "--roster", roster, "--organize-to", str(src / "in"))
    c.run("--organize", str(c.tmp / "nope"), "--roster", roster)
    c.run("--organize", str(src), "--roster", str(c.tmp / "no-roster.csv"))


# ---- quiz export -----------------------------------------------------------------------
@scenario
def export_quiz_dry_run(c):
    add_new_quiz(c.fake)
    c.run(*COMMON, "--assignment", "7003", "--export-quiz", "--dry-run",
          "--out", str(c.tmp / "o"))


@scenario
def export_quiz_by_section(c):
    add_new_quiz(c.fake)
    c.run(*COMMON, "--assignment", "7003", "--export-quiz", "--no-course-export",
          "--by-section", "--out", str(c.tmp / "o"))


@scenario
def export_quiz_no_answers_and_student(c):
    add_new_quiz(c.fake)
    c.run(*COMMON, "--assignment", "7003", "--export-quiz", "--no-course-export",
          "--no-answers", "--out", str(c.tmp / "o"))
    c.run(*COMMON, "--assignment", "7003", "--export-quiz", "--no-course-export",
          "--student", "Roe", "--out", str(c.tmp / "o2"))


@scenario
def export_quiz_with_upload_links(c):
    add_new_quiz(c.fake, "Name,ID,Q1\r\n"
                         f"Jane Doe,501,see {BASE}/files/77/download\r\n"
                         "Rick Roe,502,https://evil.example/files/1 and "
                         "https://bucket.s3.amazonaws.com/a.pdf\r\n")
    c.fake.extra[("GET", "/api/v1/files/77")] = {
        "id": 77, "display_name": "plan.pdf", "url": f"{FILES}/f/1", "size": 19}
    real = c.fake.handle

    def handle(session, method, url, **kw):          # the fake knows two hosts only
        if url.startswith("https://bucket.s3.amazonaws.com/"):
            c.fake.calls.append((method, url, {}))
            return make_response(url, content=b"s3 file")
        return real(session, method, url, **kw)
    c.fake.handle = handle
    c.run(*COMMON, "--assignment", "7003", "--export-quiz", "--no-course-export",
          "--quiz-uploads", "--out", str(c.tmp / "o"))


@scenario
def export_quiz_report_without_id(c):
    add_new_quiz(c.fake)
    c.fake.extra[("POST", "/api/quiz/v1/courses/100/quizzes/7003/reports")] = {}
    c.run(*COMMON, "--assignment", "7003", "--export-quiz", "--no-course-export",
          "--out", str(c.tmp / "o"))


@scenario
def export_quiz_errors(c):
    c.run(*COMMON, "--export-quiz", "--out", str(c.tmp / "o"))
    c.run(*COMMON, "--assignment", "7001", "--export-quiz", "--out", str(c.tmp / "o"))
    c.run(*COMMON, "--assignment", "9999", "--export-quiz", "--out", str(c.tmp / "o"))


@scenario
def export_classic_quiz_dry_run(c):
    c.fake.assignments.append({"id": 7004, "name": "Old Quiz", "quiz_id": 44,
                               "submission_types": ["online_quiz"]})
    c.fake.submissions[7004] = {}
    c.run(*COMMON, "--assignment", "7004", "--export-quiz", "--dry-run",
          "--out", str(c.tmp / "o"))


# ---- browser uploads (no Playwright in tests) ---------------------------------------
@scenario
def browser_uploads_dry_run_and_missing_playwright(c):
    add_new_quiz(c.fake)
    c.run(*COMMON, "--assignment", "7003", "--browser-uploads", "--dry-run",
          "--by-section", "--out", str(c.tmp / "o"))
    c.run(*COMMON, "--assignment", "7003", "--browser-uploads", "--limit", "1",
          "--out", str(c.tmp / "o"))


@scenario
def browser_uploads_errors(c):
    c.run(*COMMON, "--browser-uploads", "--out", str(c.tmp / "o"))
    c.run(*COMMON, "--assignment", "7001", "--browser-uploads", "--out", str(c.tmp / "o"))


# ---- argument and environment errors ------------------------------------------------
@scenario
def argument_errors(c):
    c.run("--course", "100")
    c.run("--base-url", BASE)
    c.run("--base-url", "http://canvas.test", "--course", "100")
    c.run(*COMMON, "--export-quiz", "--roster-csv", "r.csv")
    c.run("--organize", "x")
    c.run(*COMMON, "--quiz-uploads")
    c.run(*COMMON, "--roster", "r.csv")


@scenario
def missing_token(c):
    c.monkeypatch.delenv("CANVAS_API_TOKEN")
    c.run(*COMMON, "--list-assignments")


@scenario
def canvas_errors(c):
    status(c.fake, "GET", "/api/v1/courses/100/sections", 403)
    c.run(*COMMON, "--list-sections")
    status(c.fake, "GET", "/api/v1/courses/100/sections", 503)
    c.run(*COMMON, "--roster-csv", str(c.tmp / "r.csv"))
