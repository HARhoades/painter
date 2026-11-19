"""The finished-download screen's "Details" panel: who was late and by how long,
who submitted more than once, per assignment and per student (from the same
rows as the manifest and Excel log)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from painter.domain.run_report import RunReport, build_report
from painter.gui.widgets import Card, FoldButton, hbox, label

STUDENT_COLS = ["Student", "Section", "Assignment", "Submitted", "Submissions",
                "Late by", "Files"]
ASSIGN_COLS = ["Assignment", "Students", "Files", "Late", "Longest late",
               "Submitted more than once", "Excused"]


class SortItem(QTableWidgetItem):
    """Sorts by a hidden key (numbers, minutes late) instead of the shown text."""

    def __init__(self, text: str, key=None):
        super().__init__(text)
        self.setData(Qt.UserRole, text.lower() if key is None else key)

    def __lt__(self, other):                     # noqa: D105
        a, b = self.data(Qt.UserRole), other.data(Qt.UserRole)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def table(cols: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.NoSelection)
    t.setWordWrap(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    return t


def headline(report: RunReport) -> str:
    n = len(report.students)
    late = len(report.late)
    again = sum(s.attempts > 1 for s in report.students)
    excused = sum(s.excused for s in report.students)
    bits = [f"{n} submission{'s' * (n != 1)}",
            f"{late} late" + (f" (longest {report.late[0].late_by})" if late else ""),
            f"{again} submitted more than once"]
    if excused:
        bits.append(f"{excused} excused")
    return "  ·  ".join(bits)


class RunDetails(Card):
    def __init__(self):
        super().__init__()
        self.fold = FoldButton("Details: lateness and submissions")
        self.fold.setAccessibleName("Show details from the log and manifest")
        self.line = label("", "muted", wrap=True)
        self.body.addWidget(self.fold)
        self.body.addWidget(self.line)
        self.box = QWidget()
        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        self.by_assignment = table(ASSIGN_COLS)
        self.late_only = QCheckBox("Late only")
        self.late_only.toggled.connect(self._filter)
        self.by_student = table(STUDENT_COLS)
        self.by_student.setMinimumHeight(260)
        self.by_student.setSortingEnabled(True)
        lay.addWidget(label("<b>By assignment</b>"))
        lay.addWidget(self.by_assignment)
        lay.addLayout(hbox(label("<b>By student</b>  (click a heading to sort)"), None,
                           self.late_only))
        lay.addWidget(self.by_student)
        self.body.addWidget(self.box)
        self.box.setVisible(False)
        self.fold.toggled.connect(self.box.setVisible)
        self.report = RunReport()

    def show_rows(self, rows: list[dict]) -> None:
        self.report = build_report(rows)
        self.setVisible(bool(self.report.students))
        self.line.setText(headline(self.report))
        self._fill_assignments()
        self._fill_students()

    def _fill_assignments(self):
        t = self.by_assignment
        t.setRowCount(0)
        for a in self.report.assignments:
            r = t.rowCount()
            t.insertRow(r)
            for c, v in enumerate((a.assignment, a.students, a.files, a.late,
                                   a.latest_late or "—", a.resubmitted, a.excused)):
                t.setItem(r, c, QTableWidgetItem(str(v)))
        t.resizeRowsToContents()
        h = t.horizontalHeader().height() + sum(t.rowHeight(r) for r in range(t.rowCount()))
        t.setFixedHeight(h + 4)

    def _fill_students(self):
        t = self.by_student
        t.setSortingEnabled(False)
        t.setRowCount(0)
        bold = QFont()
        bold.setBold(True)
        for s in self.report.students:
            r = t.rowCount()
            t.insertRow(r)
            late = ("excused" if s.excused else f"+{s.late_by}" if s.late else "on time")
            files = f"{s.files}" + (f" ({s.failed} failed)" if s.failed else "")
            cells = [SortItem(s.student), SortItem(s.section), SortItem(s.assignment),
                     SortItem(s.submitted_at or "—"), SortItem(str(s.attempts), s.attempts),
                     SortItem(late, s.late_minutes if s.late else -1),
                     SortItem(files, s.files)]
            if s.late:
                cells[5].setFont(bold)
            cells[0].setData(Qt.UserRole + 1, s.late)
            for c, it in enumerate(cells):
                t.setItem(r, c, it)
        t.setSortingEnabled(True)
        t.sortByColumn(5, Qt.DescendingOrder)        # latest first
        self._filter(self.late_only.isChecked())

    def _filter(self, on: bool):
        t = self.by_student
        for r in range(t.rowCount()):
            t.setRowHidden(r, on and not t.item(r, 0).data(Qt.UserRole + 1))
