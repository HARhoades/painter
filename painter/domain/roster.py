"""Course membership: sections, students, instructors, and the --section/--student filters."""
from __future__ import annotations

from painter.canvas.client import Canvas
from painter.errors import InvalidInput, NotFound
from painter.events import Note
from painter.domain.matching import (  # noqa: F401  (match_* re-exported)
    StudentMatcher, best_matches, match_section, match_student, section_ids,
    section_names,
)


# --------------------------------------------------------------------------
# Main workflow
# --------------------------------------------------------------------------
def catch_all_sections(sections_by_student: dict) -> set:
    """Sections that say nothing about where a student belongs.

    A course-wide default section holds every student; it counts as a catch-all
    only if every student also has another, real section. The one rule used by
    download --by-section, quiz uploads --by-section and --organize
    (review finding 5).
    """
    groups = [secs for secs in sections_by_student.values() if secs]
    if not groups:
        return set()
    return {sec for sec in {s for g in groups for s in g}
            if all(sec in g and len(g) > 1 for g in groups)}


class Roster:
    """Course membership, joined across the sections and enrollments endpoints.

    Canvas submission objects carry no section field, so the only way to know
    which section a submission belongs to is to build this map first and look
    up by user_id.
    """

    def __init__(self, sections: list[dict], enrollments: list[dict]):
        self.sections = sections
        self.section_by_id = {s["id"]: s for s in sections}
        self.users: dict[int, dict] = {}
        self.sections_of_user: dict[int, list[int]] = {}
        self.users_of_section: dict[int, set[int]] = {s["id"]: set() for s in sections}

        for enr in enrollments:
            uid = enr.get("user_id")
            if uid is None:
                continue
            user = dict(enr.get("user") or {})
            user.setdefault("id", uid)
            # SIS/login live on the enrollment, not the nested user object.
            if enr.get("sis_user_id"):
                user.setdefault("sis_user_id", enr["sis_user_id"])
            if enr.get("user", {}).get("login_id"):
                user.setdefault("login_id", enr["user"]["login_id"])
            self.users.setdefault(uid, user)

            sid = enr.get("course_section_id")
            if sid is None:
                continue
            self.sections_of_user.setdefault(uid, [])
            if sid not in self.sections_of_user[uid]:
                self.sections_of_user[uid].append(sid)
            self.users_of_section.setdefault(sid, set()).add(uid)

        self.catch_all: set[int] = catch_all_sections(self.sections_of_user)

    @classmethod
    def load(cls, canvas: Canvas, course_id: int) -> "Roster":
        """Sections and student enrollments of a course: two paginated calls."""
        return cls(canvas.sections(course_id), canvas.student_enrollments(course_id))

    def section_names(self, user_id: int) -> list[str]:
        return [self.section_by_id.get(s, {}).get("name", str(s))
                for s in self.sections_of_user.get(user_id, [])]

    def primary_section(self, user_id: int, preferred: set[int] | None) -> dict | None:
        """The section to file a student under when writing per-section folders.

        If a student is in several sections, prefer one the user actually
        selected; otherwise their first enrollment. Either way a course-wide
        catch-all section loses to a real one, as in --organize.
        """
        ids = self.sections_of_user.get(user_id, [])
        if not ids:
            return None
        ranked = ([s for s in ids if s not in self.catch_all]
                  + [s for s in ids if s in self.catch_all])
        if preferred:
            for sid in ranked:
                if sid in preferred:
                    return self.section_by_id.get(sid)
        return self.section_by_id.get(ranked[0])


def _reject_empty(specs: list[str], flag: str) -> None:
    if any(not (s or "").strip() for s in specs):
        raise InvalidInput(f"{flag} needs a value; an empty one would match everything.")


