"""Screen 2: choose a course, then a task."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from painter.services.courses import list_courses
from painter.gui.views import View
from painter.gui.widgets import Banner, badge, button, heading, hbox, label, show_problem
from painter.gui.worker import TaskRunner


class CourseRow(QWidget):
    def __init__(self, c):
        super().__init__()
        self.mark = label("", "")
        self.mark.setFixedWidth(18)
        name = label(f"<b>{c.name}</b>")
        code = label(f"{c.code} · {c.sections} section{'s' * (c.sections != 1)}", "muted")
        role = badge(c.role, "count" if c.role == "Teacher" else "plain")
        term = label(c.term or "no term", "muted")
        size = label(f"{c.students} students" if c.students is not None else "")
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(name)
        v.addWidget(code)
        self.setLayout(hbox(self.mark, col, None, role, term, size, spacing=16,
                            margins=(12, 8, 12, 8)))

    def selected(self, on: bool):
        self.mark.setText("✓" if on else "")


class HomeView(View):
    name = "home"
    title = "Choose a course"

    def __init__(self, win):
        super().__init__(win)
        head, _, self.sub = heading("Choose a course",
                                    "Courses you teach or assist in. Painter remembers the last one.")
        self.page.addWidget(head)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter courses")
        self.filter.setAccessibleName("Filter courses")
        self.filter.setFixedWidth(280)
        self.current = QCheckBox("Current term only")
        self.teacher = QCheckBox("Teacher")
        self.ta = QCheckBox("TA")
        for cb in (self.current, self.teacher, self.ta):
            cb.setChecked(True)
            cb.toggled.connect(self.refill)
        self.filter.textChanged.connect(self.refill)
        self.refresh_btn = button("Refresh", "link", self.refresh)
        self.page.addLayout(hbox(self.filter, self.current, self.teacher, self.ta, None,
                                 self.refresh_btn, spacing=16))
        self.list = QListWidget()
        self.list.setAccessibleName("Courses")
        self.list.setMinimumHeight(240)
        self.list.setSpacing(3)
        self.list.currentItemChanged.connect(self._picked)
        self.page.addWidget(self.list)
        self.empty = label("", "muted", wrap=True)
        self.page.addWidget(self.empty)
        self.banner = Banner()
        self.page.addWidget(self.banner)

        self.dl = button("Download submissions  →", "secondary", lambda: self._task("download_setup"))
        self.gr = button("Post grades  →", "secondary", lambda: self._task("grades_pick"))
        for b, tip in ((self.dl, "Pick assignments and students; files land in one folder per "
                                 "student (or one flat folder), with a manifest and an Excel log."),
                       (self.gr, "Check filled-in grade files against Canvas, review every "
                                 "change, then post and verify.")):
            b.setMinimumHeight(64)
            b.setToolTip(tip)
        self.page.addLayout(hbox(self.dl, self.gr, spacing=16))
        self.page.addWidget(label("As a TA, Painter shows only what your Canvas role allows; a "
                                  "task Canvas refuses says so in plain words.", "muted", wrap=True))
        self.page.addStretch(1)
        self.lookup = TaskRunner(self)
        self.lookup.finished.connect(self._refreshed)
        self.lookup.failed.connect(lambda e: show_problem(self.banner, e, self.win.open_settings))
        self._filling = False

    def enter(self, **kw):
        self.refill()

    def visible_courses(self):
        text = self.filter.text().strip().lower()
        roles = {r for r, cb in (("Teacher", self.teacher), ("TA", self.ta)) if cb.isChecked()}
        return [c for c in self.session.courses
                if c.role in roles
                and (c.term_current or not self.current.isChecked())
                and (not text or text in f"{c.name} {c.code} {c.term}".lower())]

    def refill(self):
        self._filling = True
        self.list.clear()
        chosen = self.session.course
        for c in self.visible_courses():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c)
            item.setText("")
            item.setData(Qt.AccessibleTextRole, f"{c.name}, {c.code}, {c.role}, {c.term}")
            row = CourseRow(c)
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            if chosen and c.id == chosen.id:
                self.list.setCurrentItem(item)
                row.selected(True)
        n = self.list.count()
        self.empty.setText("" if n else
                           "No courses match. Untick 'Current term only' or clear the filter."
                           if self.session.courses else
                           "Canvas lists no courses where you teach or assist.")
        self.empty.setVisible(not n)
        self._filling = False

    def _picked(self, item, prev):
        for it in (prev, item):
            if it is not None and self.list.itemWidget(it):
                self.list.itemWidget(it).selected(it is item)
        if item is not None and not self._filling:
            self.session.choose_course(item.data(Qt.UserRole))

    def _task(self, view):
        if not self.session.course:
            self.banner.set("attention", "Choose a course first", "Click a course in the list above.")
            return
        self.banner.set("info")
        self.win.go(view)

    def refresh(self):
        if self.session.canvas and not self.lookup.running:
            self.lookup.start(list_courses, self.session.canvas)

    def _refreshed(self, courses):
        self.session.courses = courses
        self.refill()
