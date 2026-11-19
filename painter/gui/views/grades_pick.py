"""Screen 6: add grade files; each is read at once and its problems shown."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFrame, QGridLayout

from painter.gui.views import View
from painter.gui.widgets import (
    Banner, Card, SearchBox, StepBar, button, clear, heading, hbox, hidden_note, label,
    show_problem,
)
from painter.services.grade_files import GradeFileError, find_grade_files, parse_grade_file
from painter.services.grading import plan_grades


class DropZone(QFrame):
    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        self.dropped.emit([u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()])


def read_file(path: Path):
    """(GradeFile | None, message)."""
    try:
        return parse_grade_file(path), ""
    except GradeFileError as exc:
        return None, str(exc).split(": ", 1)[-1]
    except (OSError, UnicodeDecodeError) as exc:
        return None, str(exc)


class GradesPickView(View):
    name = "grades_pick"
    section = "grades"
    title = "Post grades"

    def __init__(self, win):
        super().__init__(win)
        self.page.addWidget(heading("Post grades", "Add filled-in grade files. Nothing is sent "
                                    "until you've reviewed every change and confirmed.")[0])
        self.page.addWidget(StepBar())
        self.page.addWidget(self._saved_card())
        drop = DropZone()
        drop.dropped.connect(self.add)
        lay = hbox(label("<span style='font-size:18px; font-weight:700'>Drop grade files "
                         "here</span><br><span style='color:#5E574C'>Grade files kept elsewhere, e.g. "
                         "A2-DATE_Grading-27-1.txt</span>", wrap=True),
                   button("Choose files…", "secondary", self.choose),
                   margins=(24, 22, 24, 22))
        drop.setLayout(lay)
        self.page.addWidget(drop)
        card = Card()
        self.count = label("No files yet", "h2")
        card.body.addWidget(self.count)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        card.body.addLayout(self.grid)
        self.page.addWidget(card)
        self.dup = QCheckBox("Post a comment even if the same text is already on the submission")
        self.page.addWidget(self.dup)
        self.page.addWidget(label("Off: repeated comments are skipped, so posting a file twice "
                                  "never doubles them.", "muted"))
        self.banner = Banner()
        self.page.addWidget(self.banner)
        self.check_btn = button("Check against Canvas", "primary", self.check)
        self.page.addLayout(hbox(self.check_btn, None))
        self.page.addStretch(1)
        self.files: dict[Path, tuple] = {}
        r = win.runner
        r.finished.connect(self._checked)
        r.failed.connect(self._failed)

    # ---- grade files Painter keeps (Make grade files saves them here) ----
    def _saved_card(self) -> Card:
        card = Card()
        self.saved_head = label("Saved grade files", "h2")
        self.rescan_btn = button("↻", "icon", self.scan, "Look in the folder again")
        self.rescan_btn.setAccessibleName("Look for grade files again")
        card.body.addLayout(hbox(self.saved_head, self.rescan_btn, None,
                                 button("Make grade files…", "link",
                                        lambda: self.win.go("grade_files_make"))))
        self.saved_note = label("", "muted", wrap=True)
        card.body.addWidget(self.saved_note)
        self.saved_search = SearchBox("grade files (name, assignment, section)")
        self.saved_search.textChanged.connect(self._filter_saved)
        self.saved_match = label("", "muted")
        card.body.addLayout(hbox(self.saved_search, self.saved_match))
        self.saved_grid = QGridLayout()
        self.saved_grid.setHorizontalSpacing(14)
        self.saved_grid.setVerticalSpacing(6)
        card.body.addLayout(self.saved_grid)
        self.saved: dict[Path, QCheckBox] = {}
        self.saved_rows: dict = {}
        self.saved_groups: dict = {}
        return card

    def grades_root(self) -> Path:
        return self.session.grades_root

    def folders(self) -> list[tuple[Path, bool]]:
        """Where to look: Painter's grade-files folder (with its course folders), and
        any folder chosen for a course in Make grade files (that folder only)."""
        out = [(self.grades_root(), True)]
        for f in (self.session.settings.course_folders or {}).values():
            out.append((Path(f), False))
        return out

    def scan(self):
        """List the saved grade files: this course's first, then newest first."""
        mine = self._course_folder()
        found: dict[str, Path] = {}
        for folder, deep in self.folders():
            for p in find_grade_files(folder, recursive=deep):
                found.setdefault(str(p.resolve()), p)

        def order(p: Path):
            try:
                age = -p.stat().st_mtime
            except OSError:
                age = 0
            return (p.parent != mine, age)
        paths = sorted(found.values(), key=order)
        clear(self.saved_grid)
        self.saved, self.saved_rows, self.saved_groups = {}, {}, {}
        for path in paths:
            group = "This course" if path.parent == mine else _folder_label(path,
                                                                            self.grades_root())
            if group not in self.saved_groups:
                head = label(f"<b>{group}</b>", "muted")
                self.saved_grid.addWidget(head, self.saved_grid.rowCount(), 0, 1, 3)
                self.saved_groups[group] = head
            self._saved_row(path, group)
        self.saved_grid.setColumnStretch(1, 1)
        n = len(paths)
        self.saved_head.setText(f"Saved grade files  ·  {n}" if n else "Saved grade files")
        self.saved_search.setVisible(bool(n))
        where = "Painter's grade-files folder" + (
            " and the folders chosen in Make grade files" if len(self.folders()) > 1 else "")
        self.saved_note.setText(
            f"Tick a file to post it. These are the files in {where}." if n else
            f"None yet in {where}. Use Make grade files to create blank ones to fill in.")
        self._filter_saved()

    def _filter_saved(self, *_):
        q = self.saved_search
        visible_groups, shown, hidden_ticked = set(), 0, 0
        for path, (widgets, group, text) in self.saved_rows.items():
            ok = q.matches(path.name, text, group)
            for w in widgets:
                w.setVisible(ok)
            if ok:
                visible_groups.add(group)
                shown += 1
            elif self.saved[path].isChecked():
                hidden_ticked += 1
        for group, head in self.saved_groups.items():
            head.setVisible(group in visible_groups)
        self.saved_match.setText(
            "No files match" if q.active and self.saved_rows and not shown else
            hidden_note(hidden_ticked, f"ticked file{'s' * (hidden_ticked != 1)}"))

    def _course_folder(self) -> Path | None:
        from painter.gui.views.grade_files_make import course_grades_folder
        course = self.session.course
        if not course:
            return None
        chosen = (self.session.settings.course_folders or {}).get(str(course.id))
        return Path(chosen) if chosen else course_grades_folder(self.grades_root(), course)

    def _saved_row(self, path: Path, group: str):
        gf, msg = read_file(path)
        r = self.saved_grid.rowCount()
        box = QCheckBox(path.name)
        box.setAccessibleName(f"Post {path.name}")
        box.setChecked(path in self.files)
        box.setEnabled(gf is not None)
        box.toggled.connect(lambda on, p=path: self._tick(p, on))
        self.saved[path] = box
        self.saved_grid.addWidget(box, r, 0)
        if gf is None:
            what = f"<b>✕ Can't be read · {msg}</b>"
        else:
            total = len(gf.entries) + gf.blank_entries
            what = (f"{gf.assignment_title or gf.assignment_id} · "
                    f"{gf.section_title or 'no section'} · {len(gf.entries)} of {total} filled in")
        what_label = label(what, "", wrap=True)
        self.saved_grid.addWidget(what_label, r, 1)
        try:
            when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d %b %H:%M")
        except OSError:
            when = "?"
        when_label = label(f"changed {when}", "muted")
        self.saved_grid.addWidget(when_label, r, 2)
        self.saved_rows[path] = ([box, what_label, when_label], group, what)

    def _tick(self, path: Path, on: bool):
        if on:
            self.files[path] = read_file(path)
        else:
            self.files.pop(path, None)
        self._filter_saved()
        self._refresh()

    def _mine(self):
        return self.win.current is self and getattr(self, "_checking", False)

    def enter(self, **kw):
        self.scan()
        self._refresh()

    def choose(self):
        start = self.session.settings.grades_folder or str(self.grades_root())
        names, _ = QFileDialog.getOpenFileNames(self, "Grade files", start, "Grade files (*.txt)")
        self.add(names)

    def add(self, names):
        for n in names:
            p = Path(n)
            self.files[p] = read_file(p)
            box = self.saved.get(p)
            if box is not None and self.files[p][0] is not None:
                box.blockSignals(True)
                box.setChecked(True)
                box.blockSignals(False)
        if names:
            self.session.settings.grades_folder = str(Path(names[0]).parent)
            self.session.save()
        self._refresh()

    def remove(self, path):
        self.files.pop(path, None)
        box = self.saved.get(path)
        if box is not None:
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self._refresh()

    def _refresh(self):
        clear(self.grid)
        for r, (path, (gf, msg)) in enumerate(self.files.items()):
            ok = gf is not None
            self.grid.addWidget(label("✓" if ok else "✕"), r, 0)
            note = (f"<span style='color:#5E574C'>{path.parent}</span>" if ok else
                    f"<b>✕ Can't be read · {msg}</b>")
            self.grid.addWidget(label(f"<b>{path.name}</b><br>{note}", wrap=True), r, 1)
            what = (f"{gf.assignment_title or gf.assignment_id} · {gf.section_title or 'no section'}"
                    if ok else "Fix it and add it again")
            self.grid.addWidget(label(what), r, 2)
            self.grid.addWidget(label(f"{len(gf.entries) + gf.blank_entries} students · {len(gf.entries)} filled in"
                                     if ok else "—", "muted"), r, 3)
            rm = button("✕", "", lambda _=False, p=path: self.remove(p), "Remove")
            rm.setAccessibleName(f"Remove {path.name}")
            self.grid.addWidget(rm, r, 4)
        self.grid.setColumnStretch(1, 1)
        n = len(self.files)
        self.count.setText(f"{n} file{'s' * (n != 1)}" if n else "No files yet")

    def missing(self) -> str:
        if not self.files:
            return "Add at least one grade file."
        bad = [p.name for p, (gf, _) in self.files.items() if gf is None]
        if bad:
            return f"Remove or fix {', '.join(bad)} first: it can't be read."
        return ""

    def check(self):
        why = self.missing()
        if why:
            self.banner.set("attention", "Not yet", why)
            return
        if self.win.runner.running:
            return
        self.banner.set("info", "Checking against Canvas…", "Reading only; nothing is sent.")
        self._checking = True
        self.check_btn.setEnabled(False)
        self.win.runner.start(plan_grades, self.session.canvas, list(self.files), None,
                              self.dup.isChecked())

    def _checked(self, plans):
        if not self._mine():
            return
        self._checking = False
        self.check_btn.setEnabled(True)
        self.banner.set("info")
        self.win.go("grades_review", plans=plans, allow_dup=self.dup.isChecked())

    def _failed(self, exc):
        if not self._mine():
            return
        self._checking = False
        self.check_btn.setEnabled(True)
        show_problem(self.banner, exc, self.win.open_settings)


def _folder_label(path: Path, root: Path) -> str:
    try:
        rel = path.parent.relative_to(root).as_posix()
    except ValueError:
        rel = str(path.parent)
    return f"Other folder: {rel}" if rel not in ("", ".") else "Grade-files folder"
