"""The look: palette, fonts and the Qt stylesheet built from them."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from string import Template

FONTS = Path(__file__).resolve().parent / "fonts"
ICONS = Path(__file__).resolve().parent / "icons"
HEADING_FONT = "Bricolage Grotesque"
BODY_FONT = "Work Sans"


@dataclass(frozen=True)
class Palette:
    background: str = "#EFE7D5"     # canvas beige
    ink: str = "#252525"            # text and icons
    primary: str = "#F4BE4F"        # marigold: main actions, active nav, selection
    on_primary: str = "#252525"     # text on marigold
    secondary: str = "#8A9C72"      # sage: supporting controls, chips, cards (no text)
    highlight: str = "#B82D58"      # raspberry rose: title strokes, warnings, badges
    on_highlight: str = "#FFFFFF"
    primary_tint: str = "#FCEFCF"
    secondary_tint: str = "#E3E9DA"
    highlight_tint: str = "#F5DFE6"
    surface: str = "#FBF6EC"
    line: str = "#D8CBB2"
    muted: str = "#5E574C"
    field_border: str = "#A89C85"
    well: str = "#E9DDC6"
    primary_hover: str = "#EDB335"  # marigold a shade darker, for hover
    secondary_hover: str = "#D3DCC6"  # sage tint a shade darker, for hover


PAINTER = Palette()

# Brushy corners: QSS takes a horizontal and a vertical radius per corner.
BRUSH = ("border-top-left-radius: 16px 9px; border-top-right-radius: 6px 14px; "
         "border-bottom-right-radius: 14px 7px; border-bottom-left-radius: 5px 13px;")


def load_fonts() -> list[str]:
    """Register the bundled fonts; returns the families Qt accepted."""
    from PySide6.QtGui import QFontDatabase
    families = []
    for f in sorted(FONTS.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            families += QFontDatabase.applicationFontFamilies(fid)
    return families


QSS = Template(r"""
* { font-family: "${body_font}", "Segoe UI", sans-serif; font-size: 14px; color: ${ink}; }
QMainWindow, QWidget#page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: ${background}; }
QWidget#topbar { background: ${surface}; border-bottom: 1px solid ${line}; }
QLabel#brand { font-family: "${heading_font}"; font-size: 20px; font-weight: 700; }
QWidget#sidebar { background: ${surface}; border-right: 1px solid ${line}; }
QLabel#navhead { font-size: 11px; font-weight: 600; color: ${muted}; letter-spacing: 1px; }
QPushButton#nav { text-align: left; min-height: 0; padding: 10px 12px; border: 0; border-radius: 8px;
  background: transparent; font-weight: 500; }
QPushButton#nav:hover { background: ${primary_tint}; }
QPushButton#nav:checked { background: ${primary}; color: ${on_primary}; font-weight: 600; ${brush} }
QPushButton#nav:checked:hover { background: ${primary_hover}; }
QPushButton#nav:disabled { color: ${muted}; }
QPushButton#settings:checked { background: ${primary}; color: ${on_primary}; border: 2px solid ${ink};
  font-weight: 600; ${brush} }
QPushButton#settings:checked:hover { background: ${primary_hover}; }
QListWidget#courses { background: ${surface}; }
QListWidget#courses::item { border: 0; border-bottom: 1px solid ${line}; }
QListWidget#courses::item:hover { background: ${background}; }
QListWidget#courses::item:selected { background: ${primary_tint}; color: ${ink}; }
QLabel#later { color: ${muted}; padding: 6px 12px; }
QLabel#h1 { font-family: "${heading_font}"; font-size: 28px; font-weight: 700; }
QLabel#h2 { font-size: 16px; font-weight: 600; }
QLabel#kicker { font-size: 12px; font-weight: 600; color: ${muted}; letter-spacing: 1px; }
QLabel#muted, QCheckBox#muted { color: ${muted}; font-size: 13px; }
QLabel#big { font-family: "${heading_font}"; font-size: 40px; font-weight: 700; }
QFrame#card { background: ${surface}; border: 1px solid ${line}; border-radius: 12px; }
QFrame#card[accent="secondary"] { border: 2px solid ${secondary}; }
QFrame#card[accent="primary"] { border: 2px solid ${primary}; }
QFrame#card[accent="ink"] { border: 2px solid ${ink}; }
QPushButton { min-height: 40px; padding: 0 18px; border-radius: 10px; font-weight: 500;
  background: transparent; border: 1px solid ${field_border}; }
QPushButton:hover { background: ${well}; }
QPushButton[role="primary"] { background: ${primary}; color: ${on_primary}; border: 0;
  font-weight: 600; padding: 0 24px; ${brush} }
