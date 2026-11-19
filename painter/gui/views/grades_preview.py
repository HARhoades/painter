"""Post grades, step 2: each grade file as it is on disk, one card per student.
Grades and comments can be changed here and saved back to the file; Review
then reads the files again, so what is posted is always what is saved."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from painter.gui.grade_text import overlap_text
from painter.gui.views import View
from painter.gui.widgets import (
    Banner, Card, StepBar, badge, button, clear, heading, hbox, label, restyle, show_problem,
)
from painter.services.grade_edits import (
    Edit, EditRefused, FileChanged, Stamp, grade_warnings, refusal, save_edits,
)
from painter.services.grade_files import GradeFileError, parse_grade_file
from painter.services.grading import plan_grades

MUTED = "#5E574C"
META = ("Assignment", "Section", "Instructor", "Folder", "Last changed", "Size")


class StudentCard(QFrame):
    """One student: name and id to read; grade and comment to change."""
    edited = Signal()

    def __init__(self, entry):
        super().__init__()
        self.setObjectName("student")
        self.entry = entry
        self.name = label(f"<b>{entry.name or '(no name)'}</b><br>"
                          f"<span style='color:{MUTED}'>Canvas ID {entry.id or '—'}</span>",
                          wrap=True)
        self.name.setMinimumWidth(190)
        self.state = label("", "", wrap=True)
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(self.name)
        left.addWidget(self.state)
        left.addStretch(1)
        self.grade = QLineEdit(entry.grade)
        self.grade.setAccessibleName(f"Grade for {entry.name}")
        self.grade.setPlaceholderText("grade")
        self.grade.setMaximumWidth(120)
        self.grade.textChanged.connect(self._changed)
        self.comment = QPlainTextEdit(entry.comments)
        self.comment.setObjectName("comment")
        self.comment.setAccessibleName(f"Comment for {entry.name}")
        self.comment.setPlaceholderText("comment")
        self.comment.setTabChangesFocus(True)
        self.comment.setFixedHeight(76)
        self.comment.textChanged.connect(self._changed)
        self.problem = label("", "", wrap=True)
        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(self.comment)
        right.addWidget(self.problem)
        grade_col = QVBoxLayout()
        grade_col.addWidget(label("Grade", "muted"))
        grade_col.addWidget(self.grade)
        grade_col.addStretch(1)
        row = hbox(left, grade_col, right, spacing=16, margins=(14, 10, 14, 10))
        row.setStretch(2, 1)
        self.setLayout(row)
        self._changed()

    def values(self) -> tuple[str, str]:
        return self.grade.text(), self.comment.toPlainText()

    def dirty(self) -> bool:
        g, c = self.values()
        return (g.strip(), _norm(c)) != (self.entry.grade, self.entry.comments)

    def blocked(self) -> str:
        """Why this card's values can't be saved, or ""."""
        return refusal(*self.values())

    def edit(self) -> Edit:
        g, c = self.values()
        return Edit(self.entry.key, g, c)

    def revert(self) -> None:
        for w in (self.grade, self.comment):
            w.blockSignals(True)
        self.grade.setText(self.entry.grade)
        self.comment.setPlainText(self.entry.comments)
        for w in (self.grade, self.comment):
            w.blockSignals(False)
        self._changed()

    def _changed(self, *_):
        g, c = self.values()
        missing = not (g.strip() or c.strip())
        state = "missing" if missing else "changed" if self.dirty() else ""
        restyle(self, state=state)
        self.state.setText("<b>⚠ No grade or comment</b>" if missing else
                           "<b>● Changed, not saved</b>" if state == "changed" else
                           "✓ Grade, no comment" if not c.strip() else
                           "✓ Comment only" if not g.strip() else "✓ Filled in")
        why = self.blocked()
        notes = [f"<b>✕ {why}</b>"] if why else [f"⚠ {w}" for w in grade_warnings(g)]
        self.problem.setText("<br>".join(notes))
        self.problem.setVisible(bool(notes))
        self.edited.emit()


def _norm(comments: str) -> str:
    return "\n".join(ln.strip() for ln in comments.strip().splitlines()).strip()


class FileCard(Card):
    """One grade file: what it is, then its students (built when first opened)."""
    changed = Signal()

    def __init__(self, path: Path, gf, stamp: Stamp, open_now: bool):
        super().__init__("secondary")
        self.path, self.gf, self.stamp, self.students = path, gf, stamp, []
        self.title = label("", "", wrap=True)
        self.n_badge, self.miss_badge, self.chg_badge = (badge(""), badge(""), badge("", "plain"))
        self.body.addLayout(hbox(self.title, self.n_badge, self.miss_badge, self.chg_badge))
        self.meta = QGridLayout()
        self.meta.setHorizontalSpacing(18)
        self.meta.setVerticalSpacing(4)
        self.meta_values = {}
        for r, k in enumerate(META):
            self.meta.addWidget(label(k, "muted"), r // 2, (r % 2) * 2)
            self.meta_values[k] = label("", "", wrap=True)
            self.meta.addWidget(self.meta_values[k], r // 2, (r % 2) * 2 + 1)
        self.meta.setColumnStretch(1, 1)
        self.meta.setColumnStretch(3, 1)
        self.body.addLayout(self.meta)
        self.toggle = button("", "link", self._toggle)
        self.save_btn = button("Save changes to file…", "secondary", None)
        self.undo_btn = button("Undo changes", "link", self.revert)
        self.body.addLayout(hbox(self.toggle, None, self.undo_btn, self.save_btn))
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        self.body.addLayout(self.list)
        self.open = False
        self.load(gf, stamp)
        if open_now:
            self._toggle()

    def load(self, gf, stamp: Stamp) -> None:
        """Show the file as read from disk (again)."""
        self.gf, self.stamp = gf, stamp
        clear(self.list)
        self.students = []
        if self.open:
            self._build()
        self._meta()
        self._update()

    def _meta(self):
        gf, path = self.gf, self.path
        when = datetime.fromtimestamp(self.stamp.mtime_ns / 1e9).strftime("%d %b %Y, %H:%M:%S")
        rows = (("Assignment", f"{gf.assignment_title or '(no title)'} · ID {gf.assignment_id}"),
                ("Section", f"{gf.section_title or '(none)'}"
                            + (f" · ID {gf.section_id}" if gf.section_id else "")),
                ("Instructor", gf.instructor or "—"),
                ("Folder", str(path.parent)),
                ("Last changed", when),
                ("Size", f"{self.stamp.size:,} bytes"))
        for k, v in rows:
            self.meta_values[k].setText(v)

    def _build(self):
        for entry in self.gf.students:
            card = StudentCard(entry)
            card.edited.connect(self._update)
            self.students.append(card)
            self.list.addWidget(card)
            card.setVisible(self.open)

    def _toggle(self):
        self.open = not self.open
        if self.open and not self.students:
            self._build()
        for c in self.students:
            c.setVisible(self.open)
        self._update()

    def dirty(self) -> list[StudentCard]:
        return [c for c in self.students if c.dirty()]

    def blocked(self) -> list[str]:
        return [f"{c.entry.name}: {c.blocked()}" for c in self.dirty() if c.blocked()]

    def revert(self):
        for c in self.dirty():
            c.revert()

    def _update(self, *_):
        gf, n = self.gf, len(self.gf.students)
        if self.students:
            missing = sum(1 for c in self.students if not any(v.strip() for v in c.values()))
        else:
            missing = sum(1 for e in gf.students if e.blank)
        changed = len(self.dirty())
        self.title.setText(f"<b style='font-size:16px'>{self.path.name}</b>")
        self.n_badge.setText(f"{n} student{'s' * (n != 1)}")
        self.miss_badge.setText(f"⚠ {missing} missing" if missing else "✓ All filled in")
        restyle(self.miss_badge, kind="warn" if missing else "plain")
        self.chg_badge.setText(f"● {changed} changed")
        self.chg_badge.setVisible(bool(changed))
        self.toggle.setText(("Hide students" if self.open else f"Show {n} students"))
        self.save_btn.setEnabled(bool(changed) and not self.blocked())
        self.undo_btn.setVisible(bool(changed))
        self.changed.emit()


class Ask:
    """The questions this screen asks; tests replace them."""

    @staticmethod
    def save(parent, card: FileCard) -> bool:
        names = [c.entry.name for c in card.dirty()]
        shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
        return QMessageBox.question(
            parent, "Save changes to the file?",
            f"Write the new grades and comments for {shown} into {card.path.name}? Only "
            "those lines change.", QMessageBox.Save | QMessageBox.Cancel,
            QMessageBox.Save) == QMessageBox.Save

    @staticmethod
    def unsaved(parent, n: int) -> str:
        """'save', 'discard' or 'cancel'."""
        box = QMessageBox(QMessageBox.Question, "Unsaved changes",
                          f"{n} file{'s have' if n != 1 else ' has'} changes that aren't saved. "
                          "Painter posts only what is saved in the files.", parent=parent)
        save = box.addButton("Save and continue", QMessageBox.AcceptRole)
        discard = box.addButton("Discard changes", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        return {save: "save", discard: "discard"}.get(box.clickedButton(), "cancel")

    @staticmethod
    def changed_on_disk(parent, name: str) -> str:
        """'reload', 'overwrite' or 'cancel'."""
        box = QMessageBox(QMessageBox.Warning, "The file changed",
                          f"{name} was changed by another program after Painter read it.",
                          parent=parent)
        box.setInformativeText("Reload it to see those changes (yours here are lost), or "
                               "write your changes into it (the other changes to the file "
                               "are kept, except for these students' grades and comments).")
        reload = box.addButton("Reload from disk", QMessageBox.RejectRole)
        over = box.addButton("Write my changes into it", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        return {reload: "reload", over: "overwrite"}.get(box.clickedButton(), "cancel")


class GradesPreviewView(View):
    name = "grades_preview"
    section = "grades"
    title = "Preview and edit"

    def __init__(self, win):
        super().__init__(win)
        self.page.addWidget(heading(
            "Preview and edit", "Each file as it is saved now. Change a grade or comment, "
            "then save it to the file. Nothing is sent to Canvas yet.")[0])
        steps = StepBar()
        steps.set(2)
        self.page.addWidget(steps)
        self.overlap = Banner()
        self.page.addWidget(self.overlap)
        self.banner = Banner()
        self.page.addWidget(self.banner)
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(16)
        self.page.addLayout(self.cards_box)
        foot = Card("primary")
        foot.setObjectName("summary")
        self.foot_text = label("", wrap=True)
        self.check_btn = button("Check against Canvas", "primary", self.check)
        foot.body.addLayout(hbox(self.foot_text, button("Back", "", self.back), self.check_btn))
        self.page.addWidget(foot)
        self.page.addStretch(1)
        self.cards: list[FileCard] = []
        self.allow_dup, self._checking = False, False
        self.ask = Ask
        r = win.runner
        r.finished.connect(self._checked)
        r.failed.connect(self._failed)

    # ---- showing the files ----
    def enter(self, paths=None, allow_dup=None, **kw):
        if allow_dup is not None:
            self.allow_dup = allow_dup
        if paths is not None:
            self._show([Path(p) for p in paths])
        else:
            self._reload_untouched()
        self._summary()

    def _show(self, paths: list[Path]):
        clear(self.cards_box)
        self.cards = []
        self.banner.set("info")
        bad = []
        for path in paths:
            try:
                gf, stamp = parse_grade_file(path), Stamp.of(path)
            except (GradeFileError, OSError, UnicodeDecodeError) as exc:
                bad.append(f"{path.name}: {str(exc).split(': ', 1)[-1]}")
                continue
            card = FileCard(path, gf, stamp, open_now=len(paths) == 1)
            card.save_btn.clicked.connect(lambda _=False, c=card: self.save(c))
            card.changed.connect(self._summary)
            self.cards.append(card)
            self.cards_box.addWidget(card)
        if bad:
            self.banner.set("error", "Some files can't be read", "<br>".join(bad))
        self._overlap()

    def _overlap(self):
        text = overlap_text([c.gf for c in self.cards])
        if text:
            self.overlap.set("attention", "These files overlap", text)
        else:
            self.overlap.set("info")

    def _reload_untouched(self):
        """Back from Review: files changed on disk since are shown afresh,
        unless they have changes here that aren't saved."""
        for card in self.cards:
            try:
                now = Stamp.of(card.path)
                if now != card.stamp and not card.dirty():
                    card.load(parse_grade_file(card.path), now)
            except (GradeFileError, OSError, UnicodeDecodeError):
                continue

    def _summary(self, *_):
        n = sum(len(c.gf.students) for c in self.cards)
        dirty = [c for c in self.cards if c.dirty()]
        missing = sum(1 for c in self.cards for e in c.gf.students if e.blank)
        text = (f"<b>{len(self.cards)} file{'s' * (len(self.cards) != 1)}</b> · {n} students"
                + (f" · {missing} with no grade or comment" if missing else ""))
        if dirty:
            text += (f"<br><b>● Unsaved changes in {len(dirty)} file"
                     f"{'s' * (len(dirty) != 1)}</b>: they are saved before checking.")
        self.foot_text.setText(text)
        self.check_btn.setEnabled(bool(self.cards) and not self._checking)

    def dirty_cards(self) -> list[FileCard]:
        return [c for c in self.cards if c.dirty()]

    # ---- saving ----
    def save(self, card: FileCard, ask: bool = True) -> bool:
        """Write one card's changes into its file; True when saved (or nothing to save)."""
        if not card.dirty():
            return True
        blocked = card.blocked()
        if blocked:
            self.banner.set("error", f"Can't save {card.path.name}", "<br>".join(blocked))
            return False
        if ask and self.session.settings.confirm_save and not self.ask.save(self, card):
            return False
        edits = [c.edit() for c in card.dirty()]
        try:
            gf = save_edits(card.path, edits, card.stamp)
        except FileChanged:
            choice = self.ask.changed_on_disk(self, card.path.name)
            if choice == "reload":
                return self._reload(card)
            if choice != "overwrite":
                return False
            try:
                gf = save_edits(card.path, edits, None)
            except (EditRefused, GradeFileError, OSError, UnicodeDecodeError) as exc:
                return self._save_failed(card, exc)
        except (EditRefused, GradeFileError, OSError, UnicodeDecodeError) as exc:
            return self._save_failed(card, exc)
        card.load(gf, Stamp.of(card.path))
        self.banner.set("ok", f"Saved {card.path.name}",
                        f"{len(edits)} student{'s' * (len(edits) != 1)} updated in the file.")
        return True

    def _reload(self, card: FileCard) -> bool:
        try:
            card.load(parse_grade_file(card.path), Stamp.of(card.path))
        except (GradeFileError, OSError, UnicodeDecodeError) as exc:
            return self._save_failed(card, exc)
        self.banner.set("info", f"Reloaded {card.path.name}", "Your changes to it were "
                        "dropped. Make them again if you still want them.")
        return False

    def _save_failed(self, card: FileCard, exc) -> bool:
        self.banner.set("error", f"{card.path.name} wasn't saved",
                        str(exc).split(": ", 1)[-1])
        return False

    def settle(self) -> bool:
        """Before checking or leaving: save or discard unsaved changes. False: stay."""
        dirty = self.dirty_cards()
        if not dirty:
            return True
        choice = "save"
        if self.session.settings.confirm_save:
            choice = self.ask.unsaved(self, len(dirty))
        if choice == "cancel":
            return False
        if choice == "discard":
            for c in dirty:
                c.revert()
            return True
        return all(self.save(c, ask=False) for c in dirty)

    def unsaved_ok(self, closing: bool = False) -> bool:
        return self.win.current is not self or self.settle()

    # ---- on to Review ----
    def back(self):
        if self.settle():
            self.win.go("grades_pick")

    def check(self):
        if not self.cards or self.win.runner.running or not self.settle():
            return
        self.banner.set("info", "Checking against Canvas…",
                        "Reading the saved files again; nothing is sent.")
        self._checking = True
        self.check_btn.setEnabled(False)
        self.win.runner.start(plan_grades, self.session.canvas,
                              [c.path for c in self.cards], None, self.allow_dup)

    def _mine(self):
        return self.win.current is self and self._checking

    def _checked(self, plans):
        if not self._mine():
            return
        self._checking = False
        self.check_btn.setEnabled(True)
        self.banner.set("info")
        self.win.go("grades_review", plans=plans, allow_dup=self.allow_dup)

    def _failed(self, exc):
        if not self._mine():
            return
        self._checking = False
        self.check_btn.setEnabled(True)
        show_problem(self.banner, exc, self.win.open_settings)
