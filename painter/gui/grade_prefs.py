"""Settings › Grade files: how new grade files are named by default, and
whether saving edits to a grade file asks first."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox

from painter.config import naming_defaults
from painter.gui.widgets import Card, hbox, label

# How much of the section name starts each file name.
PREFIX_CHOICES = (("short", "Section, short (A1)"),
                  ("full", "Full section name (A1-8)"),
                  ("instructor", "Section and instructor (A1-Rhoades)"))

# Shown greyed out: details the preview could look up in Canvas later.
LATER = ("Show each file's due date in the preview (coming later)",
         "Show each file's points possible in the preview (coming later)")


def prefix_combo(name: str) -> QComboBox:
    box = QComboBox()
    box.setAccessibleName(name)
    for key, text in PREFIX_CHOICES:
        box.addItem(text, key)
    return box


class GradeFilePrefs(Card):
    """The card; every change is saved at once."""

    def __init__(self, session):
        super().__init__(padding=22)
        self.session = session
        self.body.addWidget(label("Grade files", "h2"))
        self.body.addWidget(label(
            "Defaults for courses where you haven't chosen yet in Make grade files. "
            "A course keeps its own choice once you change it there.", "muted", wrap=True))
        self.prefix = prefix_combo("Default start of grade file names")
        self.prefix.currentIndexChanged.connect(self._save)
        self.body.addLayout(hbox(label("File names start with"), self.prefix, None))
        self.term = QCheckBox("Add the academic year and semester to file names")
        self.term.toggled.connect(self._save)
        self.body.addWidget(self.term)
        self.confirm = QCheckBox("Ask before saving changes to a grade file")
        self.confirm.toggled.connect(self._save)
        self.body.addWidget(self.confirm)
        self.body.addWidget(label("Off: Save writes your changes to the file straight away. "
                                  "Painter still checks that nobody else changed the file "
                                  "first.", "muted", wrap=True))
        self.later = []
        for text in LATER:
            box = QCheckBox(text)
            box.setEnabled(False)
            self.later.append(box)
            self.body.addWidget(box)

    def load(self) -> None:
        s = self.session.settings
        d = naming_defaults(s)
        for w in (self.prefix, self.term, self.confirm):
            w.blockSignals(True)
        i = self.prefix.findData(d["prefix"])
        self.prefix.setCurrentIndex(i if i >= 0 else 0)
        self.term.setChecked(bool(d["term"]))
        self.confirm.setChecked(bool(s.confirm_save))
        for w in (self.prefix, self.term, self.confirm):
            w.blockSignals(False)

    def _save(self, *_):
        s = self.session.settings
        s.grade_naming = {"prefix": self.prefix.currentData(), "term": self.term.isChecked()}
        s.confirm_save = self.confirm.isChecked()
        self.session.save()
