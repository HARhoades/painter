"""Token storage and window settings (phase 5)."""
import json

import pytest

keyring = pytest.importorskip("keyring")
from keyring.backend import KeyringBackend  # noqa: E402

from painter import credentials  # noqa: E402
from painter.config import Settings, load_settings, save_settings
from painter.errors import MissingDependency


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, password):
        self.store[(service, user)] = password

    def delete_password(self, service, user):
        self.store.pop((service, user))


@pytest.fixture
def memory_keyring():
    old = keyring.get_keyring()
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    yield kr
    keyring.set_keyring(old)


def test_token_round_trip_per_host(memory_keyring):
    credentials.set_token("https://school.instructure.com/", "abc")
    assert memory_keyring.store == {("painter", "school.instructure.com"): "abc"}
    assert credentials.get_token("https://SCHOOL.instructure.com", env={}) == ("abc", "keyring")
    assert credentials.get_token("https://other.test", env={}) == (None, None)
    credentials.clear_token("https://school.instructure.com")
    credentials.clear_token("https://school.instructure.com")     # already clear: fine
    assert credentials.get_token("https://school.instructure.com", env={}) == (None, None)


def test_environment_wins(memory_keyring):
    credentials.set_token("https://school.test", "stored")
    assert credentials.get_token("https://school.test", env={"CANVAS_API_TOKEN": "env"}) \
        == ("env", "env")


def test_no_credential_store(monkeypatch):
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    assert not credentials.keyring_available()
    assert credentials.get_token("https://school.test", env={}) == (None, None)
    with pytest.raises(MissingDependency, match="CANVAS_API_TOKEN"):
        credentials.set_token("https://school.test", "abc")


def test_settings_defaults_when_missing_or_broken(tmp_path):
    assert load_settings(tmp_path / "none.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_settings(bad) == Settings()


def test_settings_round_trip_keeps_unknown_keys(tmp_path):
    p = tmp_path / "s" / "settings.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"base_url": "https://x.test", "future_key": [1]}), encoding="utf-8")
    s = load_settings(p)
    assert s.base_url == "https://x.test" and s.extra == {"future_key": [1]}
    s.course_id = 100
    s.options = {"flat": True}
    save_settings(s, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["course_id"] == 100 and data["future_key"] == [1] and data["options"] == {"flat": True}
    assert "token" not in p.read_text(encoding="utf-8")
    assert not list(p.parent.glob("*.part"))


def test_settings_never_hold_a_token(tmp_path):
    s = Settings(extra={"token": "abc"})
    with pytest.raises(ValueError):
        save_settings(s, tmp_path / "settings.json")


def test_several_saved_tokens_with_names_and_dates(memory_keyring):
    a = credentials.save_token("https://school.test/", "aaaa-1111", "Fall", "2027-01-15")
    b = credentials.save_token("https://school.test", "bbbb-2222", "Spring")
    assert [t.label for t in credentials.list_saved()] == ["Fall", "Spring"]
    assert credentials.get_saved(a.id) == "aaaa-1111" and credentials.get_saved(b.id) == "bbbb-2222"
    assert a.hint == "1111" and a.base_url == "https://school.test"
    # the index never holds a token
    index = memory_keyring.store[("painter", credentials.INDEX)]
    assert "aaaa-1111" not in index and "bbbb-2222" not in index
    # saving the same token again updates it instead of adding another
    again = credentials.save_token("https://school.test", "aaaa-1111", "Fall term")
    assert again.id == a.id and len(credentials.list_saved()) == 2
    credentials.remove_saved(a.id)
    credentials.remove_saved(a.id)                         # already gone: fine
    assert [t.id for t in credentials.list_saved()] == [b.id]
    assert credentials.get_saved(a.id) is None


def test_expiry_warning_window():
    from datetime import date
    t = credentials.SavedToken("x", "https://s.test", "Fall", "2026-11-20", "1234")
    assert t.days_left(date(2026, 11, 13)) == 7 and t.expiring(date(2026, 11, 13))
    assert not t.expiring(date(2026, 11, 12))
    assert t.expiring(date(2026, 11, 25))                  # expired counts too
    assert "⚠ expired" in t.title(date(2026, 11, 25))
    assert "expires Nov 20, 2026" in t.title(date(2026, 10, 1))
    assert not credentials.SavedToken("y", "https://s.test").expiring()


def test_legacy_token_moves_into_the_list(memory_keyring):
    credentials.set_token("https://school.test", "legacy-9999")
    moved = credentials.migrate_legacy("https://school.test")
    assert moved.label == "Saved token" and credentials.get_saved(moved.id) == "legacy-9999"
    assert credentials.get_token("https://school.test", env={}) == (None, None)
    assert credentials.migrate_legacy("https://school.test") is None


def test_saving_needs_a_store(monkeypatch):
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    assert credentials.list_saved() == []
    with pytest.raises(MissingDependency):
        credentials.save_token("https://school.test", "abc")
