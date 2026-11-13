"""The main window: top bar, task sidebar, one screen at a time."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget,
)

from painter.gui.session import Session
from painter.gui.style import build_qss, load_fonts
from painter.gui.widgets import Logo, button, hbox, label
from painter.gui.worker import TaskRunner

LATER = ["Roster CSV", "Organize by section", "Make grade files", "Quiz export", "Quiz uploads"]


class MainWindow(QMainWindow):
    """Owns the session, the one task runner, and navigation between views."""

    def __init__(self, session: Session | None = None):
        super().__init__()
        self.session = session or Session()
        self.runner = TaskRunner(self)          # downloads, checks, posting: one at a time
        self.runner.busy.connect(self._busy)
        self.setWindowTitle("Painter")
        self.resize(1240, 860)

        root = QWidget()
        root.setObjectName("page")
        col = QVBoxLayout(root)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._topbar())
        body = QWidget()
        body.setLayout(hbox(self._sidebar(), spacing=0))
        self.stack = QStackedWidget()
        body.layout().addWidget(self.stack, 1)
        col.addWidget(body, 1)
        self.setCentralWidget(root)

        self.views = {}
        from painter.gui.views import all_views
        for cls in all_views():
            v = cls(self)
            self.views[v.name] = v
            self.stack.addWidget(v)
        self.session.course_changed.connect(self._course_label)
        self.session.connected.connect(lambda _: self._course_label(self.session.course))
        self._course_label(None)
        self.current = None
        self.go("connect", auto=True)

    # ---- chrome ----
    def _topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(56)
        brand = label("Painter", "brand")
        self.course_btn = button("", "", lambda: self.go("home"), "Change course")
        self.host = label("", "muted")
        self.settings_btn = button("⚙  Settings", "", self.open_settings, "Open settings")
        self.settings_btn.setObjectName("settings")
        self.settings_btn.setCheckable(True)
        self.settings_btn.setAccessibleName("Settings")
        bar.setLayout(hbox(Logo(), brand, self.course_btn, None, self.host, self.settings_btn,
                           spacing=14, margins=(20, 0, 20, 0)))
        return bar

    def _sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(240)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 18, 12, 18)
        lay.setSpacing(4)
        lay.addWidget(label("TASKS", "navhead"))
        self.nav = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, text, view in (("download", "Download submissions", "download_setup"),
                                ("grades", "Post grades", "grades_pick")):
            b = button(text, "", lambda _=False, v=view: self._nav(v))
            b.setObjectName("nav")
            b.setCheckable(True)
            group.addButton(b)
            self.nav[key] = b
            lay.addWidget(b)
        self.nav_group = group
        lay.addSpacing(14)
        lay.addWidget(label("LATER · COMMAND LINE FOR NOW", "navhead"))
        for t in LATER:
            lab = label(t, "later")
            lab.setToolTip("Not in the window yet; use the painter command. See docs/manual.md.")
            lay.addWidget(lab)
        lay.addStretch(1)
        return side

    def _course_label(self, course):
        s = self.session
        self.course_btn.setText(f"{course.name} · {course.term}  ▾" if course else "Choose a course  ▾")
        self.course_btn.setVisible(s.canvas is not None)
        self.host.setText(s.canvas.base.split("//", 1)[-1] if s.canvas else "")

    def _busy(self, on: bool):
        cur = self.current.section if self.current else None
        for key, b in self.nav.items():
            b.setEnabled(not on or key == cur)
            base = {"download": "Download submissions", "grades": "Post grades"}[key]
            busy = {"download": "Downloading…", "grades": "Working on grades…"}[key]
            b.setText(busy if on and key == cur else f"{base} (later)" if on else base)
            b.setToolTip("Available after the current task finishes" if on and key != cur else "")
        self.course_btn.setEnabled(not on)
        self.settings_btn.setEnabled(not on)

    # ---- navigation ----
    def _nav(self, view: str):
        if not self.session.course:
            self.go("home")
            self.views["home"].banner.set("attention", "Choose a course first",
                                          "Click a course in the list above.")
            return
        self.go(view)

    def go(self, name: str, **kw):
        view = self.views[name]
        if name not in ("connect",) and self.session.canvas is None:
            view = self.views["connect"]
        self.current = view
        view.enter(**kw)
        self.stack.setCurrentWidget(view)
        self.setWindowTitle(f"Painter · {view.title}")
        self.nav_group.setExclusive(False)
        for key, b in self.nav.items():
            b.setChecked(key == view.section)
        self.nav_group.setExclusive(True)
        self._settings_state(view.name == "connect")

    def _settings_state(self, on: bool):
        """The Settings button reads as pressed while Settings is showing."""
        self.settings_btn.setChecked(on)
        back = on and self.session.canvas is not None
        self.settings_btn.setText("✕  Close settings" if back else "⚙  Settings")
        self.settings_btn.setToolTip("Back to your courses" if back else
                                     "You're in Settings" if on else "Open settings")

    def open_settings(self):
        if self.runner.running:
            pass
        elif self.current is self.views["connect"]:
            if self.session.canvas is not None:
                self.go("home")                  # the button closes Settings
        else:
            self.go("connect")
        self._settings_state(self.current is self.views["connect"])

    # ---- closing during a run ----
    def closeEvent(self, ev):
        if not self.runner.running:
            ev.accept()
            return
        if self.runner.cancellable:
            msg = ("A task is running. Stop it and close? Painter finishes the current file, "
                   "saves the manifest and log, and a rerun picks up where it left off.")
        else:
            msg = ("Grades are being posted. Painter will finish posting this file, then "
                   "close. Close when it's done?")
        ans = QMessageBox.question(self, "Close Painter?", msg,
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            ev.ignore()
            return
        self.runner.cancel()
        self.runner.wait(120)
        ev.accept()


def main(argv=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("Painter")
    load_fonts()
    app.setStyleSheet(build_qss())
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())
