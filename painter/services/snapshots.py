"""What the local cache stores for each kind of data, and how it is read back.

Plain dicts and lists only (JSON-safe). Anything that does not read back as
expected raises, and callers treat that as "not cached".
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from painter.services.submissions import AssignmentFiles, AssignmentInfo


def assignments_to_data(items: list[AssignmentInfo], tz: str | None) -> dict:
    return {"tz": tz or "", "items": [asdict(a) for a in items]}


def assignments_from_data(data: dict) -> list[AssignmentInfo]:
    return [AssignmentInfo(**d) for d in data["items"]]


def files_to_data(known: dict[int, AssignmentFiles], at: dict[int, datetime]) -> dict:
    """File counts per assignment, each with when it was read."""
    return {str(aid): {"at": at[aid].isoformat(),
                       "submitted": sorted(f.submitted),
                       "files": {str(u): n for u, n in f.files.items()},
                       "files_history": {str(u): n for u, n in f.files_history.items()}}
            for aid, f in known.items() if aid in at}


def files_from_data(data: dict) -> tuple[dict[int, AssignmentFiles], dict[int, datetime]]:
    known, at = {}, {}
    for aid, d in data.items():
        when = datetime.fromisoformat(d["at"])
        known[int(aid)] = AssignmentFiles(
            {int(u) for u in d["submitted"]},
            {int(u): int(n) for u, n in d["files"].items()},
            {int(u): int(n) for u, n in d["files_history"].items()})
        at[int(aid)] = when
    return known, at
