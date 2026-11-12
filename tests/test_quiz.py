import csv
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest

import canvas_fetch_submissions as cfs
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
    b = cfs.QtiBuilder(QUIZ, "gabc")
    for it in cfs.QtiBuilder.ordered(ITEMS):
        b.add(it)
    return b


def test_helpers():
    assert cfs.strip_html("<p>a &amp; <b>b</b></p>") == "a & b"
    assert cfs._num(10) == "10.0" and cfs._num(0.25) == "0.25"
    assert cfs._escape("<a & b>") == "&lt;a &amp; b&gt;"


def test_ordering_puts_stimulus_questions_after_their_stimulus():
    items = [{"id": "q1", "position": 1, "stimulus_quiz_entry_id": "s"},
             {"id": "x", "position": 1},
             {"id": "s", "position": 2},
             {"id": "q2", "position": 2, "stimulus_quiz_entry_id": "s"}]
    assert [i["id"] for i in cfs.QtiBuilder.ordered(items)] == ["x", "s", "q1", "q2"]


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
    cfs.verify_qti_zip(path, 4)
    with pytest.raises(IOError):
        cfs.verify_qti_zip(path, 5)
    with zipfile.ZipFile(path) as zf:
        assert sorted(zf.namelist()) == ["gabc/assessment_meta.xml", "gabc/gabc.xml",
                                         "imsmanifest.xml"]
        root = ET.fromstring(zf.read("gabc/gabc.xml"))
        meta = ET.fromstring(zf.read("gabc/assessment_meta.xml"))
    ns = {"q": cfs.QTI_NS}
    items = root.findall(".//q:item", ns)
    assert [i.get("ident") for i in items] == ["i1", "i2", "i3", "i4"]
    types = [i.find(".//q:fieldentry", ns).text for i in items]
    assert types == ["multiple_choice_question", "true_false_question",
                     "essay_question", "numerical_question"]
    # the correct choice is the second response label
    labels = [lab.get("ident") for lab in items[0].findall(".//q:response_label", ns)]
    scored = items[0].find(".//q:respcondition[q:setvar]/q:conditionvar/q:varequal", ns).text
    assert scored == labels[1]
    m = {"m": cfs.CANVAS_META_NS}
    assert meta.find("m:allowed_attempts", m).text == "2"
    assert meta.find("m:shuffle_answers", m).text == "true"


def test_quiz_kind():
    assert cfs.quiz_kind({"is_quiz_lti_assignment": True}) == "new"
    assert cfs.quiz_kind({"quiz_id": 5}) == "classic"
    assert cfs.quiz_kind({"submission_types": ["online_quiz"]}) == "classic"
    assert cfs.quiz_kind({"submission_types": ["external_tool"],
                          "external_tool_tag_attributes": {"url": "https://x.quiz-lti.y"}}) == "new"
    assert cfs.quiz_kind({"submission_types": ["online_upload"]}) is None


def test_assignment_folder_reuses_an_existing_numbered_folder(tmp_path):
    a = {"id": 7001, "name": "DATE Scenario"}
    assert cfs.assignment_folder(tmp_path, a) == tmp_path / "01_DATE-Scenario"
    (tmp_path / "03_DATE-Scenario").mkdir()
    assert cfs.assignment_folder(tmp_path, a) == tmp_path / "03_DATE-Scenario"


def roster():
    return cfs.Roster([{"id": 11, "name": "A1-8"}, {"id": 12, "name": "A2-8"}], [
        {"user_id": 501, "course_section_id": 11, "sis_user_id": "S501",
         "user": {"id": 501, "name": "Jane Doe", "sortable_name": "Doe, Jane"}},
        {"user_id": 502, "course_section_id": 12, "sis_user_id": "S502",
         "user": {"id": 502, "name": "Rick Roe", "sortable_name": "Roe, Rick"}},
    ])


def test_find_student_column_goes_by_values_not_headers():
    header = ["Anything", "Q1", "Who"]
    rows = [["x", "ans", "501"], ["y", "ans", "502"], ["z", "ans", "777"]]
    col, kind, uid_of = cfs.find_student_column(header, rows, roster())
    assert (col, kind) == (2, "Canvas user ID") and uid_of == {"501": 501, "502": 502}
    col, kind, _ = cfs.find_student_column(["n", "a"], [["Jane Doe", "1"], ["Roe, Rick", "2"]],
                                           roster())
    assert (col, kind) == (0, "name")
    assert cfs.find_student_column(["a"], [["q"], ["r"]], roster()) is None


def test_write_answers_splits_by_section(tmp_path, capsys):
    raw = tmp_path / "raw.csv"
    with open(raw, "w", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerows([["Name", "ID", "Q1"], ["Jane Doe", "501", "A"],
                                  ["Rick Roe", "502", "B"], ["Test Student", "999", "C"]])
    d1, d2 = tmp_path / "A1-8", tmp_path / "A2-8"
    plan = cfs.QuizExportPlan([d1, d2], selected={501, 502}, dir_of={501: d1, 502: d2},
                              roster=roster())
    written, notes = cfs.write_answers(raw, plan, "answers.csv")
    assert written == [d1 / "answers.csv", d2 / "answers.csv"]
    assert list(csv.reader(open(d1 / "answers.csv", encoding="utf-8-sig"))) == [
        ["Name", "ID", "Q1"], ["Jane Doe", "501", "A"]]
    assert "1 answer row(s) belong to people not on the current student roster" in notes[0]
    # no filters: the report is copied unchanged
    plain = cfs.QuizExportPlan([tmp_path / "all"])
    written, notes = cfs.write_answers(raw, plain, "answers.csv")
    assert written[0].read_bytes() == raw.read_bytes() and notes == []


def test_browser_upload_helpers():
    sub = {"url": "https://x/launch?quiz_session_id=4242&x=1"}
    assert cfs.submission_quiz_session(sub) == "4242"
    assert cfs.submission_quiz_session({"url": "nothing"}) is None
    results = [{"position": 2, "item_id": "i", "scored_data": {"value": [
        {"name": "a.pdf", "size": 3, "url": "https://s3/a"}, {"name": "no-url"}]}},
        {"scored_data": {"value": "text answer"}}, None]
    assert cfs.uploads_in_results(results) == [
        {"position": 2, "item_id": "i", "name": "a.pdf", "size": 3, "url": "https://s3/a"}]
    assert cfs.uploads_in_results({"not": "a list"}) == []


def test_package_contains_quiz(tmp_path):
    path = tmp_path / "export.imscc"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("q/q.xml", "<questestinterop><p>Question 1 text here</p></questestinterop>")
    assert cfs.package_contains_quiz(path, QUIZ, ITEMS)[0] is True
    other = tmp_path / "other.imscc"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("a.xml", "<manifest/>")
    assert cfs.package_contains_quiz(other, QUIZ, ITEMS) == (
        False, "the course export has no quiz (QTI) files")


def test_state_file_round_trip(tmp_path):
    p = tmp_path / "d" / ".state.json"
    assert cfs._load_state(p) == {}
    cfs._save_state(p, {"k": 1})
    assert cfs._load_state(p) == {"k": 1} and json.loads(p.read_text()) == {"k": 1}


@pytest.mark.xfail(strict=True, reason="review finding 2: link check accepts hosts that "
                   "merely contain a trusted name, and any host with /files/<n>")
def test_file_link_check_rejects_lookalike_hosts():
    host = BASE.split("//")[1]
    assert not cfs._is_file_link("https://instructure.evil.example/x", host)
    assert not cfs._is_file_link("http://10.0.0.5/files/1", host)
