"""Screen 5: a download finished (or stopped): counts, problems, open the files."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QWidget

from painter.gui.views import View
from painter.gui.widgets import Banner, Card, button, clear, heading, hbox, label, show_problem


def open_path(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def summarise(rows: list[dict]) -> dict:
    out = {"downloaded": 0, "cached": 0, "failed": [], "students": set(), "assignments": set()}
    for r in rows:
        st = r.get("status", "")
        if st.startswith("failed"):
            out["failed"].append(r)
        elif st.startswith("cached"):
            out["cached"] += 1
        else:
            out["downloaded"] += 1
        out["students"].add(r.get("user_id"))
        out["assignments"].add(r.get("assignment_id"))
    return out


class DownloadDoneView(View):
    name = "download_done"
    section = "download"
    title = "Download finished"

    def __init__(self, win):
        super().__init__(win)
        head, self.h1, self.sub = heading("Finished", " ")
        self.page.addWidget(head)
        self.error = Banner()
        self.page.addWidget(self.error)
        self.tiles = QGridLayout()
        self.tiles.setSpacing(14)
        self.page.addLayout(self.tiles)
        self.problems = Card("ink")
        self.problems_body = QGridLayout()
        self.problems_body.setHorizontalSpacing(16)
        self.problems.body.addWidget(label("✕  Could not be downloaded", "h2"))
        self.problems.body.addLayout(self.problems_body)
        self.page.addWidget(self.problems)
        files = Card()
        self.where = label("", "muted", wrap=True)
        self.open_folder = button("Open folder", "primary", lambda: open_path(self.request.out_root))
        self.open_log = button("Open Excel log", "secondary",
                               lambda: open_path(self.result.log_path))
        self.open_manifest = button("Open manifest", "", lambda: open_path(self.result.manifest))
        self.again = button("↻  Try again", "", self.try_again)
        col = QWidget()
        col.setLayout(hbox(label("<b>Your files</b>"), None))
        files.body.addWidget(col)
        files.body.addWidget(self.where)
        files.body.addLayout(hbox(self.open_folder, self.open_log, self.open_manifest,
                                  self.again, None))
        self.page.addWidget(files)
        self.quiz = Banner()
        self.page.addWidget(self.quiz)
        self.page.addLayout(hbox(button("New download", "", lambda: self.win.go("download_setup")),
                                 None))
        self.page.addStretch(1)

    def enter(self, result=None, stopped=False, request=None, error=None, log="", **kw):
        self.request, self.result = request, result
        clear(self.tiles)
        clear(self.problems_body)
        self.error.clear_actions()
        self.error.set("info")
        if error is not None:
            self.h1.setText("The download didn't finish")
            self.sub.setText("Files saved before the problem are kept; running it again "
                             "fetches only what is missing.")
            show_problem(self.error, error, self.win.open_settings)
            for w in (self.problems, self.open_log, self.open_manifest):
                w.setVisible(False)
            self.quiz.set("info")
            self.where.setText(str(request.out_root) if request else "")
            return
        s = summarise(result.rows if result else [])
        failed = s["failed"]
        if stopped:
            self.h1.setText(f"Stopped: {s['downloaded']} file{'s' * (s['downloaded'] != 1)} "
                            "downloaded before you stopped")
            self.sub.setText("The manifest and log list what was saved. Running it again "
                             "picks up where it left off.")
        elif failed:
            self.h1.setText(f"Finished, with {len(failed)} file{'s' * (len(failed) != 1)} "
                            "to look at")
            self.sub.setText("They are listed below and in the manifest. Running the download "
                             "again fetches only what is missing.")
        else:
            self.h1.setText("Finished")
            self.sub.setText("Everything selected is in the folder below.")
        tiles = [(s["downloaded"], "✓ files downloaded"), (s["cached"], "↺ already here (kept)"),
                 (len(failed), "✕ could not be downloaded"),
                 (len(s["students"]), f"students, {len(s['assignments'])} assignment"
                                      f"{'s' * (len(s['assignments']) != 1)}")]
        for i, (n, text) in enumerate(tiles):
            c = Card("ink" if i == 2 and failed else "")
            c.body.addWidget(label(str(n), "big"))
            c.body.addWidget(label(text, "muted"))
            self.tiles.addWidget(c, 0, i)
        self.problems.setVisible(bool(failed))
        for r, row in enumerate(failed):
            who = f"<b>{row.get('student')}</b>" + (f" · {row['section']}" if row.get("section") else "")
            self.problems_body.addWidget(label(who), r, 0)
            self.problems_body.addWidget(label(f"{row.get('assignment')} · {row.get('filename')}"), r, 1)
            self.problems_body.addWidget(label(row["status"].split(":", 1)[-1].strip(), "muted", True), r, 2)
        self.where.setText(str(request.out_root))
        self.open_log.setVisible(bool(result and result.log_path))
        self.open_manifest.setVisible(bool(result and result.manifest))
        self.again.setText(f"↻  Try the {len(failed)} again" if failed else "↻  Run again")
        nq = result.new_quizzes_without_files if result else []
        self.quiz.set("info", "", "" if not nq else
                      f"{', '.join(a['name'] for a in nq)}: New Quiz file uploads aren't "
                      "attachments on Canvas. Use Quiz uploads (command line for now: "
                      "painter quiz uploads --assignment …).")

    def try_again(self):
        if self.request is not None and not self.win.runner.running:
            self.win.go("download_run", request=replace(self.request, run_started=datetime.now()))
