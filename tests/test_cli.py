"""End-to-end runs of the command line against the fake Canvas."""
import csv
import json
import zipfile

import pytest

from conftest import BASE

COMMON = ("--base-url", BASE, "--course", "100")


def read_csv(path, encoding="utf-8-sig"):
    with open(path, newline="", encoding=encoding) as fh:
        return list(csv.DictReader(fh))


def tree(root):
    return sorted(str(p.relative_to(root)).replace("\\", "/")
                  for p in root.rglob("*") if p.is_file())


# ---- listings -----------------------------------------------------------------
def test_list_assignments(fake_canvas, run_cli):
    code, out, _ = run_cli(*COMMON, "--list-assignments")
    assert code == 0
    assert out.splitlines() == ["      7001  DATE Scenario", "      7002  Reflection"]


def test_list_sections(fake_canvas, run_cli):
    code, out, _ = run_cli(*COMMON, "--list-sections")
    assert code == 0
    assert out.splitlines() == [
        "        11  SIS-A1               1 students  A1-8",
        "        12  -                    2 students  A2-8"]


def test_list_students_honours_filters(fake_canvas, run_cli):
    code, out, err = run_cli(*COMMON, "--list-students", "--section", "A2")
    assert code == 0
    assert [line.split()[0] for line in out.splitlines()] == ["503", "502"]
    assert "2 student(s) of 3 in the course" in err


# ---- download -----------------------------------------------------------------
def test_download_default_layout(fake_canvas, run_cli, tmp_path):
    pytest.importorskip("openpyxl")
    out_dir = tmp_path / "submissions"
    code, out, err = run_cli(*COMMON, "--out", str(out_dir))
    assert code == 0, err
    files = tree(out_dir)
    xlsx = [f for f in files if f.startswith("submission_log_")]
    assert len(xlsx) == 1
    assert [f for f in files if f not in xlsx] == [
        "DATE-Scenario_7001/Doe-Jane_501/essay.pdf",
        "DATE-Scenario_7001/Roe-Rick_502/analysis.zip",
        "DATE-Scenario_7001/Roe-Rick_502/analysis/data/in.txt",
        "DATE-Scenario_7001/Roe-Rick_502/analysis/main.py",
        "manifest.csv",
    ]
    assert "[LATE +1d]" in out and "extracted -> analysis/" in out
    assert "2 file(s). Manifest:" in out
    rows = read_csv(out_dir / "manifest.csv")
    assert (out_dir / "manifest.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert [(r["student"], r["filename"], r["late"], r["late_by"]) for r in rows] == [
        ("Doe, Jane", "essay.pdf", "False", ""), ("Roe, Rick", "analysis.zip", "True", "1d")]
    assert rows[0]["due_source"] == "everyone" and rows[0]["section"] == ""

    from openpyxl import load_workbook
    wb = load_workbook(out_dir / xlsx[0])
    assert wb.sheetnames == ["Files", "By Student", "By Section", "Run Summary"]
    assert wb["Files"].max_row == 3

    # a rerun downloads nothing new
    code, out, _ = run_cli(*COMMON, "--out", str(out_dir), "--no-xlsx")
    assert "cached essay.pdf" in out and "downloaded" not in out


def test_download_by_section_flat_filtered(fake_canvas, run_cli, tmp_path):
    out_dir = tmp_path / "out"
    code, out, err = run_cli(*COMMON, "--out", str(out_dir), "--assignment", "7001",
                             "--section", "A2", "--by-section", "--flat",
                             "--no-extract", "--no-xlsx", "--tz", "America/New_York")
    assert code == 0, err
    assert tree(out_dir) == ["DATE-Scenario_7001/A2-8/Roe-Rick_502__analysis.zip",
                             "manifest.csv"]
    assert "Filtering to 2 student(s)." in out
    row = read_csv(out_dir / "manifest.csv")[0]
    assert row["section"] == "A2-8" and row["due_source"] == "section override"
    assert row["due_at"] == "2026-09-02 23:59"       # converted from UTC


