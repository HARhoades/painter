"""Facts about a Canvas assignment: quiz type and its output folder."""
from __future__ import annotations

from pathlib import Path
import re

from painter.domain.naming import slug
from painter.errors import InvalidInput, NotFound


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


def require_one(canvas, course_id: int, assignment_ids, count_error: str,
                optional: bool = False) -> dict | None:
    """The single assignment a mode works on, fetched from Canvas.

    count_error is the message when the number of IDs is wrong (none, unless
    optional, or more than one). A missing assignment is InvalidInput with
    the same wording everywhere; any other Canvas error propagates.
    """
    ids = tuple(assignment_ids or ())
    if not ids and optional:
        return None
    if len(ids) != 1:
        raise InvalidInput(count_error)
    try:
        return canvas.assignment(course_id, ids[0])
    except NotFound as exc:
        raise InvalidInput(f"Assignment {ids[0]} not found in course {course_id} "
                           f"({exc}).") from None


def assignment_dir_name(assignment: dict) -> str:
    """<Name>_<assignment id>: the same in every run, whatever the filters,
    and distinct for two assignments with the same name (review finding 3)."""
    name = slug(assignment.get("name") or "assignment")
    return f"{name}_{assignment['id']}"


def assignment_folder(out_root: Path, assignment: dict) -> tuple[Path, str | None]:
    """The assignment's folder in the --out tree, <Name>_<id>, and a note for
    the user if something was renamed or left alone (else None).

    Older versions named it NN_<Name>, where NN depended on which assignments
    the run was filtered to. If the new folder does not exist yet and exactly
    one such NN_<Name> folder does, it is renamed once so earlier downloads
    and job state carry over. With several candidates nothing is renamed,
    because there is no way to tell which assignment each belonged to.
    """
    target = out_root / assignment_dir_name(assignment)
    if target.exists() or not out_root.is_dir():
        return target, None
    name = slug(assignment.get("name") or "assignment")
    pattern = re.compile(r"^\d{2,}_" + re.escape(name) + r"$")
    legacy = sorted(d for d in out_root.iterdir() if d.is_dir() and pattern.match(d.name))
    if len(legacy) == 1:
        legacy[0].rename(target)
        return target, (f"  renamed {legacy[0].name}/ -> {target.name}/ (folders are "
                        "now named by assignment ID)")
    if legacy:
        return target, (f"  note: {', '.join(d.name for d in legacy)} are from an older "
                        f"version and could belong to any assignment named {name}; "
                        f"writing to {target.name}/ and leaving them as they are")
    return target, None
