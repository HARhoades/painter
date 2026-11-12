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
