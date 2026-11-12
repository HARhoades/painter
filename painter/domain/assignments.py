"""Facts about a Canvas assignment: quiz type and its output folder."""
from __future__ import annotations

from pathlib import Path
import re
import sys

from painter.domain.naming import slug


def quiz_kind(assignment: dict) -> str | None:
    """'new' for a New Quiz, 'classic' for a Classic Quiz, None otherwise."""
    if assignment.get("is_quiz_lti_assignment"):
        return "new"
    if assignment.get("quiz_id") or "online_quiz" in (assignment.get("submission_types") or []):
        return "classic"
    tool = (assignment.get("external_tool_tag_attributes") or {}).get("url") or ""
    if "external_tool" in (assignment.get("submission_types") or []) and "quiz-lti" in tool:
        return "new"
    return None


def assignment_folder(out_root: Path, assignment: dict) -> Path:
    """The assignment's folder in the --out tree.

    Reuses an existing NN_<name> folder (from a download run) if there is
    exactly one; otherwise uses 01_<name>, the name a download run with this
    single --assignment would create.
    """
    name = slug(assignment.get("name") or str(assignment.get("id")))
    pattern = re.compile(r"^\d{2,}_" + re.escape(name) + r"$")
    if out_root.is_dir():
        hits = [d for d in out_root.iterdir() if d.is_dir() and pattern.match(d.name)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            print(f"  note: several folders match {name}; using {hits[0].name}",
                  file=sys.stderr)
            return sorted(hits)[0]
    return out_root / f"01_{name}"
