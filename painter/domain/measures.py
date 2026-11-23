"""Durations, sizes and speeds as people read them; shared by the command
line, the Excel log and the window so a run reads the same everywhere."""
from __future__ import annotations


def fmt_duration(seconds: float) -> str:
    """'under a second', '42 s', '3 min 07 s', '1 h 05 min'."""
    if seconds < 1:
        return "under a second"
    s = round(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def fmt_clock(seconds: float) -> str:
    """A running clock: '0:07', '3:42', '1:05:09'."""
    s = max(int(seconds), 0)
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_bytes(n: int) -> str:
    """'0 B', '812 B', '14.2 KB', '18.6 MB', '1.20 GB' (1 KB = 1024 B)."""
    if n < 1024:
        return f"{n} B"
    for unit, size in (("KB", 1 << 10), ("MB", 1 << 20), ("GB", 1 << 30)):
        if n < size * 1024 or unit == "GB":
            value = n / size
            return f"{value:.2f} {unit}" if unit == "GB" else f"{value:.1f} {unit}"
    return f"{n} B"                                   # not reached


def fmt_speed(n_bytes: int, seconds: float) -> str:
    """Average speed, or "" when the run was too short to say."""
    if seconds < 1 or n_bytes <= 0:
        return ""
    return fmt_bytes(int(n_bytes / seconds)) + "/s"
