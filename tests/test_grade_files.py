import pytest

import canvas_fetch_submissions as cfs

GRADE_FILE = """\
[ASSIGNMENT]
title=DATE Scenario
id=7001

[SECTION]
title=A1-8
instructor=Rhoades
id=11

[STUDENT]
name=Doe, Jane
id=501
grade=9
comments=Clear analysis. Tighten the
  recommendation section next time.

[STUDENT]
name=Roe, Rick
id=502
grade=
comments=

[STUDENT]
name=
id=
grade=
comments=
"""


def write(tmp_path, text, name="A1-DATE_Grading-27-1.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_term_names():
    assert cfs.parse_term_name("AY27-1") == ("27", "1")
    assert cfs.parse_term_name("AY 2027 Term 2") == ("27", "2")
    assert cfs.parse_term_name("2026-2027 Semester 1") == ("27", "1")
    assert cfs.parse_term_name("Fall 2026") is None
    assert cfs.parse_term_name(None) is None


def test_file_naming():
    assert cfs.section_prefix("A1-8") == "A1"
    assert cfs.section_prefix("A1") == "A1"
    assert cfs.grade_file_name("A1-8", "DATE", "27", "1") == "A1-DATE_Grading-27-1.txt"


def test_instructor_label():
    assert cfs.instructor_label({"user": {"sortable_name": "Rhoades, Hunter"}}) == "Rhoades"
    assert cfs.instructor_label({"user": {"name": "Hunter Rhoades"}}) == "Rhoades"
    assert cfs.instructor_label({}) == ""


def test_render_then_parse_round_trip(tmp_path):
    text = cfs.render_grade_file(
        {"id": 7001, "name": "DATE Scenario"}, "DATE", {"id": 11, "name": "A1-8"},
        "Rhoades", [{"id": 501, "sortable_name": "Doe, Jane"}])
    assert text.splitlines()[:3] == ["[ASSIGNMENT]", "title=DATE Scenario", "id=7001"]
    assert "[STUDENT]\nname=Doe, Jane\nid=501\ngrade=\ncomments=\n" in text
    gf = cfs.parse_grade_file(write(tmp_path, text))
    assert (gf.assignment_id, gf.section_id, gf.instructor) == (7001, 11, "Rhoades")
    assert gf.entries == [] and gf.blank_entries == 1


def test_parse_grade_file(tmp_path):
    gf = cfs.parse_grade_file(write(tmp_path, GRADE_FILE))
    assert gf.assignment_title == "DATE Scenario" and gf.section_title == "A1-8"
    assert len(gf.entries) == 1 and gf.blank_entries == 1
    e = gf.entries[0]
    assert (e.name, e.id, e.grade) == ("Doe, Jane", "501", "9")
    assert e.comments == "Clear analysis. Tighten the\nrecommendation section next time."


@pytest.mark.parametrize("text, message", [
    ("stray\n[ASSIGNMENT]\nid=1\n", "text before the first [BLOCK] header"),
    ("[HOMEWORK]\n", "unknown block [HOMEWORK]"),
    ("[ASSIGNMENT]\nid=1\nid=2\n", "'id' appears twice"),
    ("[ASSIGNMENT]\nid=1\nwhat is this\n", "unexpected line"),
    ("[ASSIGNMENT]\ntitle=x\n", "[ASSIGNMENT] needs id="),
    ("[ASSIGNMENT]\nid=abc\n", "is not a number"),
    ("[SECTION]\nid=1\n", "expected one [ASSIGNMENT] block, found 0"),
    ("[ASSIGNMENT]\nid=1\n[STUDENT]\ngrade=5\n", "grade or comment but no name or id"),
])
def test_parse_errors(tmp_path, text, message):
    with pytest.raises(cfs.GradeFileError) as exc:
        cfs.parse_grade_file(write(tmp_path, text))
    assert message in str(exc.value)


def entry(grade="", comments=""):
    return cfs.GradeEntry(line=1, name="Doe, Jane", id="501", grade=grade, comments=comments)


def test_grade_fields_by_grading_type():
    points = {"grading_type": "points", "points_possible": 10}
    assert cfs.grade_fields(entry("9"), points) == ({"posted_grade": "9"}, [])
    assert cfs.grade_fields(entry("85%"), points) == ({"posted_grade": "85%"}, [])
    assert cfs.grade_fields(entry("EX"), points) == ({"excuse": "true"}, [])
    assert cfs.grade_fields(entry("", "Nice"), points) == ({"text_comment": "Nice"}, [])
    fields, warnings = cfs.grade_fields(entry("11"), points)
    assert fields == {"posted_grade": "11"} and "above points possible (10)" in warnings[0]
    assert "negative" in cfs.grade_fields(entry("-1"), points)[1][0]
    with pytest.raises(ValueError):
        cfs.grade_fields(entry("A-"), points)
    assert cfs.grade_fields(entry("Complete"), {"grading_type": "pass_fail"})[0] == {
        "posted_grade": "complete"}
    with pytest.raises(ValueError):
        cfs.grade_fields(entry("9"), {"grading_type": "pass_fail"})
    with pytest.raises(ValueError):
        cfs.grade_fields(entry("9"), {"grading_type": "not_graded"})
    assert cfs.grade_fields(entry("A-"), {"grading_type": "letter_grade"})[0] == {
        "posted_grade": "A-"}


def test_name_matching():
    user = {"name": "Jane Q Doe", "sortable_name": "Doe, Jane Q"}
    assert cfs.name_matches("Jane Doe", user)
    assert cfs.name_matches("Doe, Jane", user)
    assert not cfs.name_matches("John Doe", user)
    assert not cfs.name_matches("", user)


def test_resolve_grade_entry():
    roster = cfs.Roster([{"id": 11, "name": "A1-8"}, {"id": 12, "name": "A2-8"}], [
        {"user_id": 501, "course_section_id": 11, "sis_user_id": "S501",
         "user": {"id": 501, "name": "Jane Doe", "sortable_name": "Doe, Jane"}},
        {"user_id": 504, "course_section_id": 12,
         "user": {"id": 504, "name": "Jane Doe", "sortable_name": "Doe, Jane"}},
    ])
    E = cfs.GradeEntry
    assert cfs.resolve_grade_entry(roster, E(1, "Doe, Jane", "501", "9", ""), None)["id"] == 501
    assert cfs.resolve_grade_entry(roster, E(1, "", "S501", "9", ""), None)["id"] == 501
    assert cfs.resolve_grade_entry(roster, E(1, "Jane Doe", "", "9", ""), 12)["id"] == 504
    for bad in (E(1, "Rick Roe", "501", "9", ""),      # id and name disagree
                E(1, "", "999", "9", ""),               # unknown id
                E(1, "Jane Doe", "", "9", ""),          # ambiguous without a section
                E(1, "No Body", "", "9", "")):
        with pytest.raises(LookupError):
            cfs.resolve_grade_entry(roster, bad, None)


def test_verify_posted():
    it = cfs.PlannedGrade(entry=entry("9", "Nice"), user_id=501, student="Doe, Jane",
                          fields={"posted_grade": "9", "text_comment": "Nice  work"},
                          grade_before="")
    good = {"entered_grade": "9", "entered_score": 9.0,
            "submission_comments": [{"comment": "Nice work"}]}
    assert cfs.verify_posted(it, good, "points") == []
    assert cfs.verify_posted(it, None, "points") == ["submission not found after posting"]
    bad = {"entered_grade": "8", "entered_score": 8.0, "submission_comments": []}
    assert cfs.verify_posted(it, bad, "points") == ["score is 8.0, expected 9", "comment not found"]
