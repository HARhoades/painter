"""Small building blocks shared by the views."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget, QWidgetItem,
)

from painter.domain.freshness import Freshness, describe
from painter.gui.style import ICONS as ICON_DIR, PAINTER

ICONS = {"ok": "✓", "attention": "⚠", "info": "ⓘ", "error": "✕",
         "cached": "↺", "run": "●", "bad": "✕"}


def restyle(w: QWidget, **props) -> QWidget:
    """Set dynamic properties and make the stylesheet notice."""
    for k, v in props.items():
        w.setProperty(k, v)
    w.style().unpolish(w)
    w.style().polish(w)
    return w


def button(text: str, role: str = "", slot=None, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if role:
        b.setProperty("role", role)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def hbox(*items, spacing: int = 10, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, QLabel) and it.wordWrap():
            lay.addWidget(it, 1)
        elif isinstance(it, QLayout):
            lay.addLayout(it)
        else:
            lay.addWidget(it)
    return lay


class FoldButton(QToolButton):
    """A heading that opens and closes a section, with the app's own chevron
    (right when closed, down when open) instead of the system's arrow."""

    def __init__(self, text: str = ""):
        super().__init__()
        self.setObjectName("fold")
        self.setText(text)
        self.setCheckable(True)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(14, 14))
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._chevron)
        self._chevron(False)

    def _chevron(self, open_: bool) -> None:
        name = "chevron-down.svg" if open_ else "chevron-right.svg"
        self.setIcon(QIcon(str(ICON_DIR / name)))


class FreshnessTag(QWidget):
    """Says how old a shown value is ("✓ Up to date · checked 2 min ago"), with
    a small ↻ button to ask Canvas again now."""
    refresh_requested = Signal()

    def __init__(self, tip: str = "Check with Canvas now", with_button: bool = True):
        super().__init__()
        self.text = label("", "tag")
        self.button = button("↻", "icon", self.refresh_requested.emit, tip)
        self.button.setAccessibleName(tip)
        self.button.setVisible(with_button)
        self.setLayout(hbox(self.text, self.button, None, spacing=6))
        self.state = Freshness("none")
        self._clock = QTimer(self)                 # keeps "2 min ago" honest
        self._clock.setInterval(30_000)
        self._clock.timeout.connect(self._show)
        self._clock.start()
        self._show()

    def set(self, f: Freshness | None) -> None:
        """None hides the tag (nothing to say yet)."""
        self.setVisible(f is not None)
        if f is None:
            return
        self.state = f
        self.button.setEnabled(f.state != "checking")
        self._show()

    def _show(self) -> None:
        self.text.setText(describe(self.state))
        self.text.setToolTip(self.state.reason)
        restyle(self.text, kind=self.state.state)


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto new lines to fit the width,
    so a row of chips or names never makes the page wider than the window."""

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self._gap = spacing

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, w):                       # noqa: N802 - Qt naming
        self.addChildWidget(w)
        self.addItem(QWidgetItem(w))

    def count(self):
        return len(self._items)

    def itemAt(self, i):                          # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):                          # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):                # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):                  # noqa: N802
        return True

    def heightForWidth(self, width):              # noqa: N802
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):                  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):                           # noqa: N802
        return self.minimumSize()

    def minimumSize(self):                        # noqa: N802
        size = QSize()
        for it in self._items:
            if not it.isEmpty():
                size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect, move: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = area.x(), area.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            w = min(hint.width(), area.width()) if area.width() > 0 else hint.width()
            if x > area.x() and x + w > area.right() + 1:
                x, y, line = area.x(), y + line + self._gap, 0
            if move:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, hint.height())))
            x += w + self._gap
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()


class Card(QFrame):
    """A surface panel; accent='secondary' | 'primary' | 'ink'."""

    def __init__(self, accent: str = "", padding: int = 18):
        super().__init__()
        self.setObjectName("card")
        if accent:
            self.setProperty("accent", accent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding - 4, padding, padding - 2)
        self.body.setSpacing(10)


class Stroke(QWidget):
    """The rose brush stroke under a page title."""

    def __init__(self, width: int = 200):
        super().__init__()
        self.setFixedSize(width, 14)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(PAINTER.highlight), 7, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        w = self.width()
        path = QPainterPath(QPointF(4, 9))
        path.cubicTo(QPointF(w * 0.2, 3), QPointF(w * 0.46, 2), QPointF(w - 4, 7))
        p.drawPath(path)


class Logo(QWidget):
    """A marigold brush mark with a sage stroke and a rose dot."""

    def sizeHint(self):
        return QSize(36, 24)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        blob = QPainterPath(QPointF(2, 17))
        blob.cubicTo(QPointF(8, 7), QPointF(17, 3), QPointF(31, 6))
        blob.cubicTo(QPointF(24, 8), QPointF(21, 12), QPointF(20, 16))
        blob.cubicTo(QPointF(15, 14), QPointF(9, 15), QPointF(2, 17))
        p.fillPath(blob, QColor(PAINTER.primary))
        p.setPen(QPen(QColor(PAINTER.secondary), 2.5, Qt.SolidLine, Qt.RoundCap))
        line = QPainterPath(QPointF(9, 20))
        line.cubicTo(QPointF(15, 18), QPointF(22, 17), QPointF(29, 18))
        p.drawPath(line)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(PAINTER.highlight))
        p.drawEllipse(QPointF(31, 18), 3.2, 3.2)


def heading(text: str, sub: str = "", kicker: str = "") -> tuple[QWidget, QLabel, QLabel]:
    """(widget, title label, subtitle label) for the top of a page."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    if kicker:
        lay.addWidget(label(kicker.upper(), "kicker"))
    title = label(text, "h1", wrap=True)
    title.setAccessibleName(text)
    lay.addWidget(title)
    lay.addWidget(Stroke())
    subtitle = label(sub, "muted", wrap=True)
    subtitle.setVisible(bool(sub))
    lay.addWidget(subtitle)
    return w, title, subtitle


