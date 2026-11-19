"""One module per screen. Each view is a QWidget the main window shows in
its stack; enter(**kw) is called every time it is shown."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from painter.gui.widgets import scroll_page


class View(QWidget):
    name = ""
    section = None            # which sidebar task it belongs to: "download" | "gradefiles" | "grades" | None
    title = "Painter"

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.session = win.session
        self.area, self.page = scroll_page(self)

    def enter(self, **kw) -> None:
        pass

    def unsaved_ok(self, closing: bool = False) -> bool:
        """Called before the window shows another screen: False stays here
        (the view has asked about, and kept, changes not saved yet)."""
        return True

    def leave_ok(self) -> bool:
        """False to keep the user here (e.g. a run is going)."""
        return True


def all_views():
    """Every screen, in the order they're added to the stack."""
    from painter.gui.views.connect import ConnectView
    from painter.gui.views.home import HomeView
    from painter.gui.views.download_done import DownloadDoneView
    from painter.gui.views.download_run import DownloadRunView
    from painter.gui.views.download_setup import DownloadSetupView
    from painter.gui.views.grade_files_make import GradeFilesMakeView
    from painter.gui.views.grades_pick import GradesPickView
    from painter.gui.views.grades_preview import GradesPreviewView
    from painter.gui.views.grades_result import GradesResultView
    from painter.gui.views.grades_review import GradesReviewView
    return [ConnectView, HomeView, DownloadSetupView, DownloadRunView, DownloadDoneView,
            GradeFilesMakeView, GradesPickView, GradesPreviewView, GradesReviewView,
            GradesResultView]
