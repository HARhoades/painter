"""Phase 3's rule, enforced: only painter/cli/ talks to the terminal.

Outside cli/ (and the `python -m painter` entry point) no module may call
print() or input(), raise or catch SystemExit, or read an argparse
namespace (args.<name>). Services report through a Reporter, take request
dataclasses and raise painter.errors exceptions, so a GUI can call them.
Comments and strings are ignored: the check reads Python tokens.
"""
from __future__ import annotations

import io
from pathlib import Path
import tokenize

import pytest

PKG = Path(__file__).resolve().parent.parent / "painter"
FRONT_ENDS = {PKG / "cli", PKG / "__main__.py"}


def _modules():
    for path in sorted(PKG.rglob("*.py")):
        if any(path == f or f in path.parents for f in FRONT_ENDS):
            continue
        yield path


def violations(source: str) -> list[str]:
    toks = [t for t in tokenize.generate_tokens(io.StringIO(source).readline)
            if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                              tokenize.INDENT, tokenize.DEDENT)]
    found = []
    for i, tok in enumerate(toks):
        if tok.type != tokenize.NAME:
            continue
        prev = toks[i - 1].string if i else ""
        nxt = toks[i + 1].string if i + 1 < len(toks) else ""
        if prev == ".":                       # an attribute, e.g. page.print(
            continue
        if tok.string in ("print", "input") and nxt == "(":
            found.append(f"line {tok.start[0]}: {tok.string}()")
        elif tok.string == "SystemExit":
            found.append(f"line {tok.start[0]}: SystemExit")
        elif tok.string == "args" and nxt == ".":
            found.append(f"line {tok.start[0]}: args.{toks[i + 2].string}")
    return found


def test_the_checker_catches_each_pattern_and_skips_comments_and_strings():
    src = ("x = 1  # print(x) input() SystemExit args.out\n"
           "s = 'print(1)'\n"
           "page.print(1)\n"
           "print(x)\n"
           "raise SystemExit(1)\n"
           "y = args.out\n"
           "z = input('?')\n")
    assert violations(src) == ["line 4: print()", "line 5: SystemExit",
                               "line 6: args.out", "line 7: input()"]


@pytest.mark.parametrize("path", list(_modules()),
                         ids=lambda p: str(p.relative_to(PKG.parent)).replace("\\", "/"))
def test_no_terminal_io_outside_cli(path):
    found = violations(path.read_text(encoding="utf-8"))
    assert not found, f"{path.relative_to(PKG.parent)}: " + ", ".join(found)


# ---- phase 5: the window's boundary ---------------------------------------------
import ast  # noqa: E402

GUI = PKG / "gui"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
    return out


@pytest.mark.parametrize("path", sorted(PKG.rglob("*.py")),
                         ids=lambda p: str(p.relative_to(PKG.parent)).replace("\\", "/"))
def test_only_the_window_imports_qt(path):
    if GUI in path.parents:
        return
    qt = {m for m in _imports(path) if m.split(".")[0] in ("PySide6", "PyQt6", "PyQt5", "shiboken6")}
    assert not qt, f"{path.relative_to(PKG.parent)} imports {sorted(qt)}"


@pytest.mark.parametrize("path", sorted(GUI.rglob("*.py")),
                         ids=lambda p: str(p.relative_to(PKG.parent)).replace("\\", "/"))
def test_the_window_uses_services_not_the_cli_or_http(path):
    bad = {m for m in _imports(path)
           if m.startswith("painter.cli") or m.split(".")[0] in ("requests", "urllib3")}
    assert not bad, f"{path.relative_to(PKG.parent)} imports {sorted(bad)}"
