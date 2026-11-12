import csv
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest

from painter.canvas.jobs import _load_state, _save_state
from painter.domain.assignments import assignment_folder, quiz_kind
from painter.domain.roster import Roster
from painter.qti.builder import CANVAS_META_NS, QTI_NS, QtiBuilder, _escape, _num, strip_html
from painter.qti.verify import verify_qti_zip
from painter.services.quiz_export import package_contains_quiz, write_answers
from painter.services.quiz_plan import QuizExportPlan, find_student_column
from painter.services.quiz_uploads import (
    _is_file_link, submission_quiz_session, uploads_in_results,
)
from conftest import BASE

QUIZ = {"title": "Quiz 1", "instructions": "<p>Do it</p>", "points_possible": 4,
        "quiz_settings": {"shuffle_answers": True,
                          "multiple_attempts": {"multiple_attempts_enabled": True,
                                                "attempt_limit": True, "max_attempts": 2}}}


def item(n, slug, entry, etype="Item", **extra):
    base = {"id": str(n), "position": n, "entry_type": etype, "points_possible": 1,
            "entry": dict({"title": f"Q{n}", "item_body": f"<p>Question {n} text here</p>",
                           "interaction_type_slug": slug, "feedback": {}}, **entry)}
    base.update(extra)
    return base


ITEMS = [
    item(1, "choice", {
        "interaction_data": {"choices": [
            {"id": "a", "position": 1, "item_body": "<p>Alpha</p>"},
            {"id": "b", "position": 2, "item_body": "<p>Beta</p>"}]},
        "scoring_data": {"value": "b"},
        "feedback": {"correct": "Yes", "incorrect": "No"}}),
    item(2, "true-false", {"interaction_data": {}, "scoring_data": {"value": True}}),
    item(3, "essay", {"scoring_data": {"value": "grader notes"}}),
    item(4, "numeric", {"scoring_data": {"value": [
        {"type": "marginOfError", "value": "10", "margin": "1", "margin_type": "absolute"}]}}),
    item(5, "ordering", {}),
    {"id": "6", "position": 6, "entry_type": "Bank", "points_possible": 1,
     "properties": {"sample_num": 2},
     "entry": {"title": "Pool", "item_entry_count": 9}},
]


def build():
    b = QtiBuilder(QUIZ, "gabc")
    for it in QtiBuilder.ordered(ITEMS):
        b.add(it)
    return b


def test_helpers():
    assert strip_html("<p>a &amp; <b>b</b></p>") == "a & b"
    assert _num(10) == "10.0" and _num(0.25) == "0.25"
    assert _escape("<a & b>") == "&lt;a &amp; b&gt;"


def test_ordering_puts_stimulus_questions_after_their_stimulus():
    items = [{"id": "q1", "position": 1, "stimulus_quiz_entry_id": "s"},
             {"id": "x", "position": 1},
             {"id": "s", "position": 2},
             {"id": "q2", "position": 2, "stimulus_quiz_entry_id": "s"}]
    assert [i["id"] for i in QtiBuilder.ordered(items)] == ["x", "s", "q1", "q2"]


def test_conversion_report():
    b = build()
    by_pos = {r["Position"]: r for r in b.report}
    assert [by_pos[n]["In QTI"] for n in range(1, 7)] == ["yes"] * 4 + ["no", "no"]
    assert by_pos[1]["Question Type"] == "choice"
    assert "grading notes kept in the JSON only" in by_pos[3]["Notes"]
    assert "no Classic Quizzes equivalent" in by_pos[5]["Notes"]
    assert "draws 2 question(s) at random from item bank 'Pool'" in by_pos[6]["Notes"]
    assert len(b.items) == 4


