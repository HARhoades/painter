"""What the window knows between screens: the Canvas connection, the
signed-in user, their courses, the chosen course and the saved settings."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from painter import credentials as default_store
from painter.canvas.client import Canvas, check_base_url
from painter.config import Settings, cache_root, load_settings, save_settings
from painter.services.courses import CourseInfo, identify, list_courses
from painter.storage.cache import CacheStore, Entry

ENV = "env"                               # the token in CANVAS_API_TOKEN, as a choice


def check_connection(base_url: str, token: str):
    """Runs on a worker thread: (canvas, display name, courses, Canvas user id)."""
    canvas = Canvas(check_base_url(base_url), token)
    user_id, me = identify(canvas)
    return canvas, me, list_courses(canvas), user_id


class Session(QObject):
    connected = Signal(str)               # display name
    course_changed = Signal(object)       # CourseInfo | None

    def __init__(self, settings_path: Path | None = None, env=None, store=default_store,
                 cache_dir: Path | None = None):
        super().__init__()
        self.settings_path = settings_path
        # A session given its own settings file keeps its cache beside it, so
        # tests and side-by-side setups never share one.
        self.cache = CacheStore(cache_dir or (Path(settings_path).parent / "cache"
                                              if settings_path else cache_root()))
        self.user_id: int | None = None
        self.courses_at: datetime | None = None
        self.settings: Settings = load_settings(settings_path)
        self.env = env
        self.store = store
        self.canvas: Canvas | None = None
        self.me = ""
        self.courses: list[CourseInfo] = []
        self.course: CourseInfo | None = None
        self._migrated = False

    # ---- tokens and connection ----
    def can_remember(self) -> bool:
        return self.store.keyring_available()

    def env_token(self) -> str | None:
        return self.store.env_token(self.env)

    def saved_tokens(self):
        """Saved tokens, after moving in any one an earlier version saved."""
        if self.settings.base_url and not self._migrated:
            self._migrated = True
            try:
                moved = self.store.migrate_legacy(self.settings.base_url)
            except Exception:                  # a store that refuses: keep going
                moved = None
            if moved and not self.settings.credential_id:
                self.settings.credential_id = moved.id
                self.save()
        return self.store.list_saved()

    def token_for(self, choice: str) -> str | None:
        """The token behind a choice: a saved-token id or ENV."""
        if choice == ENV:
            return self.env_token()
        return self.store.get_saved(choice)

    def remember_token(self, base_url: str, token: str, label: str = "",
                       expires: str = "", token_id: str | None = None):
        return self.store.save_token(base_url, token, label, expires, token_id)

    def remove_token(self, token_id: str) -> None:
        self.store.remove_saved(token_id)
        if self.settings.credential_id == token_id:
            self.settings.credential_id = ""
            self.save()

    def use(self, canvas: Canvas, me: str, courses: list[CourseInfo],
            choice: str = "", user_id: int | None = None) -> None:
        """Adopt a checked connection. choice: the saved-token id or ENV in use,
        so the next start picks the same one ("" for a token that wasn't saved)."""
        self.canvas, self.me, self.courses = canvas, me, courses
        self.user_id, self.courses_at = user_id, datetime.now(timezone.utc)
        self.settings.base_url = canvas.base
        self.settings.credential_id = choice
        self.save()
        self.connected.emit(me)
        last = next((c for c in courses if c.id == self.settings.course_id), None)
        if last:
            self.choose_course(last)

    # ---- the local cache (see storage/cache.py) ----
    def cache_key(self, course_id: int) -> str:
        """Per Canvas host, signed-in user and course, so a TA's and a teacher's
        views of the same course (or two accounts) never mix."""
        host = (self.canvas.base if self.canvas else self.settings.base_url).split("//")[-1]
        return f"{host}_{self.user_id or 'unknown'}_{course_id}"

    def cached(self, kind: str, course_id: int) -> Entry | None:
        return self.cache.read(kind, self.cache_key(course_id))

    def remember(self, kind: str, course_id: int, data: object) -> Entry:
        return self.cache.write(kind, self.cache_key(course_id), data)

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
