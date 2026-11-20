import pytest

from painter.domain.matching import name_matches
from painter.errors import InvalidInput
from painter.domain.roster import Roster, instructor_label
from painter.services.grade_files import (
    GradeEntry, GradeFileError, grade_file_name, parse_grade_file, parse_term_name,
    render_grade_file, section_prefix, BASE_MAX, Naming, base_name, name_section_files,
    course_lead, section_words,
)
from painter.services.grading import (
    PlannedGrade, grade_fields, resolve_grade_entry, verify_posted,
)

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
    assert parse_term_name("AY27-1") == ("27", "1")
    assert parse_term_name("AY 2027 Term 2") == ("27", "2")
    assert parse_term_name("2026-2027 Semester 1") == ("27", "1")
    assert parse_term_name("Fall 2026") is None
    assert parse_term_name(None) is None


def test_file_naming():
    assert section_prefix("A1-8") == "A1"
    assert section_prefix("A1") == "A1"
    assert section_prefix("A1-8", "full") == "A1-8"
    assert section_prefix("A1-8", "instructor", "Rhoades") == "A1-Rhoades"
    assert section_prefix("A1-8", "instructor", "") == "A1"
    assert grade_file_name("A1", "DATE", "27", "1") == "A1-DATE-27-1.txt"
    assert grade_file_name("A1", "DATE") == "A1-DATE.txt"
    assert grade_file_name("A1", "DATE", "27", None) == "A1-DATE.txt"
    with pytest.raises(InvalidInput):
        section_prefix("A1", "tiny")


def test_base_name_is_safe_and_short():
    assert base_name("Lab 3: Loops / Lists?") == "Lab-3-Loops-Lists"
    assert len(base_name("x" * 200)) == BASE_MAX


def test_section_names_never_clash():
    names, notes = name_section_files(
        [(2, "A2-9", "Lee"), (1, "A2-8", "Lee"), (3, "a2", "Kim")], "DATE", Naming("short"))
    # every section that shared "A2" gets the longer name, not just the later ones
    assert names == {1: "A2-8-DATE.txt", 2: "A2-9-DATE.txt", 3: "a2-DATE.txt"}
    names, _ = name_section_files([(1, "A2", ""), (2, "a2", "")], "DATE", Naming("short"))
    assert names == {1: "A2-1-DATE.txt", 2: "a2-2-DATE.txt"}           # last resort: the id
    assert set(notes) == {1, 2, 3}
    names, _ = name_section_files([(1, "A1-8", "Lee"), (2, "A1-9", "Lee")], "Q",
                                  Naming("instructor", "27", "1"))
    assert names == {1: "A1-8-Lee-Q-27-1.txt", 2: "A1-9-Lee-Q-27-1.txt"}


# Section names as West Point's Canvas writes them: course, period, section, instructor.
REAL = [(27429, "AI105    A1 5  - HICKS, M", "Hicks"),
        (27425, "AI105    A1 8  - RHOADES, H", "Rhoades"),
        (27440, "AI105    A2 8  - RHOADES, H", "Rhoades"),
        (27455, "AI105    B1 8  - RHOADES, H", "Rhoades"),
        (27469, "AI105    B2 8  - RHOADES, H", "Rhoades")]


def test_course_code_and_instructor_are_not_the_section():
    assert section_words("AI105    A1 8  - RHOADES, H") == ["A1", "8"]
    assert section_words("A1-8") == ["A1", "8"]
    assert section_words("X1 3 - Lee", lead="X1") == ["3"]
    assert section_prefix("AI105    A1 8  - RHOADES, H") == "A1"
    assert section_prefix("AI105    A1 8  - RHOADES, H", "full") == "A1-8"
    assert section_prefix("AI105    A1 8  - RHOADES, H", "instructor", "Rhoades") == \
        "A1-Rhoades"
    assert course_lead([n for _, n, _ in REAL]) == "AI105"
    assert course_lead(["A1-8", "A2-8"]) == ""


@pytest.mark.parametrize("style, want", [
    ("short", ["A2-Build.txt", "B1-Build.txt", "B2-Build.txt"]),
    ("instructor", ["A2-Rhoades-Build.txt", "B1-Rhoades-Build.txt", "B2-Rhoades-Build.txt"]),
    ("full", ["A2-8-Build.txt", "B1-8-Build.txt", "B2-8-Build.txt"]),
])
def test_one_instructors_sections_all_named_alike(style, want):
    """The first file is named like the rest (the bug: it came out AI105-Build)."""
    names, notes = name_section_files(REAL[2:], "Build", Naming(style), "AI105")
    assert sorted(names.values()) == want and not notes


def test_shared_period_gives_every_section_the_longer_name():
    names, notes = name_section_files(REAL, "Build", Naming("short"), "AI105")
    assert names[27429] == "A1-5-Build.txt" and names[27425] == "A1-8-Build.txt"
    assert names[27440] == "A2-Build.txt" and set(notes) == {27429, 27425}
    names, _ = name_section_files(REAL, "Build", Naming("instructor"), "AI105")
    assert names[27429] == "A1-Hicks-Build.txt" and names[27425] == "A1-Rhoades-Build.txt"


def test_instructor_label():
    assert instructor_label({"user": {"sortable_name": "Rhoades, Hunter"}}) == "Rhoades"
    assert instructor_label({"user": {"name": "Hunter Rhoades"}}) == "Rhoades"
    assert instructor_label({}) == ""