class Banner(QFrame):
    """kind: attention (rose), info (sage), ok (marigold), error (ink outline).
    Always an icon and words as well as colour."""

    def __init__(self, kind: str = "info", title: str = "", body: str = ""):
        super().__init__()
        self.setObjectName("banner")
        self.icon = QLabel()
        self.icon.setFixedWidth(22)
        self.icon.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.title = label("", "btitle", wrap=True)
        self.text = label("", wrap=True)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        box = QWidget()
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(self.title)
        col.addWidget(self.text)
        col.addLayout(self.actions)
        self.actions.addStretch(1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        lay.addWidget(box, 1)
        self.set(kind, title, body)
        self.setAccessibleName("Status")

    def set(self, kind: str, title: str = "", body: str = "") -> "Banner":
        restyle(self, kind=kind)
        self.icon.setText(ICONS.get(kind, ""))
        self.title.setText(title)
        self.title.setVisible(bool(title))
        self.text.setText(body)
        self.text.setVisible(bool(body))
        self.setVisible(bool(title or body))
        return self

    def add_action(self, b: QPushButton) -> QPushButton:
        self.actions.insertWidget(self.actions.count() - 1, b)
        return b

    def clear_actions(self) -> None:
        for i in reversed(range(self.actions.count())):
            w = self.actions.itemAt(i).widget()
            if w:
                self.actions.takeAt(i)
                w.deleteLater()


def show_problem(banner: Banner, exc: BaseException, open_settings=None) -> None:
    """Put a described exception on a banner, with its follow-up buttons."""
    from PySide6.QtWidgets import QApplication

    from painter.gui.problems import describe
    pr = describe(exc)
    banner.clear_actions()
    banner.set(pr.kind, pr.title, pr.body)
    if pr.settings and open_settings:
        banner.add_action(button("Open settings", "quiet", open_settings))
    if pr.details:
        banner.add_action(button("Copy details", "quiet",
                                 lambda: QApplication.clipboard().setText(str(pr.details))))
        banner.text.setText(f"{pr.body}\nDetails were saved to {pr.details}")


def pill_cell(kind: str, text: str) -> QWidget:
    """A Pill sized to its text, for a table cell."""
    w = QWidget()
    w.setLayout(hbox(Pill(kind, text), None, margins=(4, 2, 4, 2)))
    return w


class Pill(QLabel):
    """Status with shape + icon + words: ok, cached, run, bad."""

    def __init__(self, kind: str = "ok", text: str = ""):
        super().__init__()
        self.setObjectName("pill")
        self.set(kind, text)

    def set(self, kind: str, text: str) -> "Pill":
        restyle(self, kind=kind)
        self.setText(f"{ICONS.get(kind, '')} {text}".strip())
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        return self


def badge(text: str, kind: str = "count") -> QLabel:
    b = QLabel(text)
    b.setObjectName("badge")
    b.setProperty("kind", kind)
    b.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    b.setAlignment(Qt.AlignCenter)
    return b


def grow(layout, index: int = 0):
    """Let item `index` of an hbox take the spare width (for wrapped text)."""
    layout.setStretch(index, 1)
    return layout


class StepBar(QWidget):
    def __init__(self, names=("Files", "Review", "Post and verify")):
        super().__init__()
        self.labels = [QLabel() for _ in names]
        self.names = names
        lay = hbox(*self.labels, None, spacing=8)
        self.setLayout(lay)
        self.set(1)

    def set(self, current: int) -> None:
        for i, (lab, name) in enumerate(zip(self.labels, self.names), start=1):
            lab.setObjectName("step")
            state = "done" if i < current else "current" if i == current else "todo"
            lab.setText(f"{'✓ ' if i < current else ''}{i} {name}")
            lab.setAccessibleName(f"Step {i}, {name}, {state}")
            restyle(lab, state=state)


class FolderPicker(QWidget):
    changed = Signal(str)

    def __init__(self, title: str = "Choose a folder"):
        super().__init__()
        self.title = title
        self.edit = QLineEdit()
        self.edit.setAccessibleName(title)
        self.edit.textChanged.connect(self.changed)
        self.browse = button("Browse…", "", self._browse)
        self.setLayout(hbox(self.edit, self.browse))
        self.layout().setStretch(0, 1)

    def _browse(self):
        start = self.edit.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, self.title, start)
        if path:
            self.edit.setText(path)

    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, p: str) -> None:
        self.edit.setText(p or "")


def scroll_page(widget: QWidget) -> tuple[QScrollArea, QVBoxLayout]:
    """Put a page's content in a scroll area; returns (area, content layout)."""
    area = QScrollArea(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    inner = QWidget()
    inner.setObjectName("page")
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(32, 28, 32, 28)
    lay.setSpacing(18)
    area.setWidget(inner)
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(area)
    return area, lay


def clear(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear(item.layout())
