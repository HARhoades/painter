"""Narrow the section chips: a search box (section name or instructor) and an
instructor drop-down, so "Select all" can pick one instructor's sections or
whatever matches. Used by Download's Students box and Make grade files."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QWidget

from painter.gui.widgets import SearchBox, hbox, hidden_note, label

EVERYONE = "All instructors"
NOBODY = "No instructor listed"


def instructor_names(instructors: dict[int, list[str]], section_ids) -> list[str]:
    """Instructors of the given sections, A to Z (plus "no instructor" if any lack one)."""
    names = sorted({n for s in section_ids for n in instructors.get(s, [])}, key=str.lower)
    if any(not instructors.get(s) for s in section_ids) and names:
        names.append(NOBODY)
    return names


class InstructorFilter(QWidget):
    """[Search sections]  Instructor [All instructors ▾]  "1 chosen not shown".
    The instructor part is hidden when no instructors are known."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.search = SearchBox("sections")
        self.search.textChanged.connect(lambda *_: self.changed.emit())
        self.combo = QComboBox()
        self.combo.setAccessibleName("Show the sections of one instructor")
        self.combo.setMinimumWidth(180)
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.combo_label = label("Instructor")
        self.note = label("", "muted")
        row = hbox(self.search, self.combo_label, self.combo, self.note)
        row.setStretch(0, 1)
        self.setLayout(row)
        self.instructors: dict[int, list[str]] = {}
        self.names: dict[int, str] = {}
        self._show_combo(False)

    def _show_combo(self, on: bool):
        self.combo.setVisible(on)
        self.combo_label.setVisible(on)

    def set_sections(self, instructors: dict[int, list[str]], section_ids,
                     names: dict[int, str] | None = None) -> None:
        """New sections: keep the chosen instructor if they still teach one."""
        keep = self.current()
        self.instructors = dict(instructors or {})
        self.names = dict(names or {})
        who = instructor_names(self.instructors, list(section_ids))
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems([EVERYONE, *who])
        if keep in who:
            self.combo.setCurrentText(keep)
        self.combo.blockSignals(False)
        self._show_combo(bool(who))

    def current(self) -> str | None:
        text = self.combo.currentText()
        return None if text in ("", EVERYONE) else text

    def choose(self, name: str | None) -> None:
        self.combo.setCurrentText(name or EVERYONE)

    @property
    def narrowed(self) -> bool:
        return self.current() is not None or self.search.active

    def select_text(self, everyone_chosen: bool) -> str:
        """"Select all", "Select all for Smith", "Clear all shown"…"""
        who = self.current()
        base = "Clear all" if everyone_chosen else "Select all"
        if who and who != NOBODY and not self.search.active:
            return f"{base} for {who}"
        return base + (" shown" if self.narrowed else "")

    def shows(self, section_id: int) -> bool:
        names = self.instructors.get(section_id, [])
        who = self.current()
        if who is not None and (bool(names) if who == NOBODY else who not in names):
            return False
        return self.search.matches(self.names.get(section_id, ""), *names)

    def apply(self, buttons: dict) -> list:
        """Show only the chips that pass; returns the shown ones."""
        shown = []
        for sid, b in buttons.items():
            ok = self.shows(sid)
            b.setVisible(ok)
            if ok:
                shown.append(b)
        hidden = sum(b.isChecked() for s, b in buttons.items() if not self.shows(s))
        self.note.setText("No sections match" if buttons and not shown and self.narrowed
                          else hidden_note(hidden, f"chosen section{'s' * (hidden != 1)}"))
        return shown

    @staticmethod
    def tag_for(roster, section_id: int) -> str:
        """"  ·  Rhoades" for a chip label, or ""."""
        names = (getattr(roster, "instructors", None) or {}).get(section_id, [])
        return f"  ·  {', '.join(names)}" if names else ""
