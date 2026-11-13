"""Screen 1: connect to Canvas (first run, and Settings later)."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QLineEdit, QWidget

from painter.config import TOKEN_ENV
from painter.gui.views import View
from painter.gui.widgets import Banner, Card, button, heading, hbox, label, show_problem
from painter.gui.worker import TaskRunner
from painter.gui.session import check_connection


class ConnectView(View):
    name = "connect"
    title = "Connect"

    def __init__(self, win):
        super().__init__(win)
        head, _, _ = heading(
            "Connect to Canvas",
            "Painter works with your own Canvas account, as a teacher or a TA. It needs "
            "your school's Canvas address and an access token. Both stay on this computer.",
            "Settings")
        self.page.addWidget(head)

        card = Card(padding=22)
        form = QFormLayout()
        form.setSpacing(12)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://yourschool.instructure.com")
        self.url.setAccessibleName("Canvas address")
        form.addRow(label("Canvas address", "h2"), self.url)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setAccessibleName("Access token")
        self.show_btn = button("Show", "", self._toggle_show)
        tok_row = QWidget()
        tok_row.setLayout(hbox(self.token, self.show_btn))
        form.addRow(label("Access token", "h2"), tok_row)
        self.token_note = label("Make one in Canvas: Account › Settings › New access token.",
                                "muted", wrap=True)
        form.addRow(QLabel(""), self.token_note)
        card.body.addLayout(form)
        self.remember = QCheckBox("Remember on this computer")
        self.remember.setChecked(True)
        self.remember_note = label("Saved in Windows Credential Manager, not in a file. "
                                   "Untick and connect again to forget it.", "muted", wrap=True)
        card.body.addWidget(self.remember)
        card.body.addWidget(self.remember_note)
        self.page.addWidget(card)

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
        self.url.returnPressed.connect(self.proceed)
        self.token.returnPressed.connect(self.proceed)

    # ---- state ----
    def enter(self, auto: bool = False, **kw) -> None:
        s = self.session
        if not self.url.text():
            self.url.setText(s.settings.base_url)
        token, where = s.saved_token(self.url.text())
        env = where == "env"
        self.token.setReadOnly(env)
        if token and not self.token.text():
            self.token.setText(token)
        self.token_note.setText(
            f"Using the token in {TOKEN_ENV}. Clear that variable to use a token here."
            if env else "Make one in Canvas: Account › Settings › New access token.")
        can = s.can_remember()
        self.remember.setEnabled(can and not env)
        self.remember.setChecked(can and where != "env" and (where == "keyring" or not token))
        self.remember_note.setText(
            "Saved in Windows Credential Manager, not in a file. Untick and connect again "
            "to forget it." if can else
            f"No credential store here, so the token can't be remembered. Set {TOKEN_ENV} "
            "or paste it each time.")
        if auto and token and s.settings.base_url:
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

    def _ok(self, result):
        canvas, me, courses = result
        self.test_btn.setEnabled(True)
        url, token = self._inputs()
        where = self.session.saved_token(url)[1]
        try:
            self.session.use(canvas, me, courses,
                             None if where == "env" else token, self.remember.isChecked())
        except Exception as exc:                     # credential store refused
            show_problem(self.banner, exc)
            return
        self._checked = (url, token)
        teach = sum(c.role == "Teacher" for c in courses)
        assist = len(courses) - teach
        self.banner.clear_actions()
        self.banner.set("ok", f"Connected as {me}",
                        f"You teach {teach} course{'s' * (teach != 1)} and assist in "
                        f"{assist}." if courses else
                        "Token accepted, but Canvas lists no courses where you teach or assist.")
        if self._then_continue:
            self.win.go("home")

    def _failed(self, exc):
        self.test_btn.setEnabled(True)
        self._checked = None
        show_problem(self.banner, exc)
