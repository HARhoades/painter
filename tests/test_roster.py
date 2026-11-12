from types import SimpleNamespace

import pytest

from painter.domain.roster import (
    Roster, match_section, resolve_sections, resolve_students, select_students,
)
from painter.services.submissions import collect_attachments

SECTIONS = [
    {"id": 11, "name": "A1-8", "sis_section_id": "SIS-A1"},
    {"id": 12, "name": "A2-8", "sis_section_id": None},
    {"id": 13, "name": "Lab 002"},
]


def enrollment(uid, sid, sortable, sis=None, login=None):
    first = sortable.split(", ")[1]
    last = sortable.split(", ")[0]
    user = {"id": uid, "name": f"{first} {last}", "sortable_name": sortable}
    if login:
        user["login_id"] = login
    return {"user_id": uid, "course_section_id": sid, "sis_user_id": sis, "user": user}


@pytest.fixture
def roster():
    return Roster(SECTIONS, [
        enrollment(501, 11, "Doe, Jane", sis="S501", login="jdoe2"),
        enrollment(502, 12, "Roe, Rick"),
        enrollment(503, 12, "Nguyen, Ana"),
        enrollment(503, 13, "Nguyen, Ana"),
        {"user_id": None},
    ])


def test_roster_joins_sections_and_enrollments(roster):
    assert set(roster.users) == {501, 502, 503}
    assert roster.users[501]["sis_user_id"] == "S501"
    assert roster.users[501]["login_id"] == "jdoe2"
    assert roster.sections_of_user[503] == [12, 13]
    assert roster.users_of_section[12] == {502, 503}
    assert roster.section_names(503) == ["A2-8", "Lab 002"]
    assert roster.section_names(999) == []


def test_primary_section_prefers_a_selected_section(roster):
    assert roster.primary_section(503, None)["id"] == 12
    assert roster.primary_section(503, {13})["id"] == 13
    assert roster.primary_section(503, {11})["id"] == 12
    assert roster.primary_section(999, None) is None


def test_match_section():
    assert match_section("11", SECTIONS[0])
    assert match_section("SIS-A1", SECTIONS[0])
    assert match_section("a1", SECTIONS[0])
    assert not match_section("A2", SECTIONS[0])


def test_resolve_sections_and_typos(roster):
    assert resolve_sections(roster, ["12", "lab"]) == {12, 13}
    assert resolve_sections(roster, ["-8"]) == {11, 12}
    with pytest.raises(SystemExit) as exc:
        resolve_sections(roster, ["nope"])
    assert "No section match for: 'nope'" in str(exc.value)


def test_match_and_resolve_students(roster):
    assert resolve_students(roster, ["501"]) == {501}
    assert resolve_students(roster, ["S501"]) == {501}
    assert resolve_students(roster, ["jdoe2"]) == {501}
    assert resolve_students(roster, ["nguyen"]) == {503}
    assert resolve_students(roster, ["Rick Roe"]) == {502}
    with pytest.raises(SystemExit):
        resolve_students(roster, ["nobody"])


def test_select_students_is_a_union(roster):
    none = SimpleNamespace(student=None, section=None)
    assert select_students(roster, none) == (None, set())
    both = SimpleNamespace(student=["501"], section=["Lab 002"])
    assert select_students(roster, both) == ({501, 503}, {13})


def test_collect_attachments_deduplicates_and_reads_history():
    sub = {"attachments": [{"id": 1}, {"id": 2}],
           "submission_history": [{"attachments": [{"id": 2}, {"id": 3}]}]}
    assert [a["id"] for a in collect_attachments(sub, False)] == [1, 2]
    assert [a["id"] for a in collect_attachments(sub, True)] == [1, 2, 3]
