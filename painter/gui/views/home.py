"""Screen 2: choose a course, then a task."""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from painter.domain.freshness import classify
from painter.gui.problems import short_reason
from painter.services.courses import list_courses
from painter.gui.views import View
from painter.gui.widgets import (
    Banner, FreshnessTag, badge, button, heading, hbox, label, show_problem,
)
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
        head, _, self.sub = heading("Choose a course")
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
        self.tag = FreshnessTag(with_button=False)       # the Refresh link is its button
        self.page.addLayout(hbox(self.filter, self.current, self.teacher, self.ta, None,
                                 self.tag, self.refresh_btn, spacing=16))
        self.list = QListWidget()
        self.list.setObjectName("courses")
        self.list.setAccessibleName("Courses")
        self.list.setMinimumHeight(240)
        self.list.setSpacing(0)
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
        self.page.addStretch(1)
        self.lookup = TaskRunner(self)
        self.lookup.finished.connect(self._refreshed)
        self.lookup.failed.connect(self._refresh_failed)
        self._filling = False
        self._error = ""
        self.tag_clock = QTimer(self)
        self.tag_clock.setInterval(30_000)
        self.tag_clock.timeout.connect(self._tags)
        self.tag_clock.start()

    def enter(self, **kw):
        self.refill()
        self._tags()

    def _tags(self):
        self.tag.set(classify("courses", self.session.courses_at, self.lookup.running,
                              self._error) if self.session.canvas else None)

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
            self.refresh_btn.setEnabled(False)
            self.refresh_btn.setText("Refreshing…")
            self._error = ""
            self.banner.clear_actions()
            self.banner.set("info", "Refreshing the course list…",
                            "Asking Canvas for the courses you teach or assist in.")
            self.lookup.start(list_courses, self.session.canvas)
            self._tags()

    def _refresh_done(self):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh")
        self._tags()

    def _refreshed(self, courses):
        before = {c.id for c in self.session.courses}
        self.session.courses = courses
        self.session.courses_at = datetime.now(timezone.utc)
        self._refresh_done()
        self.refill()
        added = len({c.id for c in courses} - before)
        gone = len(before - {c.id for c in courses})
        change = ("No changes since the last check." if not (added or gone) else
                  ", ".join(x for x in (f"{added} new" if added else "",
                                        f"{gone} no longer listed" if gone else "") if x) + ".")
        n = len(courses)
        self.banner.set("ok", "Course list refreshed",
                        f"Canvas lists {n} course{'s' * (n != 1)} where you teach or assist. "
                        + change)

    def _refresh_failed(self, exc):
        self._error = short_reason(exc)
        self._refresh_done()
        show_problem(self.banner, exc, self.win.open_settings)
