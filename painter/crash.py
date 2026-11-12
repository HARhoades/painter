"""Crash reports: the full traceback of an unexpected error, saved where
the user (or whoever helps them) can find it. Shared by every front end."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import traceback

from painter.config import app_data_dir


def crash_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def write_crash_report(exc: BaseException, header: str) -> Path | None:
    """app_data_dir()/logs/crash_<time>.txt, or None if it can't be written."""
    try:
        logs = app_data_dir() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / f"crash_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path.write_text(f"{header}\n\n{crash_text(exc)}", encoding="utf-8")
    except OSError:
        return None
    return path
