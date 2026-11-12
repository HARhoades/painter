"""docs/manual.md documents every command and every option the parser has."""
from __future__ import annotations

import argparse
from pathlib import Path

from painter.cli.main import build_parser

MANUAL = (Path(__file__).resolve().parent.parent / "docs" / "manual.md").read_text(
    encoding="utf-8")


def commands(parser, path=()):
    """(command path, its parser) for every leaf command."""
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield path, parser
        return
    for name, sub in subs[0].choices.items():
        yield from commands(sub, path + (name,))


def test_manual_covers_every_command_and_option():
    missing = []
    for path, p in commands(build_parser()):
        name = "painter " + " ".join(path)
        if f"## {name}" not in MANUAL and f"`{name}" not in MANUAL:
            missing.append(name)
        for action in p._actions:
            for opt in action.option_strings:
                if opt.startswith("--") and opt != "--help" and f"`{opt}" not in MANUAL:
                    missing.append(f"{name} {opt}")
    assert not missing, missing


def test_manual_exit_table_matches_the_code():
    from painter.cli.exit_codes import TABLE
    for code, _ in TABLE:
        assert f"| {code} |" in MANUAL