def test_download_failure_is_recorded_and_exit_code_is_1(fake_canvas, run_cli, tmp_path):
    """Review finding 4: a failed file is in the manifest and the log, and the
    run does not report success."""
    openpyxl = pytest.importorskip("openpyxl")
    del fake_canvas.file_bodies["/f/1"]            # essay.pdf now answers 404
    out_dir = tmp_path / "o"
    code, out, err = run_cli(*COMMON, "--out", str(out_dir), "--assignment", "7001")
    assert code == 1
    assert "1 file(s) could not be downloaded" in err
    rows = read_csv(out_dir / "manifest.csv")
    status = {r["filename"]: r["status"] for r in rows}
    assert status["essay.pdf"].startswith("failed:")
    assert status["analysis.zip"] == "downloaded"
    assert not any(p.name == "essay.pdf" for p in out_dir.rglob("*"))
    xlsx = next(out_dir.glob("submission_log_*.xlsx"))
    files = openpyxl.load_workbook(xlsx)["Files"]
    assert files.max_row == 3


def test_manifest_keeps_rows_from_earlier_runs(fake_canvas, run_cli, tmp_path):
    """Review finding 13: a narrower rerun merges into manifest.csv."""
    out_dir = tmp_path / "o"
    run_cli(*COMMON, "--out", str(out_dir), "--no-xlsx")
    code, out, _ = run_cli(*COMMON, "--out", str(out_dir), "--no-xlsx",
                           "--student", "Doe")
    assert code == 0 and "(2 row(s) including earlier runs)" in out
    rows = read_csv(out_dir / "manifest.csv")
    assert sorted(r["filename"] for r in rows) == ["analysis.zip", "essay.pdf"]


def test_download_with_nothing_submitted(fake_canvas, run_cli, tmp_path):
    code, out, _ = run_cli(*COMMON, "--out", str(tmp_path / "o"), "--assignment", "7002",
                           "--no-xlsx")
    assert code == 0 and "No submission files found." in out
    assert not (tmp_path / "o").exists()


# ---- roster and grade files ---------------------------------------------------
def test_grade_file_instructor_prefers_teacher_over_ta(fake_canvas, run_cli, tmp_path):
    """Review finding 6: a TA listed first must not become instructor=."""
    fake_canvas.teachers.reverse()            # TA for A2-8 now comes first
    code, _, err = run_cli(*COMMON, "--make-grade-files", "--assignment", "7001",
                           "--grade-file-dir", str(tmp_path))
    assert code == 0, err
    text = (tmp_path / "A2-DATE_Grading-27-1.txt").read_text(encoding="utf-8")
    assert "instructor=Smith\n" in text


def test_roster_csv(fake_canvas, run_cli, tmp_path):
    path = tmp_path / "roster.csv"
    code, out, _ = run_cli(*COMMON, "--roster-csv", str(path))
    assert code == 0 and "3 student(s), 3 line(s)" in out
    rows = read_csv(path)
    assert [(r["Student Last Name"], r["Student First Name"], r["Instructor Last Name"],
             r["Section Name"]) for r in rows] == [
        ("De La Cruz", "Ana", "Smith", "A2-8"), ("Doe", "Jane", "Rhoades", "A1-8"),
        ("Roe", "Rick", "Smith", "A2-8")]


def test_make_grade_files(fake_canvas, run_cli, tmp_path):
    code, out, err = run_cli(*COMMON, "--make-grade-files", "--assignment", "7001",
                             "--grade-file-dir", str(tmp_path))
    assert code == 0, err
    assert tree(tmp_path) == ["A1-DATE_Grading-27-1.txt", "A2-DATE_Grading-27-1.txt"]
    text = (tmp_path / "A2-DATE_Grading-27-1.txt").read_text(encoding="utf-8")
    assert text.startswith("[ASSIGNMENT]\ntitle=DATE Scenario\nid=7001\n\n"
                           "[SECTION]\ntitle=A2-8\ninstructor=Smith\nid=12\n")
    assert text.index("De La Cruz, Ana") < text.index("Roe, Rick")
    # existing files are kept unless --force
    code, out, _ = run_cli(*COMMON, "--make-grade-files", "--assignment", "7001",
                           "--grade-file-dir", str(tmp_path))
    assert "not overwritten (use --force)" in out and "0 file(s) written" in out


# ---- posting grades -----------------------------------------------------------
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


def test_post_grades_dry_run_posts_nothing(fake_canvas, run_cli, tmp_path):
    gf = tmp_path / "A2-DATE_Grading-27-1.txt"
    gf.write_text(GRADES, encoding="utf-8")
    code, out, err = run_cli("--base-url", BASE, "--post-grades", str(gf), "--dry-run")
    assert code == 0, err
    assert "Roe, Rick (502):  grade - -> 8.5   comment already on Canvas, not re-sent" in out
    assert "De La Cruz, Ana (503):  grade - -> EXCUSED" in out
    assert "Dry run: 2 update(s) checked, nothing posted." in out
    assert fake_canvas.posted_forms == []


