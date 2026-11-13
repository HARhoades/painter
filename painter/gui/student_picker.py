"""Choosing students: section chips, a name search to add anyone else, and
a folded list to leave individual students out of the chosen sections."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCompleter, QGridLayout, QLineEdit, QToolButton, QVBoxLayout, QWidget,
)

from painter.domain.matching import StudentMatcher
from painter.domain.roster import Roster
from painter.domain.selection import Selection
from painter.gui.widgets import button, clear, hbox, label

COLUMNS = 4


def _short(u: dict) -> str:
    return u.get("sortable_name") or u.get("name") or str(u["id"])


class StudentPicker(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.roster: Roster | None = None
        self.extra: list[int] = []          # added by name, outside the chosen sections
        self.excluded: set[int] = set()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.summary = label("", "muted", wrap=True)
        lay.addWidget(self.summary)
        self.chips_box = QWidget()
        self.chips = hbox(spacing=8)
        self.chips_box.setLayout(self.chips)
        lay.addWidget(self.chips_box)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Add a student by name or ID")
        self.search.setAccessibleName("Add a student by name or ID")
        self.search.returnPressed.connect(self._add_typed)
        self.completer = QCompleter([])
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.activated.connect(self._add_choice)
        self.search.setCompleter(self.completer)
        self.search_note = label("", "muted")
        self.extras = hbox(spacing=8)
        row = hbox(label("Also include", "muted"), self.search, self.search_note)
        row.setStretch(1, 1)
        lay.addLayout(row)
        lay.addLayout(self.extras)

        self.fold = QToolButton()
        self.fold.setCheckable(True)
        self.fold.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.fold.setArrowType(Qt.RightArrow)
        self.fold.setStyleSheet("QToolButton { border: 0; font-weight: 600; }")
        self.fold.toggled.connect(self._toggle_fold)
        lay.addWidget(self.fold)
        self.people_box = QWidget()
        self.people = QGridLayout(self.people_box)
        self.people.setContentsMargins(18, 0, 0, 0)
        self.people.setSpacing(6)
        self.people_box.setVisible(False)
        lay.addWidget(self.people_box)
        self.fold_note = label("Click a name to leave it out; left-out names are struck "
                               "through and marked ✕.", "muted")
        self.fold_note.setVisible(False)
        lay.addWidget(self.fold_note)
        self.section_buttons: dict[int, object] = {}

    # ---- data ----
    def set_roster(self, roster: Roster, chosen: set[int] | None = None) -> None:
        self.roster = roster
        self.extra, self.excluded = [], set()
        clear(self.chips)
        self.section_buttons = {}
        for s in sorted(roster.sections, key=lambda x: x.get("name") or ""):
            if s["id"] in roster.catch_all:
                continue                     # the course-wide section: everyone
            n = len(roster.users_of_section.get(s["id"], ()))
            b = button("", "chip")
            b.setCheckable(True)
            b.setChecked(bool(chosen) and s["id"] in chosen)
            b.toggled.connect(self._sections_changed)
            b.setProperty("section", s["id"])
            b._label = f"{s.get('name')}  ({n})"
            self.section_buttons[s["id"]] = b
            self.chips.addWidget(b)
        self.chips.addStretch(1)
        self._sections_changed()

    def chosen_sections(self) -> list[int]:
        return [sid for sid, b in self.section_buttons.items() if b.isChecked()]

    def in_sections(self) -> set[int]:
        ids: set[int] = set()
        for sid in self.chosen_sections():
            ids |= self.roster.users_of_section.get(sid, set())
        return ids

    def student_ids(self) -> set[int]:
        return (self.in_sections() | set(self.extra)) - self.excluded

    def selection(self) -> Selection:
        """Canvas IDs as specs: the exact-ID tier always matches exactly."""
        return Selection.of(sections=[str(s) for s in self.chosen_sections()],
                            students=[str(u) for u in self.extra],
                            exclude=[str(u) for u in sorted(self.excluded & self.in_sections())])

    # ---- reactions ----
    def _sections_changed(self, *_):
        for b in self.section_buttons.values():
            b.setText(("✓ " if b.isChecked() else "+ ") + b._label)
        inside = self.in_sections()
        self.extra = [u for u in self.extra if u not in inside]
        self._refresh_completer()
        self._refresh_people()
        self._refresh_extras()
        self._emit()

    def _refresh_completer(self):
        inside = self.in_sections()
        self._choices = {}
        for u in self.roster.users.values():
            if u["id"] in inside or u["id"] in self.extra:
                continue
            secs = ", ".join(self.roster.section_names(u["id"]))
            self._choices[f"{_short(u)} ({u['id']}) · {secs}"] = u["id"]
        self.completer.model().setStringList(sorted(self._choices))

    def _add_choice(self, text: str):
        uid = self._choices.get(text)
        if uid is not None:
            self._add(uid)

    def _add_typed(self):
        text = self.search.text().strip()
        if not text or text in self._choices:
            return self._add_choice(text)
        hits = StudentMatcher(self.roster.users.values()).by_spec(text)
        if len(hits) == 1:
            self._add(hits[0]["id"])
        else:
            self.search_note.setText("No match" if not hits else
                                     f"{len(hits)} match; pick one from the list")

    def _add(self, uid: int):
        if uid not in self.extra and uid not in self.in_sections():
            self.extra.append(uid)
        self.search.clear()
        self.search_note.setText("")
        self._refresh_completer()
        self._refresh_extras()
        self._emit()

    def _remove(self, uid: int):
        self.extra.remove(uid)
        self._refresh_completer()
        self._refresh_extras()
        self._emit()

    def _refresh_extras(self):
        clear(self.extras)
        for uid in self.extra:
            u = self.roster.users[uid]
            secs = ", ".join(self.roster.section_names(uid))
            b = button(f"{_short(u)} ({secs})  ✕", "chip",
                       lambda _=False, x=uid: self._remove(x), "Remove")
            b.setAccessibleName(f"Remove {_short(u)}")
            self.extras.addWidget(b)
        self.extras.addStretch(1)

    def _refresh_people(self):
        clear(self.people)
        inside = sorted(self.in_sections(), key=lambda u: _short(self.roster.users[u]))
        self.excluded &= set(inside)
        for i, uid in enumerate(inside):
            u = self.roster.users[uid]
            b = button("", "name")
            b.setCheckable(True)
            b.setChecked(uid in self.excluded)
            b.toggled.connect(lambda on, x=uid, btn=b: self._exclude(x, on, btn))
            self._name_text(b, u, uid in self.excluded)
            self.people.addWidget(b, i // COLUMNS, i % COLUMNS)
        names = ", ".join(self.roster.section_by_id[s].get("name", "")
                          for s in self.chosen_sections())
        left = len(self.excluded)
        self.fold.setText(f"Choose individual students in {names}" +
                          (f"  ·  {left} left out" if left else "  ·  everyone is in")
                          if names else "Choose individual students (pick a section first)")
        self.fold.setEnabled(bool(inside))

    @staticmethod
    def _name_text(b, u, out: bool):
        b.setText(("✕ " if out else "✓ ") + _short(u))
        b.setAccessibleName(f"{_short(u)}, {'left out' if out else 'included'}")

    def _exclude(self, uid: int, out: bool, b):
        (self.excluded.add if out else self.excluded.discard)(uid)
        self._name_text(b, self.roster.users[uid], out)
        left = len(self.excluded)
        base = self.fold.text().split("  ·  ")[0]
        self.fold.setText(base + (f"  ·  {left} left out" if left else "  ·  everyone is in"))
        self._emit()

    def _toggle_fold(self, on: bool):
        self.fold.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.people_box.setVisible(on)
        self.fold_note.setVisible(on)

    def _emit(self):
        n = len(self.student_ids())
        self.summary.setText(f"Everyone in the chosen sections, plus anyone added by name. "
                             f"{n} student{'s' * (n != 1)}.")
        self.changed.emit()