def test_package_is_valid_and_verifiable(tmp_path):
    b = build()
    path = tmp_path / "quiz_qti.zip"
    b.write_zip(path)
    verify_qti_zip(path, 4)
    with pytest.raises(IOError):
        verify_qti_zip(path, 5)
    with zipfile.ZipFile(path) as zf:
        assert sorted(zf.namelist()) == ["gabc/assessment_meta.xml", "gabc/gabc.xml",
                                         "imsmanifest.xml"]
        root = ET.fromstring(zf.read("gabc/gabc.xml"))
        meta = ET.fromstring(zf.read("gabc/assessment_meta.xml"))
    ns = {"q": QTI_NS}
    items = root.findall(".//q:item", ns)
    assert [i.get("ident") for i in items] == ["i1", "i2", "i3", "i4"]
    types = [i.find(".//q:fieldentry", ns).text for i in items]
    assert types == ["multiple_choice_question", "true_false_question",
                     "essay_question", "numerical_question"]
    # the correct choice is the second response label
    labels = [lab.get("ident") for lab in items[0].findall(".//q:response_label", ns)]
    scored = items[0].find(".//q:respcondition[q:setvar]/q:conditionvar/q:varequal", ns).text
    assert scored == labels[1]
    m = {"m": CANVAS_META_NS}
    assert meta.find("m:allowed_attempts", m).text == "2"
    assert meta.find("m:shuffle_answers", m).text == "true"


def test_quiz_kind():
    assert quiz_kind({"is_quiz_lti_assignment": True}) == "new"
    assert quiz_kind({"quiz_id": 5}) == "classic"
    assert quiz_kind({"submission_types": ["online_quiz"]}) == "classic"
    assert quiz_kind({"submission_types": ["external_tool"],
                          "external_tool_tag_attributes": {"url": "https://x.quiz-lti.y"}}) == "new"
    assert quiz_kind({"submission_types": ["online_upload"]}) is None


def test_assignment_folder_is_named_by_id(tmp_path):
    """Review finding 3: same folder in every run; same-named assignments differ."""
    a = {"id": 7001, "name": "DATE Scenario"}
    b = {"id": 7009, "name": "DATE Scenario"}
    assert assignment_folder(tmp_path, a) == tmp_path / "DATE-Scenario_7001"
    assert assignment_folder(tmp_path, b) == tmp_path / "DATE-Scenario_7009"


def test_assignment_folder_renames_one_legacy_folder(tmp_path, capsys):
    a = {"id": 7001, "name": "DATE Scenario"}
    (tmp_path / "03_DATE-Scenario" / "Doe-Jane_501").mkdir(parents=True)
    got = assignment_folder(tmp_path, a)
    assert got == tmp_path / "DATE-Scenario_7001"
    assert (got / "Doe-Jane_501").is_dir() and not (tmp_path / "03_DATE-Scenario").exists()
    assert "renamed 03_DATE-Scenario/" in capsys.readouterr().err


def test_assignment_folder_leaves_ambiguous_legacy_folders(tmp_path, capsys):
    a = {"id": 7001, "name": "DATE Scenario"}
    (tmp_path / "01_DATE-Scenario").mkdir()
    (tmp_path / "03_DATE-Scenario").mkdir()
    assert assignment_folder(tmp_path, a) == tmp_path / "DATE-Scenario_7001"
    assert (tmp_path / "01_DATE-Scenario").is_dir() and (tmp_path / "03_DATE-Scenario").is_dir()
    assert "could belong to any assignment" in capsys.readouterr().err


def roster():
    return Roster([{"id": 11, "name": "A1-8"}, {"id": 12, "name": "A2-8"}], [
        {"user_id": 501, "course_section_id": 11, "sis_user_id": "S501",
         "user": {"id": 501, "name": "Jane Doe", "sortable_name": "Doe, Jane"}},
        {"user_id": 502, "course_section_id": 12, "sis_user_id": "S502",
         "user": {"id": 502, "name": "Rick Roe", "sortable_name": "Roe, Rick"}},
    ])


def test_find_student_column_goes_by_values_not_headers():
    header = ["Anything", "Q1", "Who"]
    rows = [["x", "ans", "501"], ["y", "ans", "502"], ["z", "ans", "777"]]
    col, kind, uid_of = find_student_column(header, rows, roster())
    assert (col, kind) == (2, "Canvas user ID") and uid_of == {"501": 501, "502": 502}
    col, kind, _ = find_student_column(["n", "a"], [["Jane Doe", "1"], ["Roe, Rick", "2"]],
                                           roster())
    assert (col, kind) == (0, "name")
    assert find_student_column(["a"], [["q"], ["r"]], roster()) is None


