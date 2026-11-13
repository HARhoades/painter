"""Screen 4: a download running: progress, waits, the files, the log, Stop."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHeaderView, QPlainTextEdit, QProgressBar, QTableWidget,
    QTableWidgetItem, QToolButton,
)

from painter.events import ItemDone, Stage, Waiting
from painter.gui.views import View
from painter.gui.widgets import Banner, Card, button, heading, hbox, label, pill_cell
from painter.services.submissions import download_submissions


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
        self.of = label("of 0 files", "muted")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.overall = QProgressBar()
        self.overall.setObjectName("overall")
        self.overall.setTextVisible(False)
        self.overall.setFixedHeight(6)
        self.overall_text = label("", "muted")
        self.stop_btn = button("■  Stop after this file", "secondary", self.stop)
        bars = Card(padding=0)
        bars.setObjectName("plain")
        bars.setStyleSheet("background: transparent; border: 0;")
        bars.body.addWidget(self.bar)
        bars.body.addWidget(self.overall)
        bars.body.addWidget(self.overall_text)
        row = hbox(self.big, self.of, bars, self.stop_btn, spacing=20)
        row.setStretch(2, 1)
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

        self.log_btn = QToolButton()
        self.log_btn.setCheckable(True)
        self.log_btn.setArrowType(Qt.RightArrow)
        self.log_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.log_btn.setStyleSheet("QToolButton { border: 0; font-weight: 600; }")
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
        self.done_total = 0
        self.counts = {"ok": 0, "cached": 0, "bad": 0}
        self.table.setRowCount(0)
        self.log.clear()
        self.wait.set("info")
        self.big.setText("0")
        self.of.setText("of … files")
        self.bar.setValue(0)
        self.overall.setRange(0, expected or 0)
        self.overall.setValue(0)
        self.overall_text.setText("")
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
        if not self._mine():
            return
        self.big.setText(str(done))
        self.of.setText(f"of {total} file{'s' * (total != 1)}")
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.wait.set("info")

    def _event(self, e):
        if not self._mine():
            return
        if isinstance(e, Stage):
            self.h1.setText(e.name)
            if self.kicker is not None:
                self.kicker.setText(f"STEP {e.step} OF {e.steps}" if e.step else "DOWNLOAD")
        elif isinstance(e, Waiting):
            secs = f"; retrying in {e.seconds:.0f} s" if e.seconds else ""
            self.wait.set("attention", "", f"{e.reason}{secs}. Nothing is wrong; Painter "
                                           "waits and carries on.")
        elif isinstance(e, ItemDone) and e.kind == "file":
            self._add_row(e)

    def _add_row(self, e: ItemDone):
        kind, text = pill_for(e.status)
        self.counts[kind] += 1
        self.done_total += 1
        self.overall.setValue(min(self.done_total, self.overall.maximum() or self.done_total))
        if self.expected and self.done_total <= self.expected:
            self.overall_text.setText(f"Overall: {self.done_total} of about {self.expected}")
        else:
            self.overall_text.setText(f"Overall: {self.done_total} so far")
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
        self.log_btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
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
