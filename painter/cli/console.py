"""The command line's Reporter: prints, exactly as the tool always has."""
from __future__ import annotations

import sys


class ConsoleReporter:
    def info(self, text: str = "", end: str = "\n") -> None:
        print(text, end=end, flush=not end)

    def warning(self, text: str) -> None:
        print(text, file=sys.stderr)

    def progress(self, done: int, total: int, label: str = "") -> None:
        pass            # the CLI prints its own per-item lines instead

    def cancelled(self) -> bool:
        return False    # Ctrl-C raises KeyboardInterrupt instead