QPushButton[role="primary"]:hover { background: ${primary_hover}; border: 2px solid ${ink}; }
QPushButton[role="secondary"] { background: ${surface}; border: 2px solid ${secondary}; font-weight: 600; }
QPushButton[role="secondary"]:hover { background: ${secondary_tint}; }
QPushButton[role="link"] { border: 0; min-height: 0; padding: 0; text-decoration: underline; }
QPushButton[role="link"]:hover { background: transparent; color: ${highlight}; }
QPushButton[role="icon"] { min-height: 24px; max-height: 24px; min-width: 24px; padding: 0 6px;
  border-radius: 12px; border: 1px solid ${field_border}; font-size: 13px; font-weight: 600; }
QPushButton[role="icon"]:disabled { color: ${muted}; border-color: ${line}; }
QLabel#tag { font-size: 12px; color: ${muted}; }
QLabel#tag[kind="checking"] { font-style: italic; }
QLabel#tag[kind="failed"] { color: ${ink}; font-weight: 600; }
QPushButton:focus { outline: none; border: 2px solid ${ink}; }
QPushButton[role="chip"] { min-height: 32px; padding: 0 14px; border-radius: 16px;
  border: 1px solid ${line}; background: #FFFFFF; }
QPushButton[role="chip"]:hover { background: ${secondary_tint}; }
QPushButton[role="chip"]:checked:hover { background: ${secondary_hover}; }
QPushButton[role="chip"]:checked { border: 2px solid ${secondary}; background: ${secondary_tint}; ${brush} }
QPushButton[role="name"] { min-height: 28px; padding: 0 10px; border-radius: 14px;
  border: 1px solid ${secondary}; background: ${secondary_tint}; font-weight: 400; }
QPushButton[role="name"]:hover { background: ${secondary_hover}; }
QPushButton[role="name"]:checked:hover { background: ${surface}; }
QPushButton[role="name"]:checked { border: 2px solid ${ink}; background: #FFFFFF; color: ${muted};
  text-decoration: line-through; }
QLineEdit, QComboBox, QDateEdit { min-height: 38px; padding: 0 10px; border: 1px solid ${field_border};
  border-radius: 10px; background: #FFFFFF; }
QComboBox, QDateEdit { padding: 0 38px 0 10px; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QComboBox:on { border: 2px solid ${ink}; }
QDateEdit QLineEdit { border: 0; background: transparent; min-height: 0; padding: 0; }
QComboBox::drop-down, QDateEdit::drop-down { subcontrol-origin: border; subcontrol-position: center right;
  width: 34px; border: 0; border-left: 1px solid ${line}; background: transparent;
  border-top-right-radius: 9px; border-bottom-right-radius: 9px; }
QComboBox::drop-down:hover, QDateEdit::drop-down:hover { background: ${primary_tint}; }
QComboBox::down-arrow, QDateEdit::down-arrow { image: url("${chevron_down}"); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: ${surface}; border: 1px solid ${field_border}; border-radius: 6px;
  padding: 4px; outline: 0; selection-background-color: ${primary_tint}; selection-color: ${ink}; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 0 8px; border-radius: 6px; }
QToolButton#fold { border: 0; background: transparent; font-weight: 600; padding: 4px 2px; }
QToolButton#fold:hover { text-decoration: underline; }
QToolButton#fold:disabled { color: ${muted}; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background: ${surface}; }
QCalendarWidget QToolButton { background: transparent; border: 0; border-radius: 6px; padding: 4px 8px; min-height: 0; }
QCalendarWidget QToolButton:hover { background: ${primary_tint}; }
QCalendarWidget QToolButton#qt_calendar_prevmonth { qproperty-icon: url("${chevron_left}"); }
QCalendarWidget QToolButton#qt_calendar_nextmonth { qproperty-icon: url("${chevron_right}"); }
QCalendarWidget QToolButton::menu-indicator { image: url("${chevron_down}"); width: 12px; height: 12px;
  subcontrol-position: right center; subcontrol-origin: padding; }
QCalendarWidget QAbstractItemView:enabled { background: ${surface}; color: ${ink};
  selection-background-color: ${primary}; selection-color: ${ink}; }
QCalendarWidget QAbstractItemView:disabled { color: ${muted}; }
QCheckBox, QRadioButton { spacing: 10px; }
QCheckBox::indicator, QRadioButton::indicator { width: 18px; height: 18px; border: 2px solid #7A705F; background: #FFFFFF; }
QCheckBox::indicator { border-radius: 5px; }
QRadioButton::indicator { border-radius: 11px; }
QCheckBox::indicator:checked { background: ${primary}; border-color: ${ink}; image: url("${check_icon}"); }
QRadioButton::indicator:checked { background: ${primary}; border: 5px solid ${ink}; }
QProgressBar { background: ${surface}; border: 2px solid ${ink}; border-radius: 12px; min-height: 22px;
  max-height: 22px; text-align: center; font-weight: 600; color: ${ink}; }
QProgressBar::chunk { background: ${primary}; border-radius: 8px; margin: 1px; }
QProgressBar#student { background: ${well}; border: 1px solid ${secondary}; border-radius: 5px;
  min-height: 8px; max-height: 8px; }
QProgressBar#student::chunk { background: ${secondary}; border-radius: 4px; margin: 0; }
QTableWidget, QTreeWidget, QListWidget { background: #FFFFFF; border: 1px solid ${line}; border-radius: 10px;
  gridline-color: ${line}; alternate-background-color: ${surface}; }
QTableWidget::item:selected, QListWidget::item:selected { background: ${primary_tint}; color: ${ink}; }
QHeaderView::section { background: ${surface}; border: 0; border-bottom: 1px solid ${line};
  padding: 6px 8px; font-size: 12px; font-weight: 600; color: ${muted}; }
QPlainTextEdit#log { background: #FFFFFF; border: 1px solid ${line}; border-radius: 10px;
  font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }
QFrame#banner { border-radius: 12px; }
QFrame#banner[kind="attention"] { background: ${highlight_tint}; border: 2px solid ${highlight}; }
QFrame#banner[kind="info"] { background: ${secondary_tint}; border: 1px solid ${secondary}; }
QFrame#banner[kind="ok"] { background: ${primary_tint}; border: 1px solid ${primary}; }
QFrame#banner[kind="error"] { background: #FFFFFF; border: 2px solid ${ink}; }
QLabel#pill { padding: 2px 10px; border-radius: 11px; font-size: 12px; font-weight: 600; }
QLabel#pill[kind="ok"] { background: ${secondary_tint}; border: 1px solid ${secondary}; }
QLabel#pill[kind="cached"] { background: ${well}; border: 1px solid ${line}; }
QLabel#pill[kind="run"] { background: ${primary_tint}; border: 1px solid ${primary}; }
QLabel#pill[kind="bad"] { background: #FFFFFF; border: 2px solid ${ink}; }
QLabel#btitle { font-weight: 600; }
QLabel#badge { padding: 2px 10px; border-radius: 10px; font-size: 12px; font-weight: 600; }
QLabel#badge[kind="warn"] { background: ${highlight}; color: ${on_highlight}; }
QLabel#badge[kind="count"] { background: ${secondary_tint}; border: 1px solid ${secondary}; }
QLabel#badge[kind="plain"] { background: #FFFFFF; border: 1px solid ${line}; }
QLabel#step { padding: 6px 14px; border-radius: 15px; font-size: 13px; border: 1px solid ${line}; background: ${surface}; color: ${muted}; }
QLabel#step[state="done"] { background: ${secondary_tint}; border: 1px solid ${secondary}; color: ${ink}; }
QLabel#step[state="current"] { background: ${primary}; color: ${on_primary}; border: 0; font-weight: 600; ${brush} }
QFrame#drop { border: 2px dashed ${secondary}; background: ${secondary_tint}; ${brush} }
QFrame#row[state="selected"] { background: ${primary_tint}; border: 2px solid ${primary}; ${brush} }
QFrame#row { background: ${surface}; border: 1px solid ${line}; border-radius: 12px; }
QFrame#row:hover { border-color: ${field_border}; }
QFrame#summary { background: ${surface}; border: 2px solid ${primary}; border-radius: 14px; }
QDialog { background: ${surface}; }
QToolTip { background: ${ink}; color: #FFFFFF; border: 0; padding: 4px 8px; }
""")


def build_qss(p: Palette = PAINTER) -> str:
    """The stylesheet. Widgets opt in with object names and properties:
    QPushButton[role="primary" | "secondary" | "chip" | "name" | "link"],
    QLabel#h1/#h2/#kicker/#muted/#big, QFrame#card[accent=...],
    QFrame#banner[kind=...], QLabel#pill[kind=...], QLabel#step[state=...]."""
    return QSS.substitute(asdict(p), brush=BRUSH, body_font=BODY_FONT,
                          heading_font=HEADING_FONT,
                          check_icon=(ICONS / "check.svg").as_posix(),
                          chevron_down=(ICONS / "chevron-down.svg").as_posix(),
                          chevron_left=(ICONS / "chevron-left.svg").as_posix(),
                          chevron_right=(ICONS / "chevron-right.svg").as_posix())


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio of two #RRGGBB colours."""
    def lum(h: str) -> float:
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)
