"""Editing grade files from the window: only grade= and comments= lines change."""
import pytest

from painter.services.grade_edits import (
    Edit, EditRefused, FileChanged, Stamp, grade_warnings, refusal, save_edits,
)
from painter.services.grade_files import GradeFileError, parse_grade_file

TEXT = """[ASSIGNMENT]
title=DATE Scenario
id=7001

[SECTION]
title=A1-8
instructor=Rhoades
id=11

[STUDENT]
name=Doe, Jane
id=501
grade=88
comments=Good work.
    Second line.

[STUDENT]
name=Roe, Rick
id=502
grade=
comments=

[STUDENT]
name=Poe, Pat
id=503
"""


def write(tmp_path, text=TEXT, name="A1-DATE.txt", **kw):
    p = tmp_path / name
    p.write_text(text, encoding=kw.get("encoding", "utf-8"), newline=kw.get("newline"))
    return p


def test_every_named_student_is_listed_filled_or_not(tmp_path):
    gf = parse_grade_file(write(tmp_path))
    assert [s.id for s in gf.students] == ["501", "502", "503"]
    assert [s.blank for s in gf.students] == [False, True, True]
    assert len(gf.entries) == 1 and gf.blank_entries == 2       # what posting uses


def test_only_the_edited_lines_change(tmp_path):
    p = write(tmp_path)
    gf = save_edits(p, [Edit("id:502", "91", "Nice.\nSee me\n\nabout lab 3.")], Stamp.of(p))
    new = p.read_text(encoding="utf-8")
    before, after = TEXT.splitlines(), new.splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert after[:19] == before[:19]                    # everything above Roe untouched
    assert "grade=91" in after and "comments=Nice." in after and "    about lab 3." in after
    s = {x.id: x for x in gf.students}
    assert s["502"].grade == "91" and s["502"].comments == "Nice.\nSee me\n\nabout lab 3."
    assert s["501"].comments == "Good work.\nSecond line."
    assert changed and min(changed) >= 19


def test_missing_fields_are_added_to_the_block(tmp_path):
    p = write(tmp_path)
    gf = save_edits(p, [Edit("id:503", "75", "Late.")], Stamp.of(p))
    s = {x.id: x for x in gf.students}["503"]
    assert (s.grade, s.comments) == ("75", "Late.")


def test_a_multi_line_comment_can_be_shortened(tmp_path):
    p = write(tmp_path)
    save_edits(p, [Edit("id:501", "90", "One line now.")], Stamp.of(p))
    text = p.read_text(encoding="utf-8")
    assert "Second line." not in text and "comments=One line now.\n\n[STUDENT]" in text


def test_windows_line_endings_and_bom_are_kept(tmp_path):
    p = tmp_path / "w.txt"
    p.write_bytes(("﻿" + TEXT).replace("\n", "\r\n").encode("utf-8"))
    save_edits(p, [Edit("id:502", "70", "a\nb")], Stamp.of(p))
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\n" not in raw.replace(b"\r\n", b"")
    assert {x.id: x.comments for x in parse_grade_file(p).students}["502"] == "a\nb"


@pytest.mark.parametrize("comment", ["fine\n[STUDENT]", "ok\ngrade=100", "ok\n  ID = 9",
                                     "ok\nComments=again", "x\n[ section ]"])
def test_lines_that_would_inject_data_are_refused(tmp_path, comment):
    p = write(tmp_path)
    assert refusal("1", comment)
    with pytest.raises(EditRefused):
        save_edits(p, [Edit("id:502", "1", comment)], Stamp.of(p))
    assert p.read_text(encoding="utf-8") == TEXT                 # nothing written


def test_harmless_lines_are_allowed():
    assert refusal("A-", "grade is good\nidentity = fine\n[draft] notes") == ""
    assert refusal("1\n2", "") == "A grade must fit on one line."


def test_a_file_changed_elsewhere_is_not_overwritten(tmp_path):
    p = write(tmp_path)
    stamp = Stamp.of(p)
    p.write_text(TEXT.replace("grade=88", "grade=89"), encoding="utf-8")
    import os
    os.utime(p, ns=(stamp.mtime_ns + 5_000_000_000,) * 2)
    with pytest.raises(FileChanged):
        save_edits(p, [Edit("id:502", "91", "")], stamp)
    gf = save_edits(p, [Edit("id:502", "91", "")], None)         # overwrite: keep theirs too
    s = {x.id: x.grade for x in gf.students}
    assert s == {"501": "89", "502": "91", "503": ""}


def test_a_student_gone_from_the_file_is_refused(tmp_path):
    p = write(tmp_path)
    with pytest.raises(EditRefused, match="no longer"):
        save_edits(p, [Edit("id:999", "1", "")], Stamp.of(p))


def test_the_same_student_twice_is_refused(tmp_path):
    p = write(tmp_path, TEXT + "\n[STUDENT]\nname=Doe, Jane\nid=501\n")
    with pytest.raises(GradeFileError, match="twice"):
        save_edits(p, [Edit("id:501", "1", "")], Stamp.of(p))


def test_no_part_file_is_left_behind(tmp_path):
    p = write(tmp_path)
    save_edits(p, [Edit("id:502", "1", "")], Stamp.of(p))
    assert sorted(x.name for x in tmp_path.iterdir()) == ["A1-DATE.txt"]


def test_basic_grade_checks():
    assert grade_warnings("") == [] and grade_warnings("95") == []
    assert grade_warnings("95%") == [] and grade_warnings("A-") == []
    assert grade_warnings("complete") == [] and grade_warnings("EX") == []
    assert grade_warnings("abc%") and grade_warnings("9o") and grade_warnings("-3")
    assert grade_warnings("9 5")
