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


def test_a5_a7_matching_rules_live_in_matching():
    """SIS IDs and logins are read only where users are built (roster), matched
    (matching) or displayed (cli); the rules are defined only in matching."""
    assert where(['"sis_user_id"'], strings=True) <= {
        "domain/roster.py", "domain/matching.py", "cli/commands.py"}
    assert where(['"login_id"'], strings=True) <= {
        "domain/roster.py", "domain/matching.py", "cli/commands.py"}
    import ast
    rules = {"letters_key", "name_words", "same_words", "name_contains",
             "match_tier", "best_matches", "match_section", "match_student"}
    defined = {}
    for path in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name in rules:
                defined.setdefault(node.name, set()).add(path.relative_to(PKG).as_posix())
    assert defined == {r: {"domain/matching.py"} for r in rules}


def test_student_matcher():
    from painter.domain.matching import StudentMatcher
    users = [{"id": 501, "name": "Jane Doe", "sortable_name": "Doe, Jane",
              "sis_user_id": "S501", "login_id": "jdoe2"},
             {"id": 502, "name": "Jane Doeson", "sortable_name": "Doeson, Jane"}]
    m = StudentMatcher(users)
    assert [u["id"] for u in m.by_id("S501")] == [501]
    assert [u["id"] for u in m.by_id("jdoe2")] == [501] and m.by_id("") == []
    assert [u["id"] for u in m.by_spec("Jane Doe")] == [501]      # exact beats partial
    assert [u["id"] for u in m.by_spec("doe")] == [501, 502]
    assert [u["id"] for u in m.by_words("doe jane")] == [501]
    kinds = [k for k, _, _ in m.value_lookups()]
    assert kinds == ["Canvas user ID", "SIS user ID", "login", "name"]


def test_a10_one_assignment_check(fake_canvas):
    import pytest
    from painter.canvas.client import Canvas
    from painter.domain.assignments import require_one
    from painter.errors import InvalidInput
    c = Canvas("https://canvas.test", "t")
    assert require_one(c, 100, (7001,), "one please")["id"] == 7001
    assert require_one(c, 100, (), "one please", optional=True) is None
    for ids in ((), (7001, 7002)):
        with pytest.raises(InvalidInput, match="one please"):
            require_one(c, 100, ids, "one please")
    with pytest.raises(InvalidInput, match="Assignment 9999 not found in course 100"):
        require_one(c, 100, (9999,), "one please")
    # nothing else fetches a single assignment for a mode
    # grading looks up the assignment each grade file names, a different job
    assert where([".", "assignment", "("]) == {"domain/assignments.py", "services/grading.py"}


def test_a11_selection_then_assigned_in_one_place(fake_canvas):
    from painter.canvas.client import Canvas
    from painter.domain.roster import Roster
    from painter.domain.selection import Selection
    assert where(["assigned_students", "("]) == {"domain/roster.py", "domain/selection.py"}
    c = Canvas("https://canvas.test", "t")
    roster = Roster.load(c, 100)
    everyone = Selection().resolve_assigned(c, roster, 100, (7001,))
    assert everyone.student_ids == {501, 502, 503} and everyone.selected is None
    a2 = Selection.of(["A2"]).resolve_assigned(c, roster, 100, (7001,))
    assert a2.student_ids == {502, 503} and a2.selected == {502, 503}
    assert Selection().resolve_assigned(c, roster, 100, ()).student_ids is None


def test_a12_job_state_is_handled_by_resumable_job(tmp_path):
    from painter.canvas.jobs import ResumableJob, discard_if_empty
    assert where(["_save_state", "("]) == {"canvas/jobs.py"}
    assert where(["_load_state", "("]) == {"canvas/jobs.py"}
    p = tmp_path / ".state.json"
    a = ResumableJob(p, "report", {"course_id": 1, "assignment_id": 2})
    b = ResumableJob(p, "export", {"course_id": 1})
    assert a.saved() is None
    a.save(progress_id=5)
    b.save(export_id=9, created_at="t")
    assert a.saved() == {"course_id": 1, "assignment_id": 2, "progress_id": 5}
    assert ResumableJob(p, "report", {"course_id": 1, "assignment_id": 3}).saved() is None
    a.clear()
    assert a.saved() is None and b.saved()["export_id"] == 9
    discard_if_empty(p)
    assert p.exists()                      # still holds the export
    b.clear()
    discard_if_empty(p)
    assert not p.exists()


def test_a13_one_uploads_log_writer():
    assert where(['"uploads_log.csv"'], strings=True) == {"services/quiz_uploads.py"}
    src = (PKG / "services/quiz_uploads.py").read_text(encoding="utf-8")
    assert src.count('"uploads_log.csv"') == 1


def test_part_b_no_oversized_functions():
    """Phase 4 part B: no function over 80 lines outside cli/ (the CLI
    parser is replaced in part D and then covered too)."""
    import ast
    long = []
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG).as_posix()
        if rel.startswith("cli/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n = node.end_lineno - node.lineno + 1
                if n > 80:
                    long.append(f"{rel}:{node.name} ({n} lines)")
    assert not long, long
