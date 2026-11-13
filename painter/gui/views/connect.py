"""Screen 1: connect to Canvas (first run, and Settings later)."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFormLayout, QLabel, QLineEdit, QMessageBox, QWidget,
)

from painter.config import TOKEN_ENV
from painter.gui.session import ENV, check_connection
from painter.gui.views import View
from painter.gui.widgets import Banner, Card, button, heading, hbox, label, show_problem
from painter.gui.worker import TaskRunner

NEW = "new"                      # the "New token…" entry in the drop-down
HOW_TO = "Make one in Canvas: Account › Settings › New access token."


def _row(*items) -> QWidget:
    w = QWidget()
    w.setLayout(hbox(*items))
    return w


class ConnectView(View):
    name = "connect"
    title = "Settings"

    def __init__(self, win):
        super().__init__(win)
        head, _, _ = heading(
            "Connect to Canvas",
            "Painter works with your own Canvas account, as a teacher or a TA. It needs "
            "your school's Canvas address and an access token. Both stay on this computer.",
            "Settings")
        self.page.addWidget(head)

        self.page.addWidget(self._form_card())
        self.page.addWidget(self._data_card())

        self.banner = Banner()
        self.page.addWidget(self.banner)
        self.test_btn = button("Test connection", "secondary", self.test)
        self.go_btn = button("Continue", "primary", self.proceed)
        self.page.addLayout(hbox(self.test_btn, self.go_btn, None))
        self.page.addStretch(1)

        self.lookup = TaskRunner(self)
        self.lookup.finished.connect(self._ok)
        self.lookup.failed.connect(self._failed)
        self._then_continue = False
        self._checked = None               # (url, token) last verified
        self._filling = False
        self.url.returnPressed.connect(self.proceed)
        self.token.returnPressed.connect(self.proceed)

    def _form_card(self) -> Card:
        card = Card(padding=22)
        form = QFormLayout()
        form.setSpacing(12)

        self.saved = QComboBox()
        self.saved.setAccessibleName("Saved tokens")
        self.saved.setMinimumContentsLength(28)
        self.saved.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.saved.currentIndexChanged.connect(self._chosen)
        self.remove_btn = button("Remove", "", self.remove_saved,
                                 "Forget this saved token on this computer")
        saved_row = _row(self.saved, self.remove_btn)
        saved_row.layout().setStretch(0, 1)
        form.addRow(label("Saved tokens", "h2"), saved_row)

        self.url = QLineEdit()
        self.url.setPlaceholderText("https://yourschool.instructure.com")
        self.url.setAccessibleName("Canvas address")
        form.addRow(label("Canvas address", "h2"), self.url)

        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setAccessibleName("Access token")
        self.token.textEdited.connect(self._token_typed)
        self.show_btn = button("Show", "", self._toggle_show)
        tok_row = _row(self.token, self.show_btn)
        tok_row.layout().setStretch(0, 1)
        form.addRow(label("Access token", "h2"), tok_row)
        self.token_note = label(HOW_TO, "muted", wrap=True)
        form.addRow(QLabel(""), self.token_note)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Optional, e.g. Fall term token")
        self.label_edit.setAccessibleName("Token name")
        form.addRow(label("Name", "h2"), self.label_edit)

        self.has_expiry = QCheckBox("Expires on")
        self.has_expiry.setAccessibleName("Token has an expiration date")
        self.expires = QDateEdit()
        self.expires.setCalendarPopup(True)
        self.expires.setDisplayFormat("MMM d, yyyy")
        self.expires.setAccessibleName("Expiration date")
        self.expires.setEnabled(False)
        self.has_expiry.toggled.connect(self.expires.setEnabled)
        self.expiry_note = label("Optional. Painter warns you in the week before it runs out.",
                                 "muted", wrap=True)
        form.addRow(label("Expiration", "h2"), _row(self.has_expiry, self.expires, None))
        form.addRow(QLabel(""), self.expiry_note)
        card.body.addLayout(form)

        self.remember = QCheckBox("Remember on this computer")
        self.remember.setChecked(True)
        self.remember_note = label("", "muted", wrap=True)
        card.body.addWidget(self.remember)
        card.body.addWidget(self.remember_note)
        return card

    def _data_card(self) -> Card:
        card = Card(padding=22)
        card.body.addWidget(label("Saved course data", "h2"))
        self.data_note = label("", "muted", wrap=True)
        self.clear_btn = button("Clear saved course data", "", self.clear_data)
        card.body.addWidget(self.data_note)
        card.body.addLayout(hbox(self.clear_btn, None))
        return card

    def _data_text(self) -> None:
        cache = self.session.cache
        n, kb = len(cache.files()), cache.size() / 1024
        self.data_note.setText(
            "Assignment lists, rosters and file counts are kept here so screens open at once "
            "and are checked with Canvas in the background. Grades and comments are never "
            f"kept. {n} file{'s' * (n != 1)}, {kb:.0f} KB, in {cache.root}")
        self.clear_btn.setEnabled(n > 0)

    def clear_data(self):
        ans = QMessageBox.question(
            self, "Clear saved course data?",
            "Painter will ask Canvas again the next time you open a course. Downloaded "
            "files are not touched.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self.session.cache.clear()
        self._data_text()
        self.banner.set("ok", "Saved course data cleared")

    # ---- the saved-token drop-down ----
    def choice(self) -> str:
        return self.saved.currentData() or NEW

    def _fill_saved(self, select: str) -> None:
        """Rebuild the drop-down and select `select` (an id, ENV or NEW)."""
        s = self.session
        self._entries = {t.id: t for t in s.saved_tokens()}
        self._filling = True
        self.saved.clear()
        for t in self._entries.values():
            self.saved.addItem(t.title(), t.id)
        if s.env_token():
            self.saved.addItem(f"From {TOKEN_ENV} (environment variable)", ENV)
        self.saved.addItem("New token…", NEW)
        i = self.saved.findData(select)
        self.saved.setCurrentIndex(i if i >= 0 else self.saved.count() - 1)
        self._filling = False
        self._chosen()

    def _chosen(self, *_):
        if self._filling:
            return
        choice, s = self.choice(), self.session
        entry = self._entries.get(choice)
        can = s.can_remember()
        self.remove_btn.setEnabled(entry is not None)
        self.remove_btn.setToolTip(
            "Forget this saved token on this computer" if entry else
            f"Clear the {TOKEN_ENV} variable to stop offering it" if choice == ENV else
            "Nothing saved to remove")
        self.banner.set("info")
        if entry:
            token = s.token_for(choice)
            self.url.setText(entry.base_url)
            self.token.setText(token or "")
            self.label_edit.setText(entry.label)
            self._set_expiry(entry.expiry())
            self.token_note.setText(HOW_TO)
            self.remember.setChecked(can)
            if not token:
                self.banner.set("attention", "This saved token couldn't be read",
                                "Remove it and paste the token again.")
            elif entry.expiring():
                self._expiry_banner(entry)
        elif choice == ENV:
            self.token.setText(s.env_token() or "")
            self.label_edit.clear()
            self._set_expiry(None)
            self.token_note.setText(
                f"From the {TOKEN_ENV} environment variable. Pick a saved token or "
                "“New token…” to use a different one.")
            self.remember.setChecked(False)
        else:
            self.token.clear()
            self.label_edit.clear()
            self._set_expiry(None)
            self.token_note.setText(HOW_TO)
            self.remember.setChecked(can)
        self.remember.setEnabled(can)
        self.remember_note.setText(
            ("Saved in Windows Credential Manager, not in a file. Use Remove to forget a "
             "saved token." if choice != ENV else
             "Tick to save this token here too, so it works without the variable.")
            if can else
            f"No credential store here, so tokens can't be remembered. Set {TOKEN_ENV} "
            "or paste the token each time.")

    def _token_typed(self, _text):
        """Typing over a saved or environment token makes it a new one."""
        if self.choice() == NEW:
            return
        self._filling = True
        self.saved.setCurrentIndex(self.saved.findData(NEW))
        self._filling = False
        self.label_edit.clear()
        self._set_expiry(None)
        self.remove_btn.setEnabled(False)
        self.token_note.setText(HOW_TO)
        self.remember.setChecked(self.session.can_remember())
        self.banner.set("info")

    def _set_expiry(self, when: date | None) -> None:
        self.has_expiry.setChecked(when is not None)
        when = when or date.today() + timedelta(days=30)
        self.expires.setDate(QDate(when.year, when.month, when.day))

    def expiry_text(self) -> str:
        if not self.has_expiry.isChecked():
            return ""
        return self.expires.date().toPython().isoformat()

    def _expiry_banner(self, entry) -> None:
        left = entry.days_left()
        end = entry.expiry()
        when = f"{end:%A, %B} {end.day}"
        if left < 0:
            self.banner.set("attention", "This token has expired",
                            f"It expired on {when}. Make a new one in Canvas (Account › "
                            "Settings › New access token), then remove this one.")
        else:
            days = "today" if left == 0 else "tomorrow" if left == 1 else f"in {left} days"
            self.banner.set("attention", f"This token expires {days}",
                            f"Canvas stops accepting it on {when}. Make a new one in Canvas "
                            "(Account › Settings › New access token) before then.")

    def remove_saved(self):
        entry = self._entries.get(self.choice())
        if entry is None:
            return
        ans = QMessageBox.question(
            self, "Remove saved token?",
            f"Forget “{entry.label or entry.host} · …{entry.hint}” on this computer? "
            "Canvas keeps the token until you delete it there.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self.session.remove_token(entry.id)
        self._checked = None
        self._fill_saved(NEW)
        self.banner.set("ok", "Saved token removed",
                        f"“{entry.label or entry.host} · …{entry.hint}” is no longer "
                        "remembered on this computer.")

    # ---- state ----
    def enter(self, auto: bool = False, **kw) -> None:
        s = self.session
        self._data_text()
        if s.canvas is not None and self._checked:
            return                                   # back in Settings: leave it as it was
        if not self.url.text():
            self.url.setText(s.settings.base_url)
        saved = s.saved_tokens()
        last = s.settings.credential_id
        if last == ENV and s.env_token():
            select = ENV
        elif any(t.id == last for t in saved):
            select = last
        elif s.env_token():
            select = ENV
        else:
            host = s.settings.base_url.rstrip("/")
            select = next((t.id for t in saved if t.base_url == host), NEW)
        self._fill_saved(select)
        if not self.url.text():
            self.url.setText(s.settings.base_url)
        if auto and self.token.text() and self.url.text() and s.settings.base_url:
            entry = self._entries.get(self.choice())
            if entry is None or not entry.expiring() or entry.days_left() >= 0:
                self._run(then_continue=True)

    def _toggle_show(self):
        hidden = self.token.echoMode() == QLineEdit.Password
        self.token.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)
        self.show_btn.setText("Hide" if hidden else "Show")

    def _inputs(self):
        return self.url.text().strip(), self.token.text().strip()

    def test(self):
        self._run(then_continue=False)

    def proceed(self):
        if self._checked == self._inputs() and self.session.canvas:
            try:
                self.session.settings.credential_id = self._keep(self.session.canvas.base)
            except Exception as exc:                     # credential store refused
                show_problem(self.banner, exc)
                return
            self.session.save()
            self.win.go("home")
        else:
            self._run(then_continue=True)

    def _run(self, then_continue: bool):
        url, token = self._inputs()
        if not url or not token:
            self.banner.set("error", "Fill in both fields",
                            "Painter needs the Canvas address and an access token.")
            return
        if self.lookup.running:
            return
        self._then_continue = then_continue
        self.banner.set("info", "Checking…", f"Connecting to {url}.")
        self.test_btn.setEnabled(False)
        self.lookup.start(check_connection, url, token)

    def _keep(self, base_url: str) -> str:
        """Save the token if asked; returns the choice to remember for next time."""
        choice = self.choice()
        if not self.remember.isChecked():
            return "" if choice == NEW else choice
        _, token = self._inputs()
        saved = self.session.remember_token(
            base_url, token, self.label_edit.text(), self.expiry_text(),
            choice if choice in self._entries else None)
        self._entries[saved.id] = saved
        return saved.id

    def _ok(self, result):
        canvas, me, courses, user_id = result
        self.test_btn.setEnabled(True)
        try:
            choice = self._keep(canvas.base)
        except Exception as exc:                     # credential store refused
            show_problem(self.banner, exc)
            return
        self.session.use(canvas, me, courses, choice, user_id)
        if choice and choice != self.choice():
            self._fill_saved(choice)                 # show the newly saved token
        self._checked = self._inputs()
        teach = sum(c.role == "Teacher" for c in courses)
        assist = len(courses) - teach
        self.banner.clear_actions()
        entry = self._entries.get(choice)
        if entry and entry.expiring():
            self._expiry_banner(entry)
            self.banner.title.setText(f"Connected as {me}. {self.banner.title.text()}")
        else:
            self.banner.set("ok", f"Connected as {me}",
                            f"You teach {teach} course{'s' * (teach != 1)} and assist in "
                            f"{assist}." if courses else
                            "Token accepted, but Canvas lists no courses where you teach "
                            "or assist.")
        if self._then_continue:
            self.win.go("home")

    def _failed(self, exc):
        self.test_btn.setEnabled(True)
        self._checked = None
        show_problem(self.banner, exc)
        entry = self._entries.get(self.choice())
        if entry is not None:
            self.banner.text.setText(self.banner.text.text() +
                                     "\nIf this saved token is no longer valid, Remove it.")
