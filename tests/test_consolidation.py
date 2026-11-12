"""Phase 4: each duplicated piece of logic has one home (review table 3.3).

Each test reads the package source as Python tokens (comments and strings
ignored) and checks that a pattern occurs only in the module that owns it.
"""
from __future__ import annotations

import io
from pathlib import Path
import tokenize

PKG = Path(__file__).resolve().parent.parent / "painter"


def _code_tokens(path: Path):
    src = path.read_text(encoding="utf-8")
    return [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                              tokenize.INDENT, tokenize.DEDENT)]


def where(seq: list[str], strings: bool = False) -> set[str]:
    """Modules (relative to painter/) whose code has this token sequence.
    With strings=True, a STRING token matches if its text contains seq[0]."""
    hits = set()
    for path in PKG.rglob("*.py"):
        toks = _code_tokens(path)
        for i in range(len(toks)):
            if strings:
                if toks[i].type == tokenize.STRING and seq[0] in toks[i].string:
                    hits.add(path.relative_to(PKG).as_posix())
                    break
                continue
            if [t.string for t in toks[i:i + len(seq)]] == seq:
                hits.add(path.relative_to(PKG).as_posix())
                break
    return hits


def test_a1_roster_is_loaded_in_one_place():
    """Roster.load is the only caller of the student enrollments endpoint."""
    assert where([".", "student_enrollments", "("]) == {"domain/roster.py"}


def test_a2_part_files_are_handled_in_one_place():
    assert where(['".part"'], strings=True) == {"storage/atomic.py"}


def test_atomic_write_keeps_all_or_nothing(tmp_path):
    import pytest
    from painter.storage.atomic import atomic_write
    target = tmp_path / "sub" / "a.txt"
    with atomic_write(target, "w", encoding="utf-8") as fh:
        fh.write("one")
        assert not target.exists()                 # only the .part so far
    assert target.read_text(encoding="utf-8") == "one"
    with pytest.raises(RuntimeError):
        with atomic_write(target, "w", encoding="utf-8") as fh:
            fh.write("two")
            raise RuntimeError("interrupted")
    assert target.read_text(encoding="utf-8") == "one"   # old content kept
    assert list(tmp_path.rglob("*.part")) == []
    with pytest.raises(ValueError):
        with atomic_write(target, "r"):
            pass


def test_a3_csv_is_read_and_written_in_one_place():
    assert where(["csv", "."]) == {"storage/tabular.py"}


def test_write_csv_dicts_and_lists_with_bom(tmp_path):
    from painter.storage.tabular import read_records, read_table, write_csv
    p = write_csv(tmp_path / "a.csv", ["name", "n"], [{"name": "Zoë"}, {"name": "B", "n": 2}])
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    assert read_records(p) == (["name", "n"], [{"name": "Zoë", "n": ""}, {"name": "B", "n": "2"}])
    q = write_csv(tmp_path / "b.csv", ["x", "y"], [["1", "2"]])
    assert read_table(q) == [["x", "y"], ["1", "2"]]
    assert read_table(write_csv(tmp_path / "c.csv", ["only"], [])) == [["only"]]


def test_a4_student_folder_name_has_one_definition():
    """The 45-character name slug is built only by student_folder_name."""
    assert where([", 45)"], strings=True) == {"domain/naming.py"}   # inside f-strings
    from painter.domain.naming import student_dir_name, student_folder_name
    u = {"sortable_name": "Doe, Jane"}
    assert student_folder_name(501, u) == "Doe-Jane_501"
    assert student_dir_name({"user_id": 501, "user": u}) == "Doe-Jane_501"
    assert student_folder_name(7, None) == "Anonymous_7"