def test_post_grades_posts_one_bulk_request_and_verifies(fake_canvas, run_cli, tmp_path):
    gf = tmp_path / "A2-DATE_Grading-27-1.txt"
    gf.write_text(GRADES, encoding="utf-8")
    code, out, err = run_cli("--base-url", BASE, "--post-grades", str(gf), "--yes")
    assert code == 0, err
    assert fake_canvas.posted_forms == [{
        "grade_data[502][posted_grade]": "8.5",
        "grade_data[503][excuse]": "true",
        "grade_data[503][text_comment]": "Excused for\nthe field exercise.",
    }]
    assert "Verified: all 2 update(s) are on Canvas." in out
    log = list(tmp_path.glob("grade_post_log_*.csv"))
    assert len(log) == 1
    assert log[0].read_bytes().startswith(b"\xef\xbb\xbf")    # finding 13
    rows = read_csv(log[0])
    assert [(r["student"], r["grade_sent"], r["problems"]) for r in rows] == [
        ("Roe, Rick", "8.5", ""), ("De La Cruz, Ana", "EXCUSED", "")]


def test_post_grades_refuses_when_any_file_has_an_error(fake_canvas, run_cli, tmp_path):
    gf = tmp_path / "bad.txt"
    gf.write_text(GRADES.replace("id=502", "id=999"), encoding="utf-8")
    code, _, err = run_cli("--base-url", BASE, "--post-grades", str(gf), "--yes")
    assert code == 2                                        # bad input
    assert "Errors (nothing was posted):" in err and "no student in the course has id 999" in err
    assert fake_canvas.posted_forms == []


