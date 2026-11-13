"""Screen 7: review every planned change, one card per grade file; then confirm."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QGridLayout, QVBoxLayout, QWidget

from painter.gui.grade_text import (
    comment_text, manual_posting, other_notes, plan_meta, sent_grade, summary, warnings,
)
from painter.gui.views import View
from painter.gui.widgets import (
    Banner, Card, StepBar, badge, button, clear, heading, hbox, label,
)

SHOWN = 6           # rows per card before "+ N more"


class PlanCard(Card):
    def __init__(self, plan):
        super().__init__("secondary")
        items = plan.items
        w = sum(len(it.warnings) for it in plan.to_send)
        head = QWidget()
        head.setLayout(hbox(
            label(f"<b style='font-size:16px'>{plan.source.path.name}</b><br>"
                  f"<span style='color:#5E574C'>{plan_meta(plan)}</span>", wrap=True),
            badge(f"{len(plan.to_send)} update{'s' * (len(plan.to_send) != 1)}", "count"),
            badge(f"⚠ {w} warning{'s' * (w != 1)}", "warn") if w else badge("✓ No warnings", "plain")))
        self.body.addWidget(head)
        if manual_posting(plan):
            self.body.addWidget(Banner("attention", "", "Grades are posted manually for this "
                                       "assignment: students won't see these until you post "
                                       "them in Canvas."))
        for n in other_notes(plan):
            self.body.addWidget(label(f"ⓘ {n}", "muted", wrap=True))
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(6)
        for c, t in enumerate(("Student", "Grade", "Comment")):
            self.grid.addWidget(label(t, "muted"), 0, c)
        self.grid.setColumnStretch(2, 1)
        self.body.addLayout(self.grid)
        self.rows = [self._row(it) for it in items]
        for i, widgets in enumerate(self.rows):
            for c, wdg in enumerate(widgets):
                self.grid.addWidget(wdg, i + 1, c)
                wdg.setVisible(i < SHOWN)
        self.more = button(f"+ {len(items) - SHOWN} more rows", "link", self._show_all)
        self.more.setVisible(len(items) > SHOWN)
        self.body.addLayout(hbox(self.more, None))

    @staticmethod
    def _row(it):
        warn = "".join(f"<br><b>⚠ {w}</b>" for w in it.warnings)
        who = label(f"{it.student} ({it.user_id}){warn}", wrap=True)
        if it.fields:
            before = it.grade_before or "–"
            g = sent_grade(it) or "—"
            grade = label(f"<span style='color:#5E574C'>{before}</span> → <b>{g}</b>")
        else:
            grade = label("nothing to send", "muted")
        c = comment_text(it)
        comment = label(c, "muted" if c.startswith("Already on Canvas") else "", wrap=True)
        return who, grade, comment

    def _show_all(self):
        for widgets in self.rows:
            for w in widgets:
                w.setVisible(True)
        self.more.setVisible(False)


class ConfirmDialog(QDialog):
    """Screen 8: the last look before anything is sent."""

    def __init__(self, parent, plans):
        super().__init__(parent)
        self.setWindowTitle("Post to Canvas?")
        self.setModal(True)
        s = summary(plans)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(12)
        lay.addWidget(label(f"Post {s['updates']} update{'s' * (s['updates'] != 1)} to Canvas?", "h1"))
        lay.addWidget(label(", ".join(s["assignments"]) + (
            f" · section{'s' * (len(s['sections']) != 1)} {', '.join(s['sections'])}"
            if s["sections"] else ""), "muted", wrap=True))
        lines = [f"✓  {s['grades']} grade{'s' * (s['grades'] != 1)}"
                 + (f" ({s['excused']} excused)" if s["excused"] else "")
                 + f", {s['comments']} comment{'s' * (s['comments'] != 1)}"]
        for who, before, after in s["changes"]:
            lines.append(f"<b>⚠  {who}: existing grade will change ({before} → {after})</b>")
        if s["manual"]:
            lines.append("ⓘ  Students won't see these until you post grades in Canvas "
                         "(manual posting is on)")
        for ln in lines:
            lay.addWidget(label(ln, wrap=True))
        lay.addWidget(label("One request per file. Afterwards Painter reads every grade back "
                            "from Canvas and shows anything that didn't take. A log is saved "
                            "next to the grade files. Once a file is being posted it can't be "
                            "stopped halfway.", "muted", wrap=True))
        self.ok = button(f"Post {s['updates']} update{'s' * (s['updates'] != 1)}", "primary", self.accept)
        cancel = button("Cancel", "", self.reject)
        lay.addLayout(hbox(None, cancel, self.ok))
        self.ok.setDefault(True)
        self.resize(600, self.sizeHint().height())


def confirm(parent, plans) -> bool:
    return ConfirmDialog(parent, plans).exec() == QDialog.Accepted


class GradesReviewView(View):
    name = "grades_review"
    section = "grades"
    title = "Review before posting"

    def __init__(self, win):
        super().__init__(win)
        self.page.addWidget(heading("Review before posting",
                                    "Checked against Canvas just now. Nothing has been sent.")[0])
        steps = StepBar()
        steps.set(2)
        self.page.addWidget(steps)
        self.errors = Banner()
        self.page.addWidget(self.errors)
        self.cards = QVBoxLayout()
        self.cards.setSpacing(16)
        self.page.addLayout(self.cards)
        foot = Card("primary")
        foot.setObjectName("summary")
        self.foot_text = label("", wrap=True)
        self.post_btn = button("Post…", "primary", self.post)
        self.blocked = label("", "muted", wrap=True)
        foot.body.addLayout(hbox(self.foot_text,
                                 button("Back", "", lambda: self.win.go("grades_pick")),
                                 self.post_btn))
        foot.body.addWidget(self.blocked)
        self.page.addWidget(foot)
        self.page.addStretch(1)
        self.confirm = confirm             # replaced in tests

    def enter(self, plans=None, allow_dup=False, **kw):
        if plans is None:
            return
        self.plans, self.allow_dup = plans, allow_dup
        clear(self.cards)
        if plans.errors:
            self.errors.set("error", f"{len(plans.errors)} error{'s' * (len(plans.errors) != 1)} "
                            "to fix: nothing can be posted until they're gone",
                            "\n".join(plans.errors))
        else:
            self.errors.set("info")
        for plan in plans.plans:
            self.cards.addWidget(PlanCard(plan))
        n, w = plans.total, warnings(plans)
        files = len(plans.plans)
        self.foot_text.setText(f"<b>{n} update{'s' * (n != 1)}</b> in {files} file"
                               f"{'s' * (files != 1)}" + (f" · <b>⚠ {w} warning"
                               f"{'s' * (w != 1)}</b> to look at" if w else ""))
        self.post_btn.setText(f"Post {n} update{'s' * (n != 1)}…")
        self.post_btn.setVisible(bool(n) and not plans.errors)
        self.blocked.setText("Fix the errors above, then go back and check again."
                             if plans.errors else "" if n else
                             "Nothing to post: every grade and comment is already on Canvas.")
        self.blocked.setVisible(bool(self.blocked.text()))

    def post(self):
        if self.plans.errors or not self.plans.total or self.win.runner.running:
            return
        if self.confirm(self, self.plans):
            self.win.go("grades_result", plans=self.plans, allow_dup=self.allow_dup)
