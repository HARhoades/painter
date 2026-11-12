"""Polling of Canvas background jobs and the state file that lets a rerun resume them."""
from __future__ import annotations

import json
from pathlib import Path
import time


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)
