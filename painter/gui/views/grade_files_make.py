"""Make grade files: blank files to fill in, one per section for each assignment,
kept in Painter's grade-files folder so Post grades can list them."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHeaderView, QLineEdit, QTableWidget, QTableWidgetItem,
    QWidget,
)

from painter.domain.freshness import classify, needs_check
from painter.domain.naming import slug
from painter.domain.roster import Roster
from painter.gui.problems import short_reason
from painter.gui.section_filter import InstructorFilter
from painter.gui.views import View
from painter.gui.views.download_done import open_path
from painter.gui.views.download_setup import DAMAGED, load_choices
from painter.config import exposed_in_repo
from painter.gui.widgets import (
    Banner, Card, FlowLayout, FolderPicker, FreshnessTag, SearchBox, button, clear, due_item,
    filter_rows, heading, hbox, label, show_problem,
)
from painter.gui.worker import TaskRunner
from painter.services.grade_files import (
    GradeFilesBatch, grade_file_name, make_grade_files_for, parse_term_name,
)
from painter.services.snapshots import assignments_from_data, assignments_to_data


def course_grades_folder(root: Path, course) -> Path:
    """One folder per course inside the grade-files folder."""
    return Path(root) / slug(course.code or course.name, 60)


class GradeFilesMakeView(View):
    name = "grade_files_make"
    section = "gradefiles"
    title = "Make grade files"

    def __init__(self, win):
        super().__init__(win)
        self.page.addWidget(heading(
            "Make grade files", "Blank files to fill in: one for each section, for each "
            "assignment. Painter keeps them in its grade-files folder, and Post grades "
            "lists them.")[0])
        self.banner = Banner()
        self.page.addWidget(self.banner)
        self.page.addWidget(self._assignments_card())
        self.page.addWidget(self._sections_card())
        self.page.addWidget(self._term_card())
        self.page.addWidget(self._where_card())
        self.summary = label("", "h2")
        self.make_btn = button("Make grade files", "primary", self.make)
        self.page.addLayout(hbox(self.summary, None, self.make_btn))
        self.done = Banner()
        self.page.addWidget(self.done)
        self.post_btn = button("Post grades from these files…", "secondary", self._to_post)
        self.post_btn.setVisible(False)
        self.page.addLayout(hbox(self.post_btn, None))
        self.page.addStretch(1)
        self.lookup = TaskRunner(self)
        self.lookup.finished.connect(self._loaded)
        self.lookup.failed.connect(self._lists_failed)
        self.maker = TaskRunner(self)
        self.maker.finished.connect(self._made)
        self.maker.cancelled.connect(self._made)
        self.maker.failed.connect(self._make_failed)
        self.loaded_for, self.roster, self.lists_at = None, None, None
        self.checking, self.error, self.written = False, "", []
        self.section_buttons: dict[int, object] = {}

    # ---- layout ----
    def _assignments_card(self) -> Card:
        c = Card()
        self.a_head = label("1. Assignments", "h2")
        self.a_all = button("Select all", "link", self._toggle_assignments)
        c.body.addLayout(hbox(self.a_head, None, self.a_all))
        self.tag = FreshnessTag()
        self.tag.refresh_requested.connect(self.refresh)
        c.body.addWidget(self.tag)
        self.a_search = SearchBox("assignments")
        self.a_search.textChanged.connect(self._changed)
        self.a_note = label("", "muted")
        c.body.addLayout(hbox(self.a_search, self.a_note))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Assignment", "Due"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(200)
        self.table.itemChanged.connect(self._changed)
        c.body.addWidget(self.table)
        return c

    def _sections_card(self) -> Card:
        c = Card()
        self.s_head = label("2. Sections", "h2")
        self.s_all = button("Select all", "link", self._toggle_sections)
        c.body.addLayout(hbox(self.s_head, None, self.s_all))
        c.body.addWidget(label("Each file lists the section's students, with their names "
                               "and Canvas IDs filled in.", "muted", wrap=True))
        self.who = InstructorFilter()
        self.who.changed.connect(self._changed)
        c.body.addWidget(self.who)
        box = QWidget()
        self.chips = FlowLayout(box)
        c.body.addWidget(box)
        return c

    def _term_card(self) -> Card:
        c = Card()
        c.body.addWidget(label("3. Academic year and semester", "h2"))
        self.ay = QLineEdit()
        self.ay.setPlaceholderText("e.g. 27")
        self.ay.setAccessibleName("Academic year, two digits")
        self.ay.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{2}|\d{4}")))
        self.term = QLineEdit()
        self.term.setPlaceholderText("e.g. 1")
        self.term.setAccessibleName("Semester number")
        self.term.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d")))
        for w in (self.ay, self.term):
            w.setMaximumWidth(90)
            w.textEdited.connect(self._term_edited)
        c.body.addLayout(hbox(label("AY"), self.ay, label("Semester"), self.term, None))
        self.term_note = label("", "muted", wrap=True)
        c.body.addWidget(self.term_note)
        return c

    def _where_card(self) -> Card:
        c = Card()
        self.reset_btn = button("Use Painter's grade-files folder", "link", self._default_folder)
        c.body.addLayout(hbox(label("4. Saved to", "h2"), None, self.reset_btn))
        self.where = FolderPicker("Folder for the grade files")
        self.where.changed.connect(self._folder_edited)
        self.open_btn = button("Open folder", "", self._open_folder)
        row = hbox(self.where, self.open_btn)
        row.setStretch(0, 1)
        c.body.addLayout(row)
        self.where_note = label("", "muted", wrap=True)
        c.body.addWidget(self.where_note)
        self.force = QCheckBox("Replace files that already exist (their grades are lost)")
        self.force.toggled.connect(self._changed)
        c.body.addWidget(self.force)
        c.body.addWidget(label("Off: a file already there is kept as it is, so grades you "
                               "have typed in are never overwritten.", "muted", wrap=True))
        return c

    # ---- loading: cached first, then confirmed ----
    def enter(self, **kw):
        course = self.session.course
        self._show_folder()
        self._fill_term(course)
        if self.loaded_for != course.id:
            self.loaded_for, self.roster, self.lists_at = None, None, None
            self.done.set("info")
            self.post_btn.setVisible(False)
            self._from_cache(course.id)
        if self.loaded_for is None or needs_check("assignments", self.lists_at):
            self.refresh()
        self._tag()
        self._changed()

    # ---- academic year and semester ----
    def _fill_term(self, course):
        """Saved for this course > read from the term name > blank (required)."""
        saved = (self.session.settings.course_terms or {}).get(str(course.id)) or {}
        parsed = parse_term_name(course.term)
        ay, term = saved.get("ay") or "", saved.get("term") or ""
        if not (ay and term) and parsed:
            ay, term = parsed
        self.ay.setText(ay)
        self.term.setText(term)
        self.term_parsed = parsed
        self.term_name = course.term or ""
        self._term_text()

    def _term_edited(self, *_):
        cid = str(self.session.course.id)
        terms = dict(self.session.settings.course_terms or {})
        if self.term_ok():
            terms[cid] = {"ay": self.ay.text()[-2:], "term": self.term.text()}
        else:
            terms.pop(cid, None)
        self.session.settings.course_terms = terms
        self.session.save()
        self._term_text()
        self._changed()

    def term_ok(self) -> bool:
        return self.ay.hasAcceptableInput() and self.term.hasAcceptableInput()

    def _term_text(self):
        name = self.term_name or "(no term name)"
        if self.term_parsed and (self.ay.text()[-2:], self.term.text()) == self.term_parsed:
            note = f"From the course term “{name}”. Change them if that's wrong."
        elif self.term_parsed:
            note = f"Typed in for this course (the term “{name}” reads as " \
                   f"AY{self.term_parsed[0]}, semester {self.term_parsed[1]})."
        else:
            note = (f"Painter can't read these from the course term “{name}”. Enter the "
                    "two-digit academic year and the semester number (as --ay 27 --term 1 "
                    "on the command line); Painter remembers them for this course.")
        if self.term_ok():
            note += "  Files are named like " + grade_file_name(
                "A1", "DATE", self.ay.text()[-2:], self.term.text()) + "."
        self.term_note.setText(note)
        for w in (self.ay, self.term):
            w.setProperty("invalid", not w.hasAcceptableInput())
            w.style().unpolish(w)
            w.style().polish(w)

    def default_folder(self) -> Path:
        return course_grades_folder(self.session.grades_root, self.session.course)

    def folder(self) -> Path | None:
        """The folder chosen for this course, else Painter's (grade-files/<course>)."""
        text = self.where.path()
        return Path(text).expanduser() if text else None

    def _show_folder(self):
        chosen = (self.session.settings.course_folders or {}).get(str(self.session.course.id))
        self.where.edit.blockSignals(True)
        self.where.set_path(chosen or str(self.default_folder()))
        self.where.edit.blockSignals(False)
        self._folder_note()

    def _folder_edited(self, *_):
        folders = dict(self.session.settings.course_folders or {})
        path, cid = self.folder(), str(self.session.course.id)
        if path is None or path == self.default_folder():
            folders.pop(cid, None)
        else:
            folders[cid] = str(path)
        self.session.settings.course_folders = folders
        self.session.save()
        self._folder_note()
        self._changed()

    def _default_folder(self):
        self.where.set_path(str(self.default_folder()))

    def _folder_note(self):
        path = self.folder()
        own = path is not None and path == self.default_folder()
        self.reset_btn.setVisible(not own)
        if path is None:
            note = "Choose a folder for the grade files."
        elif exposed_in_repo(path):
            note = ("⚠ This folder is inside the Painter folder but not one git ignores, so "
                    "grade files saved here could be committed. Use the grade-files folder.")
        elif own:
            note = "Painter's grade-files folder for this course (ignored by git)."
        else:
            note = ("Your folder for this course; Painter remembers it, and Post grades "
                    "lists the grade files in it.")
        self.where_note.setText(note)

    def _from_cache(self, cid: int):
        a, r = (self.session.cached(k, cid) for k in ("assignments", "rosters"))
        try:
            self._show(assignments_from_data(a.data), Roster.from_data(r.data))
            self.lists_at, self.loaded_for = min(a.fetched_at, r.fetched_at), cid
        except DAMAGED:
            self.table.setRowCount(0)
            clear(self.chips)
            self.section_buttons = {}
            self.banner.set("info", "Loading assignments and sections…")

    def refresh(self):
        if self.lookup.running or self.session.canvas is None:
            return
        self.checking, self.error = True, ""
        self._cid = self.session.course.id
        self._tag()
        tz = (self.session.settings.options or {}).get("tz") or None
        self.lookup.start(load_choices, self.session.canvas, self._cid, tz)

    def _loaded(self, result):
        assignments, roster = result
        tz = (self.session.settings.options or {}).get("tz") or None
        self.session.remember("assignments", self._cid, assignments_to_data(assignments, tz))
        e = self.session.remember("rosters", self._cid, roster.to_data())
        self.checking = False
        if self._cid != self.session.course.id:
            self.refresh()
            return
        self._show(assignments, roster)
        self.lists_at, self.loaded_for = e.fetched_at, self._cid
        self.banner.set("info")
        self._tag()
        self._changed()

    def _lists_failed(self, exc):
        self.checking, self.error = False, short_reason(exc)
        show_problem(self.banner, exc, self.win.open_settings)
        self._tag()

    def _tag(self):
        self.tag.set(classify("assignments", self.lists_at, self.checking, self.error))

    # ---- lists ----
    def _show(self, assignments, roster: Roster):
        """Fill both lists, keeping what is already chosen."""
        ticked, sections = set(self.chosen_assignments()), set(self.chosen_sections())
        self.table.blockSignals(True)
        self.table.setRowCount(len(assignments))
        for r, a in enumerate(assignments):
            it = QTableWidgetItem(a.name)
            it.setData(Qt.UserRole, a.id)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if a.id in ticked else Qt.Unchecked)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, due_item(a.due))
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)
        self.roster = roster
        clear(self.chips)
        self.section_buttons = {}
        for s in sorted(roster.sections, key=lambda x: x.get("name") or ""):
            if s["id"] in roster.catch_all:
                continue
            n = len(roster.users_of_section.get(s["id"], ()))
            b = button("", "chip")
            b.setCheckable(True)
            b.setChecked(s["id"] in sections)
            b._label = f"{s.get('name')}  ({n})" + self.who.tag_for(roster, s["id"])
            b.setEnabled(n > 0)
            b.toggled.connect(self._changed)
            self.section_buttons[s["id"]] = b
            self.chips.addWidget(b)
        self.who.set_sections(roster.instructors, self.section_buttons,
                              {s['id']: s.get('name') or '' for s in roster.sections})

    def chosen_assignments(self) -> list[int]:
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None and it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def chosen_sections(self) -> list[int]:
        return [sid for sid, b in self.section_buttons.items() if b.isChecked()]

    def _toggle_assignments(self):
        rows = [self.table.item(r, 0) for r in range(self.table.rowCount())
                if not self.table.isRowHidden(r)]
        want = Qt.Unchecked if rows and all(i.checkState() == Qt.Checked for i in rows) \
            else Qt.Checked
        self.table.blockSignals(True)
        for it in rows:
            it.setCheckState(want)
        self.table.blockSignals(False)
        self._changed()

    def _toggle_sections(self):
        shown = self.who.apply(self.section_buttons)
        usable = [b for b in shown if b.isEnabled()]
        want = not all(b.isChecked() for b in usable)
        for b in usable:
            b.blockSignals(True)
            b.setChecked(want)
            b.blockSignals(False)
        self._changed()

    def _changed(self, *_):
        na, ns = len(self.chosen_assignments()), len(self.chosen_sections())
        rows = self.table.rowCount()
        self.a_note.setText(filter_rows(self.table, self.a_search, 1))
        shown = [self.table.item(r, 0) for r in range(rows) if not self.table.isRowHidden(r)]
        self.a_head.setText(f"1. Assignments   ·   {na} of {rows} selected")
        self.a_all.setText(("Clear all" if shown and all(i.checkState() == Qt.Checked
                                                        for i in shown) else "Select all")
                           + (" shown" if self.a_search.active else ""))
        self.a_all.setEnabled(bool(shown))
        everywhere = [b for b in self.section_buttons.values() if b.isEnabled()]
        usable = [b for b in self.who.apply(self.section_buttons) if b.isEnabled()]
        self.s_head.setText(f"2. Sections   ·   {ns} of {len(everywhere)} selected")
        self.s_all.setText(self.who.select_text(bool(usable) and
                                                all(b.isChecked() for b in usable)))
        self.s_all.setEnabled(bool(usable))
        for b in self.section_buttons.values():
            b.setText(("✓ " if b.isChecked() else "+ ") + b._label)
        n = na * ns
        self.summary.setText(f"{n} file{'s' * (n != 1)}" + (
            f"  ·  {na} assignment{'s' * (na != 1)} × {ns} section{'s' * (ns != 1)}"
            if n else ""))
        self.make_btn.setEnabled(bool(n) and self.term_ok() and self.folder() is not None
                                 and not self.maker.running)

    # ---- making ----
    def missing(self) -> str:
        if not self.chosen_assignments():
            return "Pick at least one assignment."
        if not self.chosen_sections():
            return "Pick at least one section."
        if not self.term_ok():
            return "Enter the academic year (two digits) and the semester number."
        if self.folder() is None:
            return "Choose a folder for the grade files."
        return ""

    def make(self):
        why = self.missing()
        if why:
            self.done.set("attention", "Not yet", why)
            return
        if self.maker.running:
            return
        req = GradeFilesBatch(self.session.course.id, self.folder(),
                              tuple(self.chosen_assignments()), tuple(self.chosen_sections()),
                              self.force.isChecked(), self.ay.text()[-2:], self.term.text())
        self.make_btn.setEnabled(False)
        self.done.set("info", "Making grade files…", "Reading the roster and instructors.")
        self.maker.start(make_grade_files_for, self.session.canvas, req)

    def _made(self, result):
        self._changed()
        if result is None:
            return
        self.written = list(result.written) + list(result.kept)
        w, k = len(result.written), len(result.kept)
        names = "<br>".join(p.name for p in result.written[:12]) + (
            "<br>…" if w > 12 else "")
        kept = (f"<br><br>{k} already there and kept unchanged "
                "(tick “Replace files that already exist” to start them again)." if k else "")
        self.done.set("ok", f"{w} grade file{'s' * (w != 1)} made in {result.out_dir}",
                      (names + kept) or "Nothing new to write.")
        self.post_btn.setVisible(bool(self.written))

    def _make_failed(self, exc):
        self._changed()
        show_problem(self.done, exc, self.win.open_settings)

    def _open_folder(self):
        path = self.folder()
        if path is None:
            return
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.done.set("attention", "Can't open that folder", str(exc))
            return
        open_path(path)

    def _to_post(self):
        self.win.go("grades_pick")