def resolve_sections(roster: Roster, specs: list[str]) -> tuple[set[int], list[Note]]:
    """Turn --section specs into section IDs, failing loudly on typos.

    Returns (ids, notes); notes say when one spec matched several sections."""
    notes: list[Note] = []
    selected: set[int] = set()
    unmatched: list[str] = []

    _reject_empty(specs, "--section")
    for spec in specs:
        hits = best_matches(spec, roster.sections, section_ids, section_names)
        if not hits:
            unmatched.append(spec)
            continue
        if len(hits) > 1:
            names = ", ".join(f"{s.get('name')} ({s['id']})" for s in hits)
            notes.append(("info", f"  note: '{spec}' matched {len(hits)} sections -> {names}"))
        for s in hits:
            selected.add(s["id"])

    if unmatched:
        raise InvalidInput(
            "No section match for: " + ", ".join(repr(s) for s in unmatched) +
            "\nRun `painter list sections` to see valid IDs and names."
        )
    return selected, notes


def resolve_students(roster: Roster, specs: list[str]) -> tuple[set[int], list[Note]]:
    """Turn --student specs into user IDs, failing loudly on typos.

    Returns (ids, notes); notes say when one spec matched several students."""
    notes: list[Note] = []
    selected: set[int] = set()
    unmatched: list[str] = []

    _reject_empty(specs, "--student")
    for spec in specs:
        hits = StudentMatcher(roster.users.values()).by_spec(spec)
        if not hits:
            unmatched.append(spec)
            continue
        if len(hits) > 1:
            names = ", ".join(f"{u.get('sortable_name')} ({u['id']})" for u in hits)
            notes.append(("info", f"  note: '{spec}' matched {len(hits)} students -> {names}"))
        for u in hits:
            selected.add(u["id"])

    if unmatched:
        raise InvalidInput(
            "No roster match for: " + ", ".join(repr(s) for s in unmatched) +
            "\nRun `painter list students` to see valid IDs and names."
        )
    return selected, notes


def assigned_students(canvas: Canvas, course_id: int,
                      assignment_ids: list[int]) -> set[int]:
    """Students who have the given assignment(s), i.e. a submission record.

    Canvas creates a submission record for every student an assignment is
    assigned to, whether or not they have turned anything in, so this also
    respects "assign to" overrides. With several assignments, a student
    who has any of them is included.
    """
    users: set[int] = set()
    for aid in assignment_ids:
        try:
            for sub in canvas.paginate(
                    f"/courses/{course_id}/assignments/{aid}/submissions"):
                if sub.get("user_id") is not None:
                    users.add(sub["user_id"])
        except NotFound as exc:
            raise InvalidInput(f"Assignment {aid} not found in course {course_id} "
                             f"({exc}).\nRun `painter list assignments` to see valid IDs.")
    return users


def instructor_label(enrollment: dict) -> str:
    """Surname of an instructor, as the grade files use it ('Rhoades')."""
    user = enrollment.get("user") or {}
    sortable = user.get("sortable_name") or ""
    if "," in sortable:
        return sortable.split(",", 1)[0].strip()
    name = user.get("name") or sortable
    return name.split()[-1] if name.split() else ""


def split_name(user: dict) -> tuple[str, str]:
    """(first, last) for a Canvas user.

    sortable_name ("Last, First") is the reliable split: it keeps multi-word
    surnames such as "De La Cruz, Ana" together. Without a comma, the last
    word of the display name is taken as the surname.
    """
    sortable = (user.get("sortable_name") or "").strip()
    if "," in sortable:
        last, first = (part.strip() for part in sortable.split(",", 1))
        return first, last
    words = (user.get("name") or sortable).split()
    if not words:
        return "", ""
    return " ".join(words[:-1]), words[-1]


def section_instructors(canvas: Canvas, course_id: int) -> dict[int, list[str]]:
    """Section ID -> instructor surnames. Teachers win; TAs only as a fallback."""
    teachers: dict[int, list[str]] = {}
    tas: dict[int, list[str]] = {}
    for enr in canvas.teacher_enrollments(course_id):
        sid = enr.get("course_section_id")
        name = instructor_label(enr)
        if sid is None or not name:
            continue
        bucket = teachers if enr.get("type") == "TeacherEnrollment" else tas
        names = bucket.setdefault(sid, [])
        if name not in names:
            names.append(name)
    return {sid: teachers.get(sid) or tas.get(sid) or []
            for sid in set(teachers) | set(tas)}
