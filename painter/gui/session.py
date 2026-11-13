"""What the window knows between screens: the Canvas connection, the
signed-in user, their courses, the chosen course and the saved settings."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from painter import credentials as default_store
from painter.canvas.client import Canvas, check_base_url
from painter.config import Settings, load_settings, save_settings
from painter.services.courses import CourseInfo, list_courses, whoami


def check_connection(base_url: str, token: str):
    """Runs on a worker thread: (canvas, display name, courses)."""
    canvas = Canvas(check_base_url(base_url), token)
    return canvas, whoami(canvas), list_courses(canvas)


class Session(QObject):
    connected = Signal(str)               # display name
    course_changed = Signal(object)       # CourseInfo | None

    def __init__(self, settings_path: Path | None = None, env=None, store=default_store):
        super().__init__()
        self.settings_path = settings_path
        self.settings: Settings = load_settings(settings_path)
        self.env = env
        self.store = store
        self.canvas: Canvas | None = None
        self.me = ""
        self.courses: list[CourseInfo] = []
        self.course: CourseInfo | None = None

    # ---- token and connection ----
    def saved_token(self, base_url: str) -> tuple[str | None, str | None]:
        return self.store.get_token(base_url, env=self.env)

    def can_remember(self) -> bool:
        return self.store.keyring_available()

    def use(self, canvas: Canvas, me: str, courses: list[CourseInfo],
            token: str | None = None, remember: bool = False) -> None:
        """Adopt a checked connection. remember: keep token in the credential store."""
        self.canvas, self.me, self.courses = canvas, me, courses
        if token is not None:
            if remember:
                self.store.set_token(canvas.base, token)
            else:
                self.store.clear_token(canvas.base)
        self.settings.base_url = canvas.base
        self.save()
        self.connected.emit(me)
        last = next((c for c in courses if c.id == self.settings.course_id), None)
        if last:
            self.choose_course(last)

    def forget_token(self) -> None:
        if self.settings.base_url:
            self.store.clear_token(self.settings.base_url)

    # ---- course ----
    def choose_course(self, course: CourseInfo | None) -> None:
        self.course = course
        self.settings.course_id = course.id if course else None
        self.save()
        self.course_changed.emit(course)

    def save(self) -> None:
        try:
            save_settings(self.settings, self.settings_path)
        except OSError:
            pass                           # settings are a convenience, never fatal
