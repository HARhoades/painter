#!/usr/bin/env python3
"""Painter, under its old script name.

    python canvas_fetch_submissions.py <command> [options]

is the same as `painter <command>` and `python -m painter <command>`.
Commands: list, download, roster, organize, grades, quiz. The manual,
including a table from the old --flag options to the new commands, is
docs/manual.md; `--help` lists every option.
"""
# This file is kept so `python canvas_fetch_submissions.py <command> ...` keeps
# working. It runs the same command line as `painter` and `python -m painter`.
from painter.cli.main import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
