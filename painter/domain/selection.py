"""Which students a run is about: --section and --student, as a union."""
from __future__ import annotations

from dataclasses import dataclass, field

from painter.domain.roster import Roster, resolve_sections, resolve_students
from painter.errors import InvalidInput
from painter.events import Note


@dataclass(frozen=True)
class Selection:
    """Section and student specs (ID, SIS ID, login or name)."""
    sections: tuple[str, ...] = ()
    students: tuple[str, ...] = ()

    @classmethod
    def of(cls, sections=None, students=None) -> "Selection":
        return cls(tuple(sections or ()), tuple(students or ()))

    @property
    def active(self) -> bool:
        """False means "everyone"."""
        return bool(self.sections or self.students)

    def resolve(self, roster: Roster) -> "Resolved":
        """Specs -> IDs. Raises errors.InvalidInput when a spec matches nothing.

        Shared by downloads, --list-students, the roster CSV and quiz
        export, so all of them select exactly the same people.
        """
        if not self.active:
            return Resolved(None, set(), [])
        notes: list[Note] = []
        student_ids: set[int] = set()
        section_ids: set[int] = set()
        if self.sections:
            section_ids, more = resolve_sections(roster, list(self.sections))
            notes += more
            for sid in section_ids:
                student_ids |= roster.users_of_section.get(sid, set())
            names = ", ".join(roster.section_by_id[s].get("name", str(s))
                              for s in sorted(section_ids))
            notes.append(("warning", f"Sections: {names}"))
        if self.students:
            try:
                ids, more = resolve_students(roster, list(self.students))
            except InvalidInput as exc:      # what was said so far still shows
                exc.notes = notes + exc.notes
                raise
            notes += more
            student_ids |= ids
        return Resolved(student_ids, section_ids, notes)


@dataclass
class Resolved:
    student_ids: set[int] | None          # None: no filter, everyone
    section_ids: set[int]
    notes: list[Note] = field(default_factory=list)


def select_students(roster: Roster, args) -> tuple[set[int] | None, set[int]]:
    """TEMPORARY (phase 3): the old args-based call, printing its notes.
    Removed once every service takes a Selection (step 11)."""
    import sys
    res = Selection.of(args.section, args.student).resolve(roster)
    for kind, text in res.notes:
        print(text, file=sys.stderr if kind == "warning" else sys.stdout)
    return res.student_ids, res.section_ids