def test_render_then_parse_round_trip(tmp_path):
    text = render_grade_file(
        {"id": 7001, "name": "DATE Scenario"}, "DATE", {"id": 11, "name": "A1-8"},
        "Rhoades", [{"id": 501, "sortable_name": "Doe, Jane"}])
    assert text.splitlines()[:3] == ["[ASSIGNMENT]", "title=DATE Scenario", "id=7001"]
    assert "[STUDENT]\nname=Doe, Jane\nid=501\ngrade=\ncomments=\n" in text
    gf = parse_grade_file(write(tmp_path, text))
    assert (gf.assignment_id, gf.section_id, gf.instructor) == (7001, 11, "Rhoades")
    assert gf.entries == [] and gf.blank_entries == 1


def test_render_without_assignment_leaves_title_blank():
    """Review finding 14."""
    text = render_grade_file(None, "DATE", {"id": 11, "name": "A1-8"}, "Rhoades", [])
    assert text.splitlines()[:3] == ["[ASSIGNMENT]", "title=", "id="]


def test_parse_grade_file(tmp_path):
    gf = parse_grade_file(write(tmp_path, GRADE_FILE))
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
    with pytest.raises(GradeFileError) as exc:
        parse_grade_file(write(tmp_path, text))
    assert message in str(exc.value)


def entry(grade="", comments=""):
    return GradeEntry(line=1, name="Doe, Jane", id="501", grade=grade, comments=comments)


def test_grade_fields_by_grading_type():
    points = {"grading_type": "points", "points_possible": 10}
    assert grade_fields(entry("9"), points) == ({"posted_grade": "9"}, [])
    assert grade_fields(entry("85%"), points) == ({"posted_grade": "85%"}, [])
    assert grade_fields(entry("EX"), points) == ({"excuse": "true"}, [])
    assert grade_fields(entry("", "Nice"), points) == ({"text_comment": "Nice"}, [])
    fields, warnings = grade_fields(entry("11"), points)
    assert fields == {"posted_grade": "11"} and "above points possible (10)" in warnings[0]
    assert "negative" in grade_fields(entry("-1"), points)[1][0]
    with pytest.raises(ValueError):
        grade_fields(entry("A-"), points)
    assert grade_fields(entry("Complete"), {"grading_type": "pass_fail"})[0] == {
        "posted_grade": "complete"}
    with pytest.raises(ValueError):
        grade_fields(entry("9"), {"grading_type": "pass_fail"})
    with pytest.raises(ValueError):
        grade_fields(entry("9"), {"grading_type": "not_graded"})
    assert grade_fields(entry("A-"), {"grading_type": "letter_grade"})[0] == {
        "posted_grade": "A-"}


def test_name_matching():
    user = {"name": "Jane Q Doe", "sortable_name": "Doe, Jane Q"}
    assert name_matches("Jane Doe", user)
    assert name_matches("Doe, Jane", user)
    assert not name_matches("John Doe", user)
    assert not name_matches("", user)


def test_resolve_grade_entry():
    roster = Roster([{"id": 11, "name": "A1-8"}, {"id": 12, "name": "A2-8"}], [
        {"user_id": 501, "course_section_id": 11, "sis_user_id": "S501",
         "user": {"id": 501, "name": "Jane Doe", "sortable_name": "Doe, Jane"}},
        {"user_id": 504, "course_section_id": 12,
         "user": {"id": 504, "name": "Jane Doe", "sortable_name": "Doe, Jane"}},
    ])
    E = GradeEntry
    assert resolve_grade_entry(roster, E(1, "Doe, Jane", "501", "9", ""), None)["id"] == 501
    assert resolve_grade_entry(roster, E(1, "", "S501", "9", ""), None)["id"] == 501
    assert resolve_grade_entry(roster, E(1, "Jane Doe", "", "9", ""), 12)["id"] == 504
    for bad in (E(1, "Rick Roe", "501", "9", ""),      # id and name disagree
                E(1, "", "999", "9", ""),               # unknown id
                E(1, "Jane Doe", "", "9", ""),          # ambiguous without a section
                E(1, "No Body", "", "9", "")):
        with pytest.raises(LookupError):
            resolve_grade_entry(roster, bad, None)


def test_verify_posted():
    it = PlannedGrade(entry=entry("9", "Nice"), user_id=501, student="Doe, Jane",
                          fields={"posted_grade": "9", "text_comment": "Nice  work"},
                          grade_before="")
    good = {"entered_grade": "9", "entered_score": 9.0,
            "submission_comments": [{"comment": "Nice work"}]}
    assert verify_posted(it, good, "points") == []
    assert verify_posted(it, None, "points") == ["submission not found after posting"]
    bad = {"entered_grade": "8", "entered_score": 8.0, "submission_comments": []}
    assert verify_posted(it, bad, "points") == ["score is 8.0, expected 9", "comment not found"]


def test_same_grade_compares_numbers_as_numbers():
    """Review finding 17."""
    from painter.services.grading import _same_grade
    assert _same_grade("9", "9.0") and _same_grade("90%", "90.00%")
    assert _same_grade("a-", "A-") and _same_grade("EXCUSED", "excused")
    assert not _same_grade("9", "8.5") and not _same_grade("9", "9%")
    assert not _same_grade("B", "B+")
