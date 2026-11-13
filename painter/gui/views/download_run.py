"""Screen 4: a download running: progress, waits, the files, the log, Stop."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHeaderView, QPlainTextEdit, QProgressBar, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from painter.events import ItemDone, Stage, StudentStart, Waiting
from painter.gui.views import View
from painter.gui.widgets import (
    Banner, Card, FoldButton, button, heading, hbox, label, pill_cell,
)
from painter.services.submissions import download_submissions


PERMILLE = 1000          # the overall bar counts in thousandths, so it fills smoothly


def overall_fraction(done: int, prior: int, stage_total: int, expected: int | None,
                     step: int, steps: int, stage_done: int) -> tuple[float, int | None]:
    """(how far along, estimated total files) for the whole download.

    With a count from the setup screen the bar goes by files, and the estimate
    grows if Canvas turns out to have more. Without one it goes by stage."""
    if expected:
        total = max(expected, prior + stage_total, done)
        return min(done / total, 1.0), total
    if steps:
        inner = stage_done / stage_total if stage_total else 1.0
        return min(((step - 1) + inner) / steps, 1.0), None
    return 0.0, None


def pill_for(status: str) -> tuple[str, str]:
    if status.startswith("failed"):
        return "bad", "Failed: " + status.split(":", 1)[-1].strip()[:60]
    if status.startswith("cached"):
        return "cached", "Already here"
    if "extract failed" in status:
        return "bad", "Downloaded; unpack failed"
    return "ok", "Downloaded"


class DownloadRunView(View):
    name = "download_run"
    section = "download"
    title = "Downloading"

    def __init__(self, win):
        super().__init__(win)
        head, self.h1, _ = heading("Downloading", kicker="Download")
        self.kicker = head.findChild(type(self.h1), "kicker")
        self.page.addWidget(head)
        top = Card(padding=20)
        self.big = label("0", "big")
        self.of = label("of … files", "muted")
        count = QWidget()
        cv = QVBoxLayout(count)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self.big)
        cv.addWidget(self.of)
        self.overall = QProgressBar()
        self.overall.setObjectName("overall")
        self.overall.setRange(0, PERMILLE)
        self.overall.setFormat("%p%")
        self.overall.setAccessibleName("Download progress")
        self.overall_text = label("", "muted")
        self.student_bar = QProgressBar()
        self.student_bar.setObjectName("student")
        self.student_bar.setTextVisible(False)
        self.student_bar.setAccessibleName("Progress through this student's files")
        self.student_text = label("", "muted")
        self.stop_btn = button("■  Stop after this file", "secondary", self.stop)
        bars = QWidget()
        bv = QVBoxLayout(bars)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(4)
        for w in (self.overall, self.overall_text, self.student_bar, self.student_text):
            bv.addWidget(w)
        bv.setSpacing(6)
        row = hbox(count, bars, self.stop_btn, spacing=24)
        row.setStretch(1, 1)
        top.body.addLayout(row)
        self.page.addWidget(top)
        self.wait = Banner()
        self.page.addWidget(self.wait)

        files = Card()
        self.files_head = label("Files", "h2")
        self.problems_only = QCheckBox("Problems only")
        self.problems_only.toggled.connect(self._filter)
        files.body.addLayout(hbox(self.files_head, None, self.problems_only))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Student", "File", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(2, 260)
        self.table.setMinimumHeight(260)
        files.body.addWidget(self.table)
        self.page.addWidget(files)

        self.log_btn = FoldButton()
        self.log_btn.toggled.connect(self._toggle_log)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        self.log.setVisible(False)
        self.page.addWidget(self.log_btn)
        self.page.addWidget(self.log)
        self.page.addStretch(1)

        r = win.runner
        r.line.connect(self._line)
        r.progress.connect(self._progress)
        r.event.connect(self._event)
        r.finished.connect(lambda res: self._ended(res, False))
        r.cancelled.connect(lambda res: self._ended(res, True))
        r.failed.connect(self._failed)

    def _mine(self) -> bool:
        return self.win.current is self

    # ---- start ----
    def enter(self, request=None, expected=None, **kw):
        if request is None:
            return
        self.request, self.expected = request, expected
        self.done_total = self.prior = self.stage_done = self.stage_total = 0
        self.step, self.steps, self.stage_name = 1, 1, ""
        self.student_done = 0
        self.student_on = False
        self.counts = {"ok": 0, "cached": 0, "bad": 0}
        self.table.setRowCount(0)
        self.log.clear()
        self.wait.set("info")
        self.overall.setValue(0)
        self.overall_text.setText("")
        self.student_bar.setRange(0, 1)
        self.student_bar.setValue(0)
        self._show_student(False)
        self._show_totals()
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("■  Stop after this file")
        self._update_counts()
        self._log_label()
        self.win.runner.start(download_submissions, self.session.canvas, request)

    def stop(self):
        if self.win.runner.cancel():
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Stopping after this file…")

    # ---- runner output ----
    def _line(self, kind, text):
        if self._mine():
            self.log.appendPlainText(text)
            self._log_label()

    def _progress(self, done, total, _label):
        """Progress inside the current assignment (a Stage event starts each one)."""
        if not self._mine():
            return
        self.stage_done, self.stage_total = done, total
        self._show_totals()
        self.wait.set("info")

    def _event(self, e):
        if not self._mine():
            return
        if isinstance(e, Stage):
            self.h1.setText(e.name)
            self.stage_name, self.stage_total, self.stage_done = e.name, e.total or 0, 0
            self.prior = self.done_total
            self.step, self.steps = e.step or 1, e.steps or 1
            if self.kicker is not None:
                self.kicker.setText(f"STEP {e.step} OF {e.steps}" if e.step else "DOWNLOAD")
            self._show_totals()
        elif isinstance(e, StudentStart):
            self.student_done = 0
            self.student_bar.setRange(0, max(e.files, 1))
            self.student_bar.setValue(0)
            self.student_name, self.student_files = e.name, e.files
            self.student_pos = f"student {e.index} of {e.total}" if e.total else ""
            self._show_student(True)
        elif isinstance(e, Waiting):
            secs = f"; retrying in {e.seconds:.0f} s" if e.seconds else ""
            self.wait.set("attention", "", f"{e.reason}{secs}. Nothing is wrong; Painter "
                                           "waits and carries on.")
        elif isinstance(e, ItemDone) and e.kind == "file":
            self._add_row(e)

    def _show_student(self, on: bool):
        self.student_on = on
        self.student_bar.setVisible(on)
        self.student_text.setVisible(on)
        if on:
            self._student_text()

    def _student_text(self):
        n, files = self.student_done, self.student_files
        bits = [self.student_name, f"file {min(n + (n < files), files)} of {files}"
                if n < files else f"{files} of {files} files", self.student_pos]
        self.student_text.setText("  ·  ".join(b for b in bits if b))

    def _show_totals(self):
        """The big count, the single overall bar and its caption."""
        frac, total = overall_fraction(self.done_total, self.prior, self.stage_total,
                                       self.expected, self.step, self.steps, self.stage_done)
        self.overall.setValue(int(frac * PERMILLE))
        self.big.setText(str(self.done_total))
        self.of.setText(f"of about {total} files" if total else "files so far")
        stage = f"assignment {self.step} of {self.steps}" if self.steps > 1 else ""
        self.overall_text.setText("  ·  ".join(x for x in (stage, self.stage_name) if x))

    def _add_row(self, e: ItemDone):
        kind, text = pill_for(e.status)
        self.counts[kind] += 1
        self.done_total += 1
        if self.student_on:
            self.student_done += 1
            self.student_bar.setValue(min(self.student_done, self.student_bar.maximum()))
            self._student_text()
        self._show_totals()
        r = 0                                # newest first
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(e.detail))
        f = QTableWidgetItem(e.key)
        f.setData(Qt.UserRole, kind)
        self.table.setItem(r, 1, f)
        self.table.setCellWidget(r, 2, pill_cell(kind, text))
        self.table.setRowHidden(r, self.problems_only.isChecked() and kind != "bad")
        self._update_counts()

    def _update_counts(self):
        c = self.counts
        self.files_head.setText(f"Files   ·   {c['ok']} downloaded · {c['cached']} already "
                                f"here · {c['bad']} failed")

    def _filter(self, on):
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, on and self.table.item(r, 1).data(Qt.UserRole) != "bad")

    def _toggle_log(self, on):
        self.log.setVisible(on)

    def _log_label(self):
        n = self.log.blockCount() if self.log.toPlainText() else 0
        self.log_btn.setText(f"Full log  ·  {n} lines, same text as the command line")

    # ---- end ----
    def _ended(self, result, stopped):
        if self._mine():
            self.win.go("download_done", result=result, stopped=stopped,
                        request=self.request, log=self.log.toPlainText())

    def _failed(self, exc):
        if self._mine():
            self.win.go("download_done", error=exc, request=self.request,
                        log=self.log.toPlainText())

    def leave_ok(self):
        return not self.win.runner.running
