"""Task screens not built yet: they say so instead of failing."""
from __future__ import annotations

from painter.gui.views import View
from painter.gui.widgets import heading, label

BUILT: set[str] = set()


def placeholders():
    out = []
    for name, title, section in (("download_setup", "Download submissions", "download"),
                                 ("grades_pick", "Post grades", "grades")):
        if name in BUILT:
            continue

        class Placeholder(View):
            def __init__(self, win, _title=title):
                super().__init__(win)
                self.page.addWidget(heading(_title)[0])
                self.page.addWidget(label("Coming in the next step of the build.", "muted"))
                self.page.addStretch(1)
        Placeholder.name, Placeholder.title, Placeholder.section = name, title, section
        out.append(Placeholder)
    return out
