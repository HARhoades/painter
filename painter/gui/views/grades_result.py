"""Screen 9: posting, then what Canvas shows afterwards; post failed rows again."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QProgressBar

from painter.gui.views import View
from painter.gui.widgets import (
    Banner, Card, StepBar, button, clear, heading, hbox, label, pill_cell, show_problem,
)
from painter.services.grading import post_grade_plans, replan_failed


def sent(row: dict) -> bool:
    return bool(row.get("grade_sent") or row.get("comment_sent"))


def sent_text(row: dict) -> str:
    return row.get("grade_sent") or ("comment" if row.get("comment_sent") else "")


class GradesResultView(View):
    name = "grades_result"
    section = "grades"
    title = "Posted and verified"

    def __init__(self, win):
        super().__init__(win)
        head, self.h1, self.sub = heading("Posting…", " ")
        self.page.addWidget(head)
        steps = StepBar()
        steps.set(3)
        self.page.addWidget(steps)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.page.addWidget(self.bar)
        self.banner = Banner()
        self.page.addWidget(self.banner)
        self.again_all = button("↻  Post again", "primary", lambda: self.post_again(None))
        card = Card()
        card.body.addLayout(hbox(label("Verification", "h2"), None, label("Problems first", "muted")))
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(6)
        card.body.addLayout(self.grid)
        self.page.addWidget(card)
        self.log_text = label("", "muted", wrap=True)
        self.open_log = button("Open log", "", self._open_log)
        self.page.addLayout(hbox(self.log_text, self.open_log,
                                 button("Post more files", "secondary",
                                        lambda: self.win.go("grades_pick"))))
        self.page.addStretch(1)
        self.result = None
        self._phase = None                  # "post" | "replan"
        r = win.runner
        r.progress.connect(self._progress)
        r.finished.connect(self._finished)
        r.cancelled.connect(self._finished)
        r.failed.connect(self._failed)
        from painter.gui.views.grades_review import confirm
        self.confirm = confirm

    def _mine(self):
        return self.win.current is self and self._phase is not None

    # ---- posting ----
    def enter(self, plans=None, allow_dup=False, **kw):
        if plans is None:
            return
        self.plans, self.allow_dup = plans, allow_dup
        self._post(plans)

    def _post(self, plans):
        self.h1.setText("Posting…")
        self.sub.setText("Each file is posted in one request, then read back from Canvas.")
        self.banner.clear_actions()
        self.banner.set("info")
        clear(self.grid)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.log_text.setText("")
        self.open_log.setVisible(False)
        self.posting = plans
        self._phase = "post"
        log_dir = Path(plans.plans[0].source.path).parent
        self.win.runner.start(post_grade_plans, self.session.canvas, plans, log_dir,
                              datetime.now(), cancellable=False)

    def _progress(self, done, total, _):
        if self._mine() and self._phase == "post":
            self.bar.setRange(0, max(total, 1))
            self.bar.setValue(done)

    def _finished(self, value):
        if not self._mine():
            return
        phase, self._phase = self._phase, None
        if phase == "replan":
            return self._replanned(value)
        self.result = value
        self.show_result(value)

    def _failed(self, exc):
        if not self._mine():
            return
        self._phase = None
        self.bar.setVisible(False)
        self.h1.setText("Posting didn't finish")
        self.sub.setText("Anything posted before the problem is in the log next to the "
                         "grade files.")
        show_problem(self.banner, exc, self.win.open_settings)

    # ---- the result ----
    def show_result(self, res):
        self.bar.setVisible(False)
        rows = [r for r in res.rows if sent(r)]
        bad = [r for r in rows if r.get("problems")]
        ok = len(rows) - len(bad)
        self.h1.setText(f"{ok} of {len(rows)} update{'s' * (len(rows) != 1)} "
                        f"{'is' if len(rows) == 1 else 'are'} on Canvas")
        self.sub.setText("Read back from Canvas after posting." +
                         (f" {len(bad)} didn't take." if bad else ""))
        self.banner.clear_actions()
        if bad:
            self.banner.set("error", f"{len(bad)} update{'s' * (len(bad) != 1)} failed",
                            "Fix the cause in Canvas if needed (for example, enrol the "
                            "student), then post only the failed rows again. Verified rows "
                            "are not re-sent.")
            self.again_all = button(f"↻  Post {len(bad)} failed update{'s' * (len(bad) != 1)} "
                                    "again", "primary", lambda: self.post_again(None))
            self.banner.add_action(self.again_all)
        else:
            self.banner.set("ok", "Every update is on Canvas")
        clear(self.grid)
        for c, t in enumerate(("Student", "Sent", "Canvas now", "Result", "")):
            self.grid.addWidget(label(t, "muted"), 0, c)
        for i, r in enumerate(bad + [r for r in rows if not r.get("problems")], start=1):
            self.grid.addWidget(label(f"{r['student']} ({r['user_id']})"), i, 0)
            self.grid.addWidget(label(sent_text(r)), i, 1)
            self.grid.addWidget(label(str(r.get("canvas_grade_after") or "–")), i, 2)
            if r.get("problems"):
                self.grid.addWidget(pill_cell("bad", r["problems"][:70]), i, 3)
                again = button("↻ Post again", "secondary",
                               lambda _=False, row=r: self.post_again(row))
                again.setAccessibleName(f"Post again for {r['student']}")
                self.grid.addWidget(again, i, 4)
            else:
                self.grid.addWidget(pill_cell("ok", "Verified"), i, 3)
        self.grid.setColumnStretch(3, 1)
        if res.log_path:
            self.log_text.setText(f"Log: {res.log_path}")
            self.open_log.setVisible(True)

    def _open_log(self):
        if self.result and self.result.log_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.log_path)))

    # ---- post again ----
    def post_again(self, row: dict | None):
        if self.win.runner.running or self.result is None:
            return
        res = self.result
        if row is not None:      # just this student: the others count as fine
            res = replace(res, rows=[r if r is row else {**r, "problems": ""} for r in res.rows])
        self.banner.clear_actions()
        self.banner.set("info", "Checking the failed rows against Canvas…", "Reading only.")
        self._phase = "replan"
        self.win.runner.start(replan_failed, self.session.canvas, self.posting, res,
                              self.allow_dup)

    def _replanned(self, plans):
        if plans.errors:
            self.banner.set("error", "These rows can't be posted again yet",
                            "\n".join(plans.errors))
            return
        if not plans.total:
            self.banner.set("ok", "Nothing left to send",
                            "Canvas already has everything that failed.")
            return
        if self.confirm(self, plans):
            self._post(plans)
        else:
            self.show_result(self.result)
