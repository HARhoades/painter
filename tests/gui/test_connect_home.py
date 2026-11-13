"""Shell, Connect and Home (phase 5, steps 8-9)."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from conftest import BASE, MemoryStore, connect_window, make_response  # noqa: E402


def test_first_run_shows_connect_and_tasks_wait_for_a_connection(window):
    assert window.current is window.views["connect"]
    window._nav("download_setup")
    assert window.current is window.views["connect"]


def test_connect_remembers_token_and_lists_courses(window, qtbot):
    connect_window(window, qtbot)
    v = window.views["connect"]
    assert v.banner.title.text() == "Connected as Hunter Rhoades"
    assert "teach 2 courses and assist in 1" in v.banner.text.text()
    assert [(t.base_url, window.store.secrets[t.id]) for t in window.store.saved] == \
        [(BASE, "test-token")]
    assert window.session.settings.credential_id == window.store.saved[0].id
    assert window.session.settings.base_url == BASE
    assert "token" not in (window.session.settings_path).read_text(encoding="utf-8")
    home = window.views["home"]
    assert [home.list.item(i).data(0x0100).id for i in range(home.list.count())] == [100, 200]


def test_unticking_remember_does_not_save_a_new_token(window, qtbot):
    v = window.views["connect"]
    v.url.setText(BASE)
    v.token.setText("test-token")
    v.remember.setChecked(False)
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        v.test()
    assert window.store.saved == []
    assert window.current is v                       # Test doesn't move on


def test_bad_token_says_so_with_a_way_to_settings(window, courses, qtbot):
    courses.extra[("GET", "/api/v1/users/self")] = make_response(
        f"{BASE}/api/v1/users/self", 401, {"errors": [{"message": "Invalid access token."}]})
    v = window.views["connect"]
    v.url.setText(BASE)
    v.token.setText("nope")
    with qtbot.waitSignal(v.lookup.failed, timeout=5000):
        v.proceed()
    assert v.banner.title.text() == "Canvas didn't accept your token"
    assert window.current is v and window.store.saved == []


def test_http_address_is_refused_in_plain_words(window, qtbot):
    v = window.views["connect"]
    v.url.setText("http://canvas.test")
    v.token.setText("t")
    with qtbot.waitSignal(v.lookup.failed, timeout=5000):
        v.proceed()
    assert v.banner.text.text().startswith("The Canvas address must be an https:// address")


def test_environment_token_is_a_choice_not_a_lock(painter_qapp, courses, tmp_path, qtbot):
    from painter.gui.app import MainWindow
    from painter.gui.session import ENV, Session
    win = MainWindow(Session(tmp_path / "s.json", env={"CANVAS_API_TOKEN": "env-token"},
                             store=MemoryStore()))
    qtbot.addWidget(win)
    v = win.views["connect"]
    assert v.choice() == ENV and v.token.text() == "env-token"
    assert not v.token.isReadOnly() and v.remember.isEnabled()
    assert "CANVAS_API_TOKEN" in v.token_note.text()
    v.remember.setChecked(True)
    assert v.remember.isChecked()
    qtbot.keyClicks(v.token, "X")                    # typing over it makes a new token
    assert v.choice() == "new" and v.token.text() == "env-tokenX"


def _with_saved(painter_qapp, tmp_path, qtbot, *tokens, env=None):
    from painter.gui.app import MainWindow
    from painter.gui.session import Session
    store = MemoryStore()
    for args in tokens:
        store.save_token(*args)
    win = MainWindow(Session(tmp_path / "s.json", env=env or {}, store=store))
    win.store = store
    qtbot.addWidget(win)
    return win


def test_saved_tokens_drop_down_fills_and_removes(painter_qapp, courses, tmp_path, qtbot,
                                                  monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _with_saved(painter_qapp, tmp_path, qtbot, (BASE, "first-token", "Fall"),
                      (BASE, "second-token", "Spring"))
    v = win.views["connect"]
    texts = [v.saved.itemText(i) for i in range(v.saved.count())]
    assert texts == ["Fall · …oken", "Spring · …oken", "New token…"]
    v.saved.setCurrentIndex(1)
    assert v.token.text() == "second-token" and v.label_edit.text() == "Spring"
    assert v.url.text() == BASE and v.remove_btn.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    v.remove_saved()
    assert [t.label for t in win.store.saved] == ["Fall"]
    assert v.choice() == "new" and v.banner.title.text() == "Saved token removed"
    assert not v.remove_btn.isEnabled()


def test_expiring_token_warns_when_chosen(painter_qapp, courses, tmp_path, qtbot):
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=3)).isoformat()
    later = (date.today() + timedelta(days=60)).isoformat()
    win = _with_saved(painter_qapp, tmp_path, qtbot, (BASE, "later-token", "Later", later),
                      (BASE, "soon-token", "Soon", soon))
    v = win.views["connect"]
    v.saved.setCurrentIndex(0)
    assert not v.banner.isVisible() or "expires" not in v.banner.title.text()
    v.saved.setCurrentIndex(1)
    assert v.banner.title.text() == "This token expires in 3 days"
    assert "⚠ expires" in v.saved.itemText(1)


def test_expired_token_says_expired(painter_qapp, courses, tmp_path, qtbot):
    from datetime import date, timedelta
    past = (date.today() - timedelta(days=2)).isoformat()
    win = _with_saved(painter_qapp, tmp_path, qtbot, (BASE, "old-token", "Old", past))
    v = win.views["connect"]
    v.saved.setCurrentIndex(0)
    assert v.banner.title.text() == "This token has expired"
    assert "⚠ expired" in v.saved.itemText(0)


def test_new_token_saves_name_and_expiry(window, qtbot):
    from datetime import date
    from PySide6.QtCore import QDate
    v = window.views["connect"]
    v.url.setText(BASE)
    v.token.setText("test-token")
    v.label_edit.setText("Fall term")
    v.has_expiry.setChecked(True)
    v.expires.setDate(QDate(2030, 1, 15))
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        v.test()
    [t] = window.store.saved
    assert (t.label, t.expires, t.hint) == ("Fall term", "2030-01-15", "oken")
    assert v.choice() == t.id and date(2030, 1, 15) == t.expiry()


def test_settings_button_shows_where_you_are(window, qtbot):
    b = window.settings_btn
    assert b.isChecked() and "Settings" in b.text()      # first run: on Settings
    connect_window(window, qtbot)
    assert not b.isChecked() and b.text().endswith("Settings")
    window.open_settings()
    assert window.current is window.views["connect"]
    assert b.isChecked() and b.text().endswith("Close settings")
    window.open_settings()                               # pressed again: back to courses
    assert window.current is window.views["home"] and not b.isChecked()


def test_saved_connection_reconnects_on_start(painter_qapp, courses, tmp_path, qtbot):
    from painter.config import Settings, save_settings
    from painter.gui.app import MainWindow
    from painter.gui.session import Session
    save_settings(Settings(base_url=BASE, course_id=200), tmp_path / "s.json")
    store = MemoryStore()
    store.set_token(BASE, "test-token")
    win = MainWindow.__new__(MainWindow)
    session = Session(tmp_path / "s.json", env={}, store=store)
    with qtbot.waitSignal(session.connected, timeout=5000):
        MainWindow.__init__(win, session)
    qtbot.addWidget(win)
    qtbot.waitUntil(lambda: win.current is win.views["home"], timeout=5000)
    assert session.course.id == 200 and "Bridge Course" in win.course_btn.text()
    assert store.tokens == {} and [t.label for t in store.saved] == ["Saved token"]


def test_home_filters_roles_and_terms(window, qtbot):
    connect_window(window, qtbot)
    home = window.views["home"]
    home.current.setChecked(False)
    assert home.list.count() == 3
    home.ta.setChecked(False)
    assert [c.id for c in home.visible_courses()] == [100, 300]
    home.filter.setText("arch")
    assert [c.id for c in home.visible_courses()] == [300]
    home.filter.setText("zzz")
    assert home.empty.isVisible() or "No courses match" in home.empty.text()


def test_choosing_a_course_persists_and_unlocks_tasks(window, qtbot):
    connect_window(window, qtbot)
    home = window.views["home"]
    home._task("download_setup")
    assert window.current is home and home.banner.title.text() == "Choose a course first"
    home.list.setCurrentRow(0)
    assert window.session.course.id == 100
    assert window.session.settings_path.read_text(encoding="utf-8").count('"course_id": 100')
    home._task("download_setup")
    assert window.current is window.views["download_setup"]
    assert window.nav["download"].isChecked()


def test_refresh_says_what_it_is_doing_and_what_it_found(window, qtbot):
    connect_window(window, qtbot)
    home = window.views["home"]
    home.refresh()
    assert home.banner.title.text() == "Refreshing the course list…"
    assert not home.refresh_btn.isEnabled() and home.refresh_btn.text() == "Refreshing…"
    qtbot.waitUntil(lambda: home.refresh_btn.isEnabled(), timeout=5000)
    assert home.banner.title.text() == "Course list refreshed"
    assert "No changes" in home.banner.text.text()


def test_course_list_is_beige_with_lines(window, qtbot):
    from painter.gui.style import build_qss
    connect_window(window, qtbot)
    home = window.views["home"]
    assert home.list.objectName() == "courses"
    assert "QListWidget#courses::item { border: 0; border-bottom" in build_qss()
    assert "Painter remembers" not in home.sub.text()
