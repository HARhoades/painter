"""Screen 3: choose assignments, students, folder and options."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QHeaderView, QRadioButton,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from painter.domain.naming import slug
from painter.domain.roster import Roster
from painter.gui.student_picker import StudentPicker
from painter.gui.views import View
from painter.gui.widgets import (
    Banner, Card, FolderPicker, button, heading, hbox, label, show_problem,
)
from painter.gui.worker import TaskRunner
from painter.services.submissions import DownloadRequest, assignment_listing, count_files

ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
         "UTC", "Europe/London"]


def load_choices(canvas, course_id: int, tz: str | None):
    """Worker thread: what the screen needs from Canvas."""
    return assignment_listing(canvas, course_id, tz), Roster.load(canvas, course_id)


def default_folder(course) -> str:
    return str(Path.home() / "Documents" / "Painter" / slug(course.code or course.name, 60))


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
        cols.setLayout(hbox(spacing=20))
        cols.layout().addLayout(left, 3)
        cols.layout().addLayout(right, 2)
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
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Assignment", "Due", "Submitted"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setMinimumHeight(220)
        self.table.itemChanged.connect(self._assignments_changed)
        a.body.addWidget(self.table)
        return a

    def _students_card(self) -> Card:
        s = Card()
        s.body.addWidget(label("2. Students", "h2"))
        self.picker = StudentPicker()
        self.picker.changed.connect(self._schedule_count)
        s.body.addWidget(self.picker)
        return s

    def _where_card(self) -> Card:
        w = Card()
        w.body.addWidget(label("3. Where and how", "h2"))
        w.body.addWidget(label("Save to folder", "muted"))
        self.folder = FolderPicker("Save submissions to")
        w.body.addWidget(self.folder)
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
        w.body.addWidget(label("Assignment › Student › files", "muted"))
        w.body.addWidget(self.flat)
        w.body.addWidget(label("All files together; names get the student's name and ID",
                               "muted", wrap=True))
        self.keep_archives = QCheckBox("Don't unpack archives")
        self.keep_archives.setToolTip("Keep .zip files as they arrive. Off: unpacked next to "
                                      "the archive.")
        w.body.addWidget(self.keep_archives)
        self.more = QToolButton()
        self.more.setText("More options")
        self.more.setCheckable(True)
        self.more.setArrowType(Qt.RightArrow)
        self.more.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more.setStyleSheet("QToolButton { border: 0; font-weight: 600; }")
        w.body.addWidget(self.more)
        self.more_box = QWidget()
        mb = QVBoxLayout(self.more_box)
        mb.setContentsMargins(18, 0, 0, 0)
        self.by_section = QCheckBox("A folder per section too")
        self.history = QCheckBox("Include earlier attempts")
        self.excel = QCheckBox("Excel log")
        self.excel.setChecked(True)
        self.tz = QComboBox()
        self.tz.setEditable(True)
        self.tz.addItems(ZONES)
        self.tz.setAccessibleName("Time zone for the manifest and log")
        for x in (self.by_section, self.history, self.excel):
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
        self.summary.body.addLayout(hbox(self.start_btn, None))
        self.summary.body.addWidget(self.why)
        return self.summary

    def _runners(self) -> None:
        self.lookup = TaskRunner(self)
        self.lookup.finished.connect(self._loaded)
        self.lookup.failed.connect(lambda e: show_problem(self.banner, e, self.win.open_settings))
        self.counter = TaskRunner(self)
        self.counter.finished.connect(self._counted)
        self.counter.cancelled.connect(self._count_cancelled)
        self._recount = False
        self.counter.failed.connect(lambda e: self._count_text("couldn't count files"))
        self.count_timer = QTimer(self)
        self.count_timer.setSingleShot(True)
        self.count_timer.setInterval(500)
        self.count_timer.timeout.connect(self._count_now)
        self.loaded_for = None
        self.count = None
        self.assignments = []

    # ---- loading ----
    def enter(self, **kw):
        course = self.session.course
        opts = self.session.settings.options or {}
        if self.loaded_for != course.id:
            self.loaded_for = None
            self.table.setRowCount(0)
            self.banner.set("info", "Loading assignments and roster…")
            self.folder.set_path(default_folder(course))
            self.lookup.start(load_choices, self.session.canvas, course.id,
                              opts.get("tz") or None)
        self.flat.setChecked(bool(opts.get("flat")))
        self.keep_archives.setChecked(not opts.get("extract", True))
        self.by_section.setChecked(bool(opts.get("by_section")))
        self.history.setChecked(bool(opts.get("history")))
        self.excel.setChecked(opts.get("excel_log", True))
        self.tz.setCurrentText(opts.get("tz") or ZONES[0])
        self._update_summary()

    def _loaded(self, result):
        assignments, roster = result
        self.assignments = assignments
        self.loaded_for = self.session.course.id
        self.banner.set("info")
        self.table.blockSignals(True)
        self.table.setRowCount(len(assignments))
        for r, a in enumerate(assignments):
            name = QTableWidgetItem(a.name + ("\nNew Quiz: files come via Quiz uploads"
                                              if a.new_quiz else ""))
            name.setData(Qt.UserRole, a.id)
            if a.new_quiz:
                name.setFlags(Qt.ItemIsEnabled)
            else:
                name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                name.setCheckState(Qt.Unchecked)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(a.due or "No due date"))
            self.table.setItem(r, 2, QTableWidgetItem("—"))
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)
        self.picker.set_roster(roster)
        self._update_summary()

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

    def _toggle_more(self, on):
        self.more.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.more_box.setVisible(on)

    # ---- background count ----
    def _schedule_count(self, *_):
        self.count = None
        self._update_summary()
        self.count_timer.start()

    def _count_now(self):
        if not self.chosen_assignments() or self.picker.roster is None:
            return
        if self.counter.running:
            self._recount = True
            self.counter.cancel()            # restarts from _count_cancelled
            return
        self._count_text("counting files…")
        self.counter.start(count_files, self.session.canvas, self.session.course.id,
                           self.chosen_assignments(), self.picker.selection(),
                           self.history.isChecked())

    def _count_cancelled(self, _):
        if self._recount:
            self._recount = False
            self._count_now()

    def _counted(self, count):
        if set(count.per_assignment) != set(self.chosen_assignments()):
            return self._count_now()
        self.count = count
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            aid = self.table.item(r, 0).data(Qt.UserRole)
            c = count.per_assignment.get(aid)
            if c is not None:
                self.table.item(r, 2).setText(f"{c.submitted} submitted")
        self.table.blockSignals(False)
        self._update_summary()

    def _count_text(self, text):
        self._counting = text
        self._update_summary()

    # ---- summary and start ----
    def missing(self) -> str:
        if not self.chosen_assignments():
            return "Pick at least one assignment."
        if self.picker.roster is not None and not self.picker.student_ids():
            return "Pick a section or add a student."
        if not self.folder.path():
            return "Choose a folder to save to."
        return ""

    def _update_summary(self):
        na = len(self.chosen_assignments())
        ns = len(self.picker.student_ids()) if self.picker.roster else 0
        if self.count is not None:
            files = f"<b>{self.count.files}</b> file{'s' * (self.count.files != 1)}"
        elif na:
            files = getattr(self, "_counting", "counting files…")
        else:
            files = "files counted once you pick assignments"
        self.summary_text.setText(
            f"<b>{na} assignment{'s' * (na != 1)}</b>, <b>{ns} student{'s' * (ns != 1)}</b>, "
            f"{files}. Files already downloaded are kept.")
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
        s.options = {"flat": req.flat, "extract": req.extract, "by_section": req.by_section,
                     "history": req.history, "excel_log": req.excel_log, "tz": req.tz or "UTC"}
        s.download_folder = str(req.out_root)
        self.session.save()
        self._recount = False
        self.count_timer.stop()
        if self.counter.running:
            self.counter.cancel()
        self.win.go("download_run", request=req,
                    expected=self.count.files if self.count else None)
