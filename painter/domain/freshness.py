"""How old a cached value is, and how to say so.

A value shown from the cache is in one of five states:
  none       nothing cached; the screen is loading
  checking   shown from the cache while Canvas is being asked
  confirmed  Canvas answered within the window for this kind of value
  stale      older than the window; a check is due
  failed     the last check could not reach or satisfy Canvas
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

WINDOWS = {
    "courses": timedelta(hours=1),            # kept in memory only; see gui/views/home.py
    "assignments": timedelta(minutes=10),
    "rosters": timedelta(days=1),
    "filecounts": timedelta(minutes=10),
}


@dataclass(frozen=True)
class Freshness:
    state: str
    fetched_at: datetime | None = None
    reason: str = ""


def needs_check(kind: str, fetched_at: datetime | None, now: datetime | None = None) -> bool:
    """True when there is no value, or it is older than the kind's window."""
    now = now or datetime.now(timezone.utc)
    return fetched_at is None or now - fetched_at >= WINDOWS[kind]


def classify(kind: str, fetched_at: datetime | None, checking: bool = False,
             error: str = "", now: datetime | None = None) -> Freshness:
    if error and fetched_at is not None:
        return Freshness("failed", fetched_at, error)
    if fetched_at is None:
        return Freshness("failed" if error else "none", None, error)
    if checking:
        return Freshness("checking", fetched_at)
    return Freshness("stale" if needs_check(kind, fetched_at, now) else "confirmed", fetched_at)


def oldest(*times: datetime | None) -> datetime | None:
    """The oldest of several fetch times; None if any is missing."""
    return None if any(t is None for t in times) or not times else min(times)


def when(fetched_at: datetime, now: datetime | None = None) -> str:
    """"just now", "4 min ago", "2 h ago", or "12 Nov, 14:02" for older values."""
    now = now or datetime.now(timezone.utc)
    secs = (now - fetched_at).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    local = fetched_at.astimezone()
    return f"{local.day} {local:%b, %H:%M}"


def describe(f: Freshness, now: datetime | None = None) -> str:
    if f.state == "none":
        return "Loading…"
    if f.state == "failed" and f.fetched_at is None:
        return "⚠ Couldn't check"
    at = when(f.fetched_at, now)
    if f.state == "confirmed":
        return f"✓ Up to date · checked {at}"
    if f.state == "checking":
        return f"⟳ From {at} · checking…"
    if f.state == "stale":
        return f"● From {at} · not checked yet"
    return f"⚠ Couldn't confirm · showing {at}"
