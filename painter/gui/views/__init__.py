"""One module per screen. Each view is a QWidget the main window shows in
its stack; enter(**kw) is called every time it is shown."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from painter.gui.widgets import scroll_page


class View(QWidget):
    name = ""
    section = None            # which sidebar task it belongs to: "download" | "grades" | None
    title = "Painter"

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.session = win.session
        self.area, self.page = scroll_page(self)

    def enter(self, **kw) -> None:
        pass

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
    from painter.gui.views.placeholder import BUILT, placeholders
    BUILT.add("download_setup")
    return [ConnectView, HomeView, DownloadSetupView, DownloadRunView, DownloadDoneView,
            *placeholders()]
