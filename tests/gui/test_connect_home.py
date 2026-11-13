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
    assert window.store.tokens == {BASE: "test-token"}
    assert window.session.settings.base_url == BASE
    assert "token" not in (window.session.settings_path).read_text(encoding="utf-8")
    home = window.views["home"]
    assert [home.list.item(i).data(0x0100).id for i in range(home.list.count())] == [100, 200]


def test_unticking_remember_forgets_the_token(window, qtbot):
    window.store.set_token(BASE, "old")
    v = window.views["connect"]
    v.url.setText(BASE)
    v.token.setText("test-token")
    v.remember.setChecked(False)
    with qtbot.waitSignal(v.lookup.finished, timeout=5000):
        v.test()
    assert window.store.tokens == {}
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
    assert window.current is v and window.store.tokens == {}


def test_http_address_is_refused_in_plain_words(window, qtbot):
    v = window.views["connect"]
    v.url.setText("http://canvas.test")
    v.token.setText("t")
    with qtbot.waitSignal(v.lookup.failed, timeout=5000):
        v.proceed()
    assert v.banner.text.text().startswith("The Canvas address must be an https:// address")


def test_environment_token_is_read_only(painter_qapp, courses, tmp_path, qtbot):
    from painter.gui.app import MainWindow
    from painter.gui.session import Session
    win = MainWindow(Session(tmp_path / "s.json", env={"CANVAS_API_TOKEN": "env-token"},
                             store=MemoryStore()))
    qtbot.addWidget(win)
    v = win.views["connect"]
    assert v.token.isReadOnly() and v.token.text() == "env-token"
    assert not v.remember.isEnabled() and "CANVAS_API_TOKEN" in v.token_note.text()


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
