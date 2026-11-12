"""Polling of Canvas background jobs and the state file that lets a rerun resume them."""
from __future__ import annotations

import json
from pathlib import Path
import time

from painter.storage.atomic import atomic_write


POLL_START = 2.0            # first wait when polling a background job


POLL_FACTOR = 1.5           # each later wait is this much longer ...


POLL_CAP = 30.0             # ... up to this upper bound between polls


def poll_until(fetch, is_done, timeout: float, sleep=time.sleep,
               start: float = POLL_START, factor: float = POLL_FACTOR,
               cap: float = POLL_CAP, on_poll=None):
    """Call fetch() until is_done(result) or timeout; returns (result, done).

    The wait between polls starts at `start` seconds and grows by `factor`
    each time, never exceeding `cap` and never sleeping past the deadline.
    """
    deadline = time.monotonic() + timeout
    interval = start
    result = fetch()
    while not is_done(result):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result, False
        sleep(min(interval, remaining))
        interval = min(cap, interval * factor)
        result = fetch()
        if on_poll:
            on_poll(result)
    return result, True


# ---- content export jobs ------------------------------------------------------
def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    with atomic_write(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(state, indent=2))


class ResumableJob:
    """One Canvas background job's entry in a state file.

    The job ID is saved the moment Canvas returns it, so a rerun after an
    interruption or timeout resumes that job instead of starting a second
    one; the entry is cleared once the job's file has been downloaded. Several
    jobs share one file under different keys. `identity` is what the entry
    must match to be reused (e.g. the course and assignment).
    """

    def __init__(self, state_path: Path, key: str, identity: dict):
        self.path, self.key, self.identity = Path(state_path), key, dict(identity)

    def saved(self) -> dict | None:
        """The saved entry, if there is one for this identity."""
        entry = _load_state(self.path).get(self.key)
        if entry and all(entry.get(k) == v for k, v in self.identity.items()):
            return entry
        return None

    def save(self, **fields) -> None:
        state = _load_state(self.path)
        state[self.key] = {**self.identity, **fields}
        _save_state(self.path, state)

    def clear(self) -> None:
        state = _load_state(self.path)
        state.pop(self.key, None)
        _save_state(self.path, state)


def discard_if_empty(state_path: Path) -> None:
    """Remove a state file that no longer holds any job."""
    if Path(state_path).exists() and not _load_state(state_path):
        Path(state_path).unlink()
