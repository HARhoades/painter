"""Screen 6: add grade files; each is read at once and its problems shown."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFrame, QGridLayout

from painter.gui.views import View
from painter.gui.widgets import (
    Banner, Card, StepBar, button, clear, heading, hbox, label, show_problem,
)
from painter.services.grade_files import GradeFileError, parse_grade_file
from painter.services.grading import plan_grades


class DropZone(QFrame):
    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        self.dropped.emit([u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()])


def read_file(path: Path):
    """(GradeFile | None, message)."""
    try:
        return parse_grade_file(path), ""
    except GradeFileError as exc:
        return None, str(exc).split(": ", 1)[-1]
    except (OSError, UnicodeDecodeError) as exc:
        return None, str(exc)


class GradesPickView(View):
    name = "grades_pick"
    section = "grades"
    title = "Post grades"

    def __init__(self, win):
        super().__init__(win)
        self.page.addWidget(heading("Post grades", "Add filled-in grade files. Nothing is sent "
                                    "until you've reviewed every change and confirmed.")[0])
        self.page.addWidget(StepBar())
        drop = DropZone()
        drop.dropped.connect(self.add)
        lay = hbox(label("<span style='font-size:18px; font-weight:700'>Drop grade files "
                         "here</span><br><span style='color:#5E574C'>.txt files made with "
                         "\"Make grade files\", e.g. A2-DATE_Grading-27-1.txt</span>", wrap=True),
                   button("Choose files…", "secondary", self.choose),
                   margins=(24, 22, 24, 22))
        drop.setLayout(lay)
        self.page.addWidget(drop)
        card = Card()
        self.count = label("No files yet", "h2")
        card.body.addWidget(self.count)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        card.body.addLayout(self.grid)
        self.page.addWidget(card)
        self.dup = QCheckBox("Post a comment even if the same text is already on the submission")
        self.page.addWidget(self.dup)
        self.page.addWidget(label("Off: repeated comments are skipped, so posting a file twice "
                                  "never doubles them.", "muted"))
        self.banner = Banner()
        self.page.addWidget(self.banner)
        self.check_btn = button("Check against Canvas", "primary", self.check)
        self.page.addLayout(hbox(self.check_btn, None))
        self.page.addStretch(1)
        self.files: dict[Path, tuple] = {}
        r = win.runner
        r.finished.connect(self._checked)
        r.failed.connect(self._failed)

    def _mine(self):
        return self.win.current is self and getattr(self, "_checking", False)

    def enter(self, **kw):
        self._refresh()

    def choose(self):
        start = self.session.settings.grades_folder or str(Path.home())
        names, _ = QFileDialog.getOpenFileNames(self, "Grade files", start, "Grade files (*.txt)")
        self.add(names)

    def add(self, names):
        for n in names:
            p = Path(n)
            self.files[p] = read_file(p)
        if names:
            self.session.settings.grades_folder = str(Path(names[0]).parent)
            self.session.save()
        self._refresh()

    def remove(self, path):
        self.files.pop(path, None)
        self._refresh()

    def _refresh(self):
        clear(self.grid)
        for r, (path, (gf, msg)) in enumerate(self.files.items()):
            ok = gf is not None
            self.grid.addWidget(label("✓" if ok else "✕"), r, 0)
            note = (f"<span style='color:#5E574C'>{path.parent}</span>" if ok else
                    f"<b>✕ Can't be read · {msg}</b>")
            self.grid.addWidget(label(f"<b>{path.name}</b><br>{note}", wrap=True), r, 1)
            what = (f"{gf.assignment_title or gf.assignment_id} · {gf.section_title or 'no section'}"
                    if ok else "Fix it and add it again")
            self.grid.addWidget(label(what), r, 2)
            self.grid.addWidget(label(f"{len(gf.entries)} students" if ok else "—", "muted"), r, 3)
            rm = button("✕", "", lambda _=False, p=path: self.remove(p), "Remove")
            rm.setAccessibleName(f"Remove {path.name}")
            self.grid.addWidget(rm, r, 4)
        self.grid.setColumnStretch(1, 1)
        n = len(self.files)
        self.count.setText(f"{n} file{'s' * (n != 1)}" if n else "No files yet")

    def missing(self) -> str:
        if not self.files:
            return "Add at least one grade file."
        bad = [p.name for p, (gf, _) in self.files.items() if gf is None]
        if bad:
            return f"Remove or fix {', '.join(bad)} first: it can't be read."
        return ""

    def check(self):
        why = self.missing()
        if why:
            self.banner.set("attention", "Not yet", why)
            return
        if self.win.runner.running:
            return
        self.banner.set("info", "Checking against Canvas…", "Reading only; nothing is sent.")
        self._checking = True
        self.check_btn.setEnabled(False)
        self.win.runner.start(plan_grades, self.session.canvas, list(self.files), None,
                              self.dup.isChecked())

    def _checked(self, plans):
        if not self._mine():
            return
        self._checking = False
        self.check_btn.setEnabled(True)
        self.banner.set("info")
        self.win.go("grades_review", plans=plans, allow_dup=self.dup.isChecked())

    def _failed(self, exc):
        if not self._mine():
            return
        self._checking = False
        self.check_btn.setEnabled(True)
        show_problem(self.banner, exc, self.win.open_settings)