def test_write_answers_splits_by_section(tmp_path, capsys):
    raw = tmp_path / "raw.csv"
    with open(raw, "w", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerows([["Name", "ID", "Q1"], ["Jane Doe", "501", "A"],
                                  ["Rick Roe", "502", "B"], ["Test Student", "999", "C"]])
    d1, d2 = tmp_path / "A1-8", tmp_path / "A2-8"
    plan = QuizExportPlan([d1, d2], selected={501, 502}, dir_of={501: d1, 502: d2},
                              roster=roster())
    written, notes = write_answers(raw, plan, "answers.csv")
    assert written == [d1 / "answers.csv", d2 / "answers.csv"]
    assert list(csv.reader(open(d1 / "answers.csv", encoding="utf-8-sig"))) == [
        ["Name", "ID", "Q1"], ["Jane Doe", "501", "A"]]
    assert "1 answer row(s) belong to people not on the current student roster" in notes[0]
    # no filters: the report is copied unchanged
    plain = QuizExportPlan([tmp_path / "all"])
    written, notes = write_answers(raw, plain, "answers.csv")
    assert written[0].read_bytes() == raw.read_bytes() and notes == []


def test_browser_upload_helpers():
    sub = {"url": "https://x/launch?quiz_session_id=4242&x=1"}
    assert submission_quiz_session(sub) == "4242"
    assert submission_quiz_session({"url": "nothing"}) is None
    results = [{"position": 2, "item_id": "i", "scored_data": {"value": [
        {"name": "a.pdf", "size": 3, "url": "https://s3/a"}, {"name": "no-url"}]}},
        {"scored_data": {"value": "text answer"}}, None]
    assert uploads_in_results(results) == [
        {"position": 2, "item_id": "i", "name": "a.pdf", "size": 3, "url": "https://s3/a"}]
    assert uploads_in_results({"not": "a list"}) == []


def test_package_contains_quiz(tmp_path):
    path = tmp_path / "export.imscc"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("q/q.xml", "<questestinterop><p>Question 1 text here</p></questestinterop>")
    assert package_contains_quiz(path, QUIZ, ITEMS)[0] is True
    other = tmp_path / "other.imscc"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("a.xml", "<manifest/>")
    assert package_contains_quiz(other, QUIZ, ITEMS) == (
        False, "the course export has no quiz (QTI) files")


def test_state_file_round_trip(tmp_path):
    p = tmp_path / "d" / ".state.json"
    assert _load_state(p) == {}
    _save_state(p, {"k": 1})
    assert _load_state(p) == {"k": 1} and json.loads(p.read_text()) == {"k": 1}


def test_file_link_check_rejects_lookalike_hosts():
    """Review finding 2."""
    host = BASE.split("//")[1]
    assert not _is_file_link("https://instructure.evil.example/x", host)
    assert not _is_file_link("http://10.0.0.5/files/1", host)
    assert not _is_file_link("https://evil.example/files/1", host)
    assert not _is_file_link("https://x.inscloudgate.net.evil.example/a", host)
    assert not _is_file_link("https://user@canvas.test/a", host)
    assert not _is_file_link("https://canvas.test:8443/a", host)
    assert not _is_file_link(f"http://{host}/files/9", host)        # token over http
    assert not _is_file_link("https://192.168.1.1/a.pdf", host)


def test_file_link_check_accepts_canvas_and_instructure_stores():
    host = BASE.split("//")[1]
    assert _is_file_link(f"{BASE}/files/9/download", host)
    assert _is_file_link("https://inst-fs-iad-prod.inscloudgate.net/files/abc", host)
    assert _is_file_link("https://school.quiz-lti-iad-prod.instructure.com/x", host)
    assert _is_file_link("https://bucket.s3.amazonaws.com/a.pdf?sig=1", host)


def test_quiz_report_without_job_id_is_not_reposted(fake_canvas, tmp_path):
    """Review finding 1: a 2xx with no id must not trigger another POST."""
    from painter.canvas.client import Canvas
    from painter.services.quiz_export import run_quiz_report
    path = "/api/quiz/v1/courses/100/quizzes/7001/reports"
    fake_canvas.extra[("POST", path)] = {}
    canvas = Canvas(BASE, "t")
    with pytest.raises(RuntimeError, match="no job id"):
        run_quiz_report(canvas, 100, 7001, tmp_path / ".state.json",
                        tmp_path / "r.csv", timeout=5)
    assert sum(1 for m, p, _ in fake_canvas.calls if m == "POST" and p == path) == 1
