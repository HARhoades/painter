"""Settings › Downloads: how many files a download fetches at once. Folded
away under "Advanced": most people never need to change it."""
from __future__ import annotations

from PySide6.QtWidgets import QSpinBox, QVBoxLayout, QWidget

from painter.config import DEFAULT_WORKERS, MAX_WORKERS, clamp_workers
from painter.gui.widgets import Card, FoldButton, hbox, label

HINT = (f"{DEFAULT_WORKERS} suits most connections. Lower it if Canvas reports rate "
        "limiting or your network is slow; 1 downloads one file at a time, in order. "
        "Applies from the next download.")


class DownloadPrefs(Card):
    """The card; a change is saved at once and used by the next download."""

    def __init__(self, session):
        super().__init__(padding=22)
        self.session = session
        self.body.addWidget(label("Downloads", "h2"))
        self.fold = FoldButton("Advanced")
        self.fold.toggled.connect(lambda on: self.box.setVisible(on))
        self.body.addWidget(self.fold)
        self.box = QWidget()
        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(18, 0, 0, 0)
        self.workers = QSpinBox()
        self.workers.setRange(1, MAX_WORKERS)
        self.workers.setAccessibleName("Files to download at once")
        self.workers.valueChanged.connect(self._save)
        lay.addLayout(hbox(label("Files to download at once"), self.workers, None))
        lay.addWidget(label(HINT, "muted", wrap=True))
        self.box.setVisible(False)
        self.body.addWidget(self.box)

    def load(self) -> None:
        self.workers.blockSignals(True)
        self.workers.setValue(clamp_workers(self.session.settings.download_workers))
        self.workers.blockSignals(False)

    def _save(self, *_):
        self.session.settings.download_workers = self.workers.value()
        self.session.save()
