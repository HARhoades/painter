"""Screen 3: choose assignments, students, folder and options."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QHeaderView,
    QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from painter.config import default_download_root, exposed_in_repo
from painter.domain.naming import slug
from painter.domain.freshness import Freshness, classify, needs_check, oldest
from painter.domain.roster import Roster
from painter.gui.problems import short_reason
from painter.gui.student_picker import StudentPicker
from painter.gui.views import View
from painter.gui.widgets import (
    Banner, Card, FolderPicker, FoldButton, FreshnessTag, button, heading, hbox, label,
    show_problem,
)
from painter.gui.worker import TaskRunner
from painter.services.snapshots import (
    assignments_from_data, assignments_to_data, files_from_data, files_to_data,
)
from painter.services.submissions import (
    DownloadRequest, FileCount, assignment_listing, count_from, file_counts,
)

STACK_BELOW = 900        # narrower than this (px): "Where and how" goes under the lists

ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
         "UTC", "Europe/London"]


def load_choices(canvas, course_id: int, tz: str | None):
    """Worker thread: what the screen needs from Canvas."""
    return assignment_listing(canvas, course_id, tz), Roster.load(canvas, course_id)


DAMAGED = (KeyError, TypeError, ValueError, AttributeError)    # a cache entry that won't read


def default_folder(course) -> str:
    return str(default_download_root() / slug(course.code or course.name, 60))


class DownloadSetupView(View):
    name = "download_setup"
    section = "download"
    title = "Download submissions"

    def __init__(self, win):
        super().__init__(win)
        self.page.addWidget(heading("Download submissions")[0])
        self.banner = Banner()
        self.page.addWidget(self.banner)
        cols = QWidget()
        left, right = QVBoxLayout(), QVBoxLayout()
        for c in (left, right):
            c.setSpacing(16)
        self.cols = QBoxLayout(QBoxLayout.LeftToRight, cols)
        self.cols.setContentsMargins(0, 0, 0, 0)
        self.cols.setSpacing(20)
        self.cols.addLayout(left, 3)
        self.cols.addLayout(right, 2)
        self.page.addWidget(cols)
        left.addWidget(self._assignments_card())
        left.addWidget(self._students_card())
        left.addStretch(1)
        right.addWidget(self._where_card())
        right.addWidget(self._summary_card())
        right.addStretch(1)
        self._runners()

    def _assignments_card(self) -> Card:
        a = Card()
        self.a_head = label("1. Assignments", "h2")
        a.body.addLayout(hbox(self.a_head, None, button("Select all", "link", self._select_all)))
        self.a_tag = FreshnessTag("Check the assignment list with Canvas now")
        self.a_tag.refresh_requested.connect(self.refresh_lists)
        a.body.addWidget(self.a_tag)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Assignment", "Due", "Submitted"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setMinimumSectionSize(60)
        hdr.sectionResized.connect(lambda *_: self.table.resizeRowsToContents())
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setMinimumHeight(220)
        self.table.setMinimumWidth(0)
        self.table.itemChanged.connect(self._assignments_changed)
        a.body.addWidget(self.table)
        return a

    def _students_card(self) -> Card:
        s = Card()
        s.body.addWidget(label("2. Students", "h2"))
        self.s_tag = FreshnessTag("Check sections and students with Canvas now")
        self.s_tag.refresh_requested.connect(self.refresh_lists)
        s.body.addWidget(self.s_tag)
        self.picker = StudentPicker()
        self.picker.changed.connect(self._schedule_count)
        s.body.addWidget(self.picker)
        return s

    def _where_card(self) -> Card:
        w = Card()
        w.body.addWidget(label("3. Where and how", "h2"))
        w.body.addWidget(label("Save to folder", "muted"))
        self.folder = FolderPicker("Save submissions to")
        self.folder.changed.connect(self._check_folder)
        w.body.addWidget(self.folder)
        self.folder_note = label("", "muted", wrap=True)
        self.folder_note.setVisible(False)
        w.body.addWidget(self.folder_note)
        w.body.addWidget(label("Folder layout", "muted"))
        self.per_student = QRadioButton("A folder per student")
        self.per_student.setToolTip("Assignment › Student › files")
        self.flat = QRadioButton("Flat: one folder")
        self.flat.setToolTip("All files together; names get the student's name and ID")
        grp = QButtonGroup(self)
        grp.addButton(self.per_student)
        grp.addButton(self.flat)
        self.per_student.setChecked(True)
        w.body.addWidget(self.per_student)
        w.body.addWidget(self.flat)
        self.by_section = QCheckBox("A folder per section")
        self.by_section.setChecked(True)
        self.by_section.setToolTip("Sort each assignment's files into a folder for the "
                                   "student's section")
        w.body.addWidget(self.by_section)
        self.layout_preview = label("", "muted", wrap=True)
        w.body.addWidget(self.layout_preview)
        for x in (self.flat, self.by_section):
            x.toggled.connect(self._show_layout)
        self._show_layout()
        self.keep_archives = QCheckBox("Don't unpack archives")
        self.keep_archives.setToolTip("Keep .zip files as they arrive. Off: unpacked next to "
                                      "the archive.")
        w.body.addWidget(self.keep_archives)
        self.more = FoldButton("More options")
        w.body.addWidget(self.more)
        self.more_box = QWidget()
        mb = QVBoxLayout(self.more_box)
        mb.setContentsMargins(18, 0, 0, 0)
        self.history = QCheckBox("Include earlier attempts")
        self.excel = QCheckBox("Excel log")
        self.excel.setChecked(True)
        self.tz = QComboBox()
        self.tz.setEditable(True)
        self.tz.addItems(ZONES)
        self.tz.setAccessibleName("Time zone for the manifest and log")
        for x in (self.history, self.excel):
            mb.addWidget(x)
        mb.addLayout(hbox(label("Times shown in", "muted"), self.tz, None))
        self.more_box.setVisible(False)
        self.more.toggled.connect(self._toggle_more)
        w.body.addWidget(self.more_box)
        self.history.toggled.connect(self._schedule_count)
        return w

    def _summary_card(self) -> Card:
        self.summary = Card("primary")
        self.summary.setObjectName("summary")
        self.summary_text = label("", wrap=True)
        self.start_btn = button("Start download", "primary", self.start)
        self.why = label("", "muted", wrap=True)
        self.summary.body.addWidget(self.summary_text)
        self.c_tag = FreshnessTag("Count the files again with Canvas now")
        self.c_tag.refresh_requested.connect(self.refresh_counts)
        self.summary.body.addWidget(self.c_tag)
        self.summary.body.addLayout(hbox(self.start_btn, None))
        self.summary.body.addWidget(self.why)
        return self.summary

    def resizeEvent(self, ev):                    # noqa: N802 - Qt naming
        """Two columns when there's room; one column on a narrow window."""
        super().resizeEvent(ev)
        want = (QBoxLayout.TopToBottom if self.width() < STACK_BELOW
                else QBoxLayout.LeftToRight)
        if self.cols.direction() != want:
            self.cols.setDirection(want)
            self.cols.setStretch(0, 3 if want == QBoxLayout.LeftToRight else 0)
            self.cols.setStretch(1, 2 if want == QBoxLayout.LeftToRight else 0)
        self.table.resizeRowsToContents()

    def _runners(self) -> None:
        self.lookup = TaskRunner(self)
        self.lookup.finished.connect(self._loaded)
        self.lookup.failed.connect(self._lists_failed)
        self.counter = TaskRunner(self)
        self.counter.finished.connect(self._counted)
        self.counter.cancelled.connect(self._counted)
        self.counter.failed.connect(self._counts_failed)
        self._recount = False
        self.count_timer = QTimer(self)
        self.count_timer.setSingleShot(True)
        self.count_timer.setInterval(500)
        self.count_timer.timeout.connect(self._count_now)
        self.tag_clock = QTimer(self)                 # "checked 2 min ago" turning stale
        self.tag_clock.setInterval(30_000)
        self.tag_clock.timeout.connect(self._tags)
        self.tag_clock.start()
        self.loaded_for = None
        self.count = None
        self.assignments: list = []
        self.gone: set[int] = set()                   # ticked, but no longer in Canvas
        self.lists_at = self.roster_at = None         # when Canvas last answered
        self.lists_checking, self.lists_error = False, ""
        self._lookup_course = None
        self._partial = FileCount({}, None)
        self._reset_counts()

    def _reset_counts(self) -> None:
        self.counts, self.counts_at = {}, {}          # per assignment: who has how many files
        self.fetching: set[int] = set()
        self.counts_error = ""
        self._counts_course = None

    def _check_folder(self, path: str):
        exposed = exposed_in_repo(path)
        self.folder_note.setText(
            "⚠ This folder is inside the Painter repository but not in an ignored folder, "
            "so student files saved here could be committed. Use the submissions folder." if exposed
            else "")
        self.folder_note.setVisible(exposed)

    # ---- loading: cached first, then confirmed with Canvas ----
    def enter(self, **kw):
        course = self.session.course
        opts = self.session.settings.options or {}
        if self.loaded_for != course.id:
            self._open_course(course, opts)
        elif not self.lookup.running and needs_check("assignments", self.lists_at):
            self.refresh_lists()
        self.flat.setChecked(bool(opts.get("flat")))
        self.keep_archives.setChecked(not opts.get("extract", True))
        self.by_section.setChecked(bool(opts.get("section_folders", True)))
        self.history.setChecked(bool(opts.get("history")))
        self.excel.setChecked(opts.get("excel_log", True))
        self.tz.setCurrentText(opts.get("tz") or ZONES[0])
        self._update_summary()

    def _open_course(self, course, opts):
        """Show what was cached for this course at once; ask Canvas if it's due."""
        self.loaded_for = None
        self.gone, self.assignments = set(), []
        self.lists_at = self.roster_at = None
        self.lists_error = ""
        self._reset_counts()
        self.table.setRowCount(0)
        self.folder.set_path(default_folder(course))
        a, r = (self.session.cached(k, course.id) for k in ("assignments", "rosters"))
        try:
            items, roster = assignments_from_data(a.data), Roster.from_data(r.data)
            self._fill_table(items, set(), set())
            self.picker.set_roster(roster)
            self.assignments, self.loaded_for = items, course.id
            self.lists_at, self.roster_at = a.fetched_at, r.fetched_at
            self.banner.set("info")
        except DAMAGED:                               # nothing cached, or unreadable
            self.banner.set("info", "Loading assignments and roster…")
        c = self.session.cached("filecounts", course.id)
        try:
            self.counts, self.counts_at = files_from_data(c.data)
        except DAMAGED:
            self._reset_counts()
        self._tags()
        if self.loaded_for is None or needs_check("assignments", self.lists_at) \
                or needs_check("rosters", self.roster_at):
            self.refresh_lists()
        self._assignments_changed()

    def refresh_lists(self):
        """Ask Canvas for the assignment list and roster (the ↻ buttons, and when due)."""
        if self.lookup.running or self.session.canvas is None:
            return
        opts = self.session.settings.options or {}
        self.lists_checking, self.lists_error = True, ""
        self._lookup_course = self.session.course.id
        self._tags()
        self.lookup.start(load_choices, self.session.canvas, self._lookup_course,
                          opts.get("tz") or None)

    def _loaded(self, result):
        assignments, roster = result
        cid, tz = self._lookup_course, (self.session.settings.options or {}).get("tz") or None
        a = self.session.remember("assignments", cid, assignments_to_data(assignments, tz))
        r = self.session.remember("rosters", cid, roster.to_data())
        self.lists_checking = False
        if cid != self.session.course.id:             # the user moved on: ask for this course
            self.refresh_lists()
            return
        self.lists_at, self.roster_at = a.fetched_at, r.fetched_at
        if self.loaded_for == cid:
            self.banner.set(*self._merge(assignments, roster))
        else:
            self.assignments, self.loaded_for = assignments, cid
            self._fill_table(assignments, set(), set())
            self.picker.set_roster(roster)
            self.banner.set("info")
        self._tags()
        self._assignments_changed()

    def _lists_failed(self, exc):
        self.lists_checking = False
        self.lists_error = short_reason(exc)
        show_problem(self.banner, exc, self.win.open_settings)
        self._tags()

    def _merge(self, assignments, roster) -> tuple:
        """Put Canvas's newer lists in place, keeping what the user has chosen.
        Returns the banner (kind, title, body) saying what changed, if anything."""
        ticked, before = set(self.chosen_assignments()), {a.id: a for a in self.assignments}
        now = {a.id for a in assignments}
        added, removed = now - before.keys(), set(before) - now
        self.gone = ticked & removed
        kept = assignments + [before[i] for i in sorted(self.gone)]
        self.assignments = assignments
        self._fill_table(kept, ticked, self.gone)
        dropped = self.picker.update_roster(roster)
        bits = [f"{len(added)} new assignment{'s' * (len(added) != 1)}" if added else "",
                f"{len(removed)} no longer in Canvas" if removed else "",
                f"{dropped} chosen section or student no longer exists" if dropped else ""]
        text = ", ".join(b for b in bits if b)
        return ("info", "Updated from Canvas", text + ".") if text else ("info", "", "")

    def _fill_table(self, items, ticked: set[int], gone: set[int]):
        self.table.blockSignals(True)
        self.table.setRowCount(len(items))
        for r, a in enumerate(items):
            note = ("\nNew Quiz: files come via Quiz uploads" if a.new_quiz else
                    "\nNo longer in Canvas: untick it to continue" if a.id in gone else "")
            name = QTableWidgetItem(a.name + note)
            name.setData(Qt.UserRole, a.id)
            if a.new_quiz:
                name.setFlags(Qt.ItemIsEnabled)
            else:
                name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                name.setCheckState(Qt.Checked if a.id in ticked else Qt.Unchecked)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(a.due or "No due date"))
            self.table.setItem(r, 2, QTableWidgetItem("—"))
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)

    def _tags(self, *_):
        """Refresh the three "how old is this" tags."""
        self.a_tag.set(classify("assignments", self.lists_at, self.lists_checking,
                                self.lists_error))
        self.s_tag.set(classify("rosters", self.roster_at, self.lists_checking,
                                self.lists_error))
        chosen = self.chosen_assignments()
        at = oldest(*(self.counts_at.get(a) for a in chosen))
        self.c_tag.set(classify("filecounts", at, bool(self.fetching), self.counts_error)
                       if chosen else None)

    # ---- choices ----
    def chosen_assignments(self) -> tuple[int, ...]:
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it.flags() & Qt.ItemIsUserCheckable and it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return tuple(out)

    def _select_all(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(Qt.Checked)
        self.table.blockSignals(False)
        self._assignments_changed()

    def _assignments_changed(self, *_):
        n = len(self.chosen_assignments())
        self.a_head.setText(f"1. Assignments   ·   {n} of "
                            f"{sum(not a.new_quiz for a in self.assignments)} selected")
        self._schedule_count()
        self._tags()

    def _toggle_more(self, on):
        self.more_box.setVisible(on)

    def _show_layout(self, *_):
        """Say where files will land, as Assignment › Section › Student › files."""
        flat = self.flat.isChecked()
        parts = ["Assignment"] + (["Section"] if self.by_section.isChecked() else []) \
            + ([] if flat else ["Student"]) + ["files"]
        self.layout_preview.setText(
            " › ".join(parts) + ("   (names get the student's name and ID)" if flat else ""))

    # ---- file counts: worked out here; Canvas is asked only for what's missing ----
    def _students(self) -> set[int] | None:
        return self.picker.student_ids() if self.picker.roster is not None else None

    def _schedule_count(self, *_):
        """A choice changed: re-total from what is known now, and, after a pause,
        ask Canvas about any chosen assignment that has no recent count."""
        self._apply_counts()
        self.count_timer.start()

    def _count_now(self):
        self._fetch_counts(force=False)

    def refresh_counts(self):
        """The ↻ button by the summary: count the chosen assignments again."""
        self._fetch_counts(force=True)

    def _fetch_counts(self, force: bool):
        chosen = self.chosen_assignments()
        if not chosen or self.session.canvas is None:
            return
        need = tuple(a for a in chosen
                     if force or needs_check("filecounts", self.counts_at.get(a)))
        if not need:
            return
        if self.counter.running:
            self._recount = True                     # after this one: the rest
            return
        self._recount = False
        self.fetching, self.counts_error = set(need), ""
        self._counts_course = self.session.course.id
        self.counter.start(file_counts, self.session.canvas, self._counts_course, need)
        self._apply_counts()

    def _counted(self, result):
        """Counts arrived (or part of them, if stopped): keep and cache them."""
        now = datetime.now(timezone.utc)
        self.fetching.clear()
        if self._counts_course == self.session.course.id:
            for aid, data in (result or {}).items():
                self.counts[aid], self.counts_at[aid] = data, now
            self.session.remember("filecounts", self._counts_course,
                                  files_to_data(self.counts, self.counts_at))
        self._apply_counts()
        if self._recount:
            self._count_now()

    def _counts_failed(self, exc):
        self.fetching.clear()
        self.counts_error = short_reason(exc)
        self._apply_counts()

    def _apply_counts(self):
        """Total the files for the current choices from what is known, at once."""
        chosen, students = self.chosen_assignments(), self._students()
        total = count_from(self.counts, chosen, students, self.history.isChecked())
        self.count = total if chosen and len(total.per_assignment) == len(chosen) else None
        self._partial = total
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self._count_cell(r, total, students)
        self.table.blockSignals(False)
        self._tags()
        self._update_summary()

    def _count_cell(self, row: int, total, students):
        aid = self.table.item(row, 0).data(Qt.UserRole)
        c = total.per_assignment.get(aid)
        if c is None:
            text, unsure = ("counting…" if aid in self.fetching else "—"), True
        else:
            unsure = aid in self.fetching or needs_check("filecounts", self.counts_at.get(aid))
            text = f"{'⟳ ' if aid in self.fetching else ''}{c.submitted} submitted"
        item = self.table.item(row, 2)
        item.setText(text)
        font = item.font()
        font.setItalic(unsure and c is not None)
        item.setFont(font)
        item.setForeground(QBrush(QColor("#5E574C" if unsure else "#252525")))

    # ---- summary and start ----
    def missing(self) -> str:
        if not self.chosen_assignments():
            return "Pick at least one assignment."
        if self.picker.roster is not None and not self.picker.student_ids():
            return "Pick a section or add a student."
        if self.gone & set(self.chosen_assignments()):
            return "Untick the assignment Canvas no longer lists."
        if not self.folder.path():
            return "Choose a folder to save to."
        return ""

    def _files_text(self, na: int) -> str:
        if self.count is not None:
            n = self.count.files
            return f"<b>{n}</b> file{'s' * (n != 1)}"
        if not na:
            return "files counted once you pick assignments"
        part = self._partial
        if not part.per_assignment:
            return "couldn't count files" if self.counts_error else "counting files…"
        return f"at least <b>{part.files}</b> files so far, counting the rest…"

    def _update_summary(self):
        na = len(self.chosen_assignments())
        ns = len(self.picker.student_ids()) if self.picker.roster else 0
        self.summary_text.setText(
            f"<b>{na} assignment{'s' * (na != 1)}</b>, <b>{ns} student{'s' * (ns != 1)}</b>, "
            f"{self._files_text(na)}. Files already downloaded are kept.")
        self.why.setText(self.missing())
        self.why.setVisible(bool(self.why.text()))

    def request(self) -> DownloadRequest:
        tz = self.tz.currentText().strip()
        return DownloadRequest(
            course_id=self.session.course.id, out_root=Path(self.folder.path()),
            assignment_ids=self.chosen_assignments(), selection=self.picker.selection(),
            by_section=self.by_section.isChecked(), flat=self.flat.isChecked(),
            extract=not self.keep_archives.isChecked(), history=self.history.isChecked(),
            tz=None if tz in ("", "UTC") else tz, excel_log=self.excel.isChecked(),
            run_started=datetime.now())

    def start(self):
        why = self.missing()
        if why:
            self.why.setText(why)
            self.why.setVisible(True)
            return
        req = self.request()
        s = self.session.settings
        s.options = {"flat": req.flat, "extract": req.extract, "section_folders": req.by_section,
                     "history": req.history, "excel_log": req.excel_log, "tz": req.tz or "UTC"}
        s.download_folder = str(req.out_root)
        self.session.save()
        self._recount = False
        self.count_timer.stop()
        if self.counter.running:
            self.counter.cancel()            # what it read so far is kept (see _counted)
        self.win.go("download_run", request=req,
                    expected=self.count.files if self.count else None)