def test_post_grades_without_a_terminal_needs_yes(fake_canvas, run_cli, tmp_path, monkeypatch):
    gf = tmp_path / "g.txt"
    gf.write_text(GRADES, encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    code, _, err = run_cli("--base-url", BASE, "--post-grades", str(gf))
    assert code == 2 and "rerun with --yes" in err
    assert fake_canvas.posted_forms == []


# ---- quiz export --------------------------------------------------------------
def add_new_quiz(fake):
    fake.assignments.append({"id": 7003, "name": "Quiz 1", "is_quiz_lti_assignment": True,
                             "submission_types": ["external_tool"]})
    fake.submissions[7003] = {uid: {"user_id": uid, "workflow_state": "submitted",
                                    "submitted_at": "2026-09-01T00:00:00Z"}
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
    fake.extra[("GET", "/files/report.csv")] = (
        "Name,ID,Q1\r\nJane Doe,501,True\r\nRick Roe,502,False\r\n".encode("utf-8-sig"))


def test_export_quiz_dry_run_writes_nothing(fake_canvas, run_cli, tmp_path):
    add_new_quiz(fake_canvas)
    code, out, err = run_cli(*COMMON, "--assignment", "7003", "--export-quiz", "--dry-run",
                             "--out", str(tmp_path / "o"))
    assert code == 0, err
    assert "2 item(s); 1 converted to QTI" in out and "Dry run: nothing written" in out
    assert not (tmp_path / "o").exists()
    assert not [c for c in fake_canvas.calls if c[0] == "POST"]


def test_export_quiz_content_and_answers_by_section(fake_canvas, run_cli, tmp_path):
    add_new_quiz(fake_canvas)
    out_dir = tmp_path / "o"
    code, out, err = run_cli(*COMMON, "--assignment", "7003", "--export-quiz",
                             "--no-course-export", "--by-section", "--out", str(out_dir))
    assert code == 0, err
    quiz = out_dir / "Quiz-1_7003"
    names = ["Quiz-1_new-quiz.json", "Quiz-1_qti-report.csv", "Quiz-1_qti.zip",
             "Quiz-1_student-answers.csv"]
    assert tree(quiz) == [f"{sec}/{n}" for sec in ("A1-8", "A2-8") for n in names]
    saved = json.loads((quiz / "A1-8" / "Quiz-1_new-quiz.json").read_text(encoding="utf-8"))
    assert saved["assignment_id"] == 7003 and len(saved["items"]) == 2
    assert zipfile.is_zipfile(quiz / "A2-8" / "Quiz-1_qti.zip")
    a2 = read_csv(quiz / "A2-8" / "Quiz-1_student-answers.csv")
    assert [r["Name"] for r in a2] == ["Rick Roe"]
    assert "1 item(s) are in the JSON but not the QTI" in err
    assert not (quiz / ".quiz_export_state.json").exists()


# ---- argument checks ----------------------------------------------------------
@pytest.mark.parametrize("argv, message", [
    ([], "choose a command"),
    (["download", "--course", "100"], "--base-url is required"),
    (["download", "--base-url", BASE], "--course is required"),
    ([*COMMON, "roster", "r.csv", "--flat"], "unrecognized arguments: --flat"),
    (["organize", "x"], "required: --roster"),
    ([*COMMON, "quiz", "export"], "required: --assignment"),
    ([*COMMON, "quiz", "export", "--assignment", "1", "--uploads", "--no-answers"],
     "--uploads needs the answers report"),
    ([*COMMON, "quiz", "uploads", "--assignment", "1", "--assignment", "2"],
     "--assignment can be given only once"),
    (["download", "--base-url", "http://canvas.test", "--course", "100"],
     "must be an https:// address"),
    (["--base-url", "canvas.test", "--course", "100", "download"], "must be an https:// address"),
])
def test_argument_errors(fake_canvas, run_cli, argv, message):
    code, _, err = run_cli(*argv)
    assert code == 2 and message in err


def test_global_options_before_or_after_the_command(fake_canvas, run_cli, tmp_path):
    for argv in (["--base-url", BASE, "--course", "100", "download"],
                 ["download", "--base-url", BASE, "--course", "100"],
                 ["--base-url", BASE, "download", "--course", "100", "--tz", "UTC"]):
        code, out, _ = run_cli(*argv, "--assignment", "7002", "--no-xlsx",
                               "--out", str(tmp_path / "o"))
        assert code == 0 and "No submission files found." in out


def test_missing_token(fake_canvas, run_cli, monkeypatch):
    monkeypatch.delenv("CANVAS_API_TOKEN")
    code, _, err = run_cli(*COMMON, "--list-assignments")
    assert code == 5 and "Set the CANVAS_API_TOKEN environment variable first." in err


# ---- Canvas errors (review finding 9) ------------------------------------------
def _status(fake, method, path, code):
    from conftest import make_response
    fake.extra[(method, path)] = make_response(f"{BASE}{path}", code, {"errors": "x"})


def test_bad_token_is_one_line_not_a_traceback(fake_canvas, run_cli):
    _status(fake_canvas, "GET", "/api/v1/courses/100/assignments", 401)
    code, _, err = run_cli(*COMMON, "--list-assignments")
    assert code == 4
    assert "rejected the API token (401)" in err and "Traceback" not in err


def test_401_on_assignment_lookup_is_not_reported_as_not_found(fake_canvas, run_cli, tmp_path):
    _status(fake_canvas, "GET", "/api/v1/courses/100/assignments/7001", 401)
    code, _, err = run_cli(*COMMON, "--make-grade-files", "--assignment", "7001",
                           "--grade-file-dir", str(tmp_path))
    assert code == 4 and "not found" not in err and "401" in err


def test_404_on_assignment_lookup_still_says_not_found(fake_canvas, run_cli, tmp_path):
    code, _, err = run_cli(*COMMON, "--make-grade-files", "--assignment", "9999",
                           "--grade-file-dir", str(tmp_path))
    assert code == 2 and "Assignment 9999 not found" in err


def test_typed_errors_are_still_requests_http_errors():
    import requests
    from painter.errors import AuthFailed, NotFound, PainterError
    assert issubclass(NotFound, requests.HTTPError) and issubclass(AuthFailed, PainterError)


def test_same_named_attachments_do_not_overwrite(fake_canvas, run_cli, tmp_path):
    """Review finding 7: two essay.pdf in one folder, and a rerun is all cached."""
    fake_canvas.file_bodies["/f/3"] = b"%PDF-1.4 second draft!!"
    fake_canvas.submissions[7001][501]["attachments"].append(
        {"id": 3, "display_name": "essay.pdf", "url": "https://files.test/f/3",
         "size": len(fake_canvas.file_bodies["/f/3"])})
    out_dir = tmp_path / "o"
    argv = (*COMMON, "--out", str(out_dir), "--assignment", "7001", "--no-xlsx")
    code, _, err = run_cli(*argv)
    assert code == 0, err
    jane = out_dir / "DATE-Scenario_7001" / "Doe-Jane_501"
    assert sorted(p.name for p in jane.iterdir()) == ["essay__a1.pdf", "essay__a3.pdf"]
    assert (jane / "essay__a3.pdf").read_bytes() == b"%PDF-1.4 second draft!!"
    _, out, _ = run_cli(*argv)
    assert "downloaded" not in out
