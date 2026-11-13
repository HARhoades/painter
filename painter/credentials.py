"""Where Canvas tokens live for the window (and any front end that wants them).

Tokens are kept in the operating system's credential store (Windows
Credential Manager) through `keyring`, never in a file. Several tokens can be
saved; each has an id, an optional name and an optional expiration date. The
list of saved tokens (names, dates, last four characters; never the tokens
themselves) is kept in the credential store too, under one index entry.

CANVAS_API_TOKEN is offered as one more choice in the window; it no longer
locks the token field.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
import os
from urllib.parse import urlsplit
import uuid

from painter.config import TOKEN_ENV
from painter.errors import MissingDependency

SERVICE = "painter"
INDEX = "saved-index"          # account holding the list of saved tokens (no secrets)
WARN_DAYS = 7                  # warn when a token expires within this many days


def _keyring():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _account(base_url: str) -> str:
    """The old one-token-per-host account name (read once, then migrated)."""
    return (urlsplit(base_url).hostname or base_url).lower()


def _secret_account(token_id: str) -> str:
    return f"token:{token_id}"


def keyring_available() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        from keyring.backends.fail import Keyring as FailKeyring
    except ImportError:                       # pragma: no cover - old keyring
        return True
    return not isinstance(kr.get_keyring(), FailKeyring)


def _need_store():
    if not keyring_available():
        raise MissingDependency(
            "No credential store is available, so the token can't be remembered. "
            f"Set the {TOKEN_ENV} environment variable instead.")
    return _keyring()


# ---- saved tokens --------------------------------------------------------

@dataclass
class SavedToken:
    id: str
    base_url: str
    label: str = ""
    expires: str = ""          # YYYY-MM-DD, or "" for no expiration date
    hint: str = ""             # last four characters, to tell tokens apart

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or self.base_url

    def expiry(self) -> date | None:
        try:
            return date.fromisoformat(self.expires) if self.expires else None
        except ValueError:
            return None

    def days_left(self, today: date | None = None) -> int | None:
        end = self.expiry()
        return None if end is None else (end - (today or date.today())).days

    def expiring(self, today: date | None = None) -> bool:
        """True when expired or within WARN_DAYS of its expiration date."""
        left = self.days_left(today)
        return left is not None and left <= WARN_DAYS

    def title(self, today: date | None = None) -> str:
        """How the token reads in the drop-down."""
        name = self.label or self.host
        text = f"{name} · …{self.hint}" if self.hint else name
        left = self.days_left(today)
        if left is None:
            return text
        end = self.expiry()
        when = f"{end:%b} {end.day}, {end.year}"
        if left < 0:
            return f"{text} · ⚠ expired {when}"
        if left <= WARN_DAYS:
            return f"{text} · ⚠ expires {when}"
        return f"{text} · expires {when}"


def _read_index(kr) -> list[SavedToken]:
    try:
        raw = kr.get_password(SERVICE, INDEX)
        data = json.loads(raw) if raw else []
    except Exception:                         # a locked store or a damaged index: nothing
        return []
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            out.append(SavedToken(**{k: str(d.get(k) or "") for k in
                                     ("id", "base_url", "label", "expires", "hint")}))
        except (AttributeError, TypeError):
            continue
    return [t for t in out if t.id]


def _write_index(kr, tokens: list[SavedToken]) -> None:
    kr.set_password(SERVICE, INDEX, json.dumps([asdict(t) for t in tokens]))


def list_saved() -> list[SavedToken]:
    kr = _keyring()
    return [] if kr is None else _read_index(kr)


def get_saved(token_id: str) -> str | None:
    kr = _keyring()
    if kr is None or not token_id:
        return None
    try:
        return kr.get_password(SERVICE, _secret_account(token_id)) or None
    except Exception:
        return None


def save_token(base_url: str, token: str, label: str = "", expires: str = "",
               token_id: str | None = None) -> SavedToken:
    """Save (or update) a token. The same token for the same host is saved once."""
    kr = _need_store()
    tokens = _read_index(kr)
    host = _account(base_url)
    if token_id is None or not any(t.id == token_id for t in tokens):
        token_id = next((t.id for t in tokens
                         if _account(t.base_url) == host and get_saved(t.id) == token),
                        None) or uuid.uuid4().hex[:12]
    entry = SavedToken(token_id, base_url.rstrip("/"), label.strip(), expires, token[-4:])
    kr.set_password(SERVICE, _secret_account(token_id), token)
    tokens = [entry if t.id == token_id else t for t in tokens]
    if not any(t.id == token_id for t in tokens):
        tokens.append(entry)
    _write_index(kr, tokens)
    return entry


def remove_saved(token_id: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, _secret_account(token_id))
    except Exception:                         # already gone: fine
        pass
    tokens = _read_index(kr)
    if any(t.id == token_id for t in tokens):
        _write_index(kr, [t for t in tokens if t.id != token_id])


def migrate_legacy(base_url: str) -> SavedToken | None:
    """Move a token saved by an earlier version (one per host) into the list."""
    token, where = get_token(base_url, env={})
    if where != "keyring" or not keyring_available():
        return None
    saved = save_token(base_url, token, label="Saved token")
    clear_token(base_url)
    return saved


def env_token(env=None) -> str | None:
    env = os.environ if env is None else env
    return env.get(TOKEN_ENV) or None


# ---- the earlier one-token-per-host store (kept for migration) ------------

def get_token(base_url: str, env=None) -> tuple[str | None, str | None]:
    """(token, where): where is "env", "keyring" or None when there is none."""
    env = os.environ if env is None else env
    if env.get(TOKEN_ENV):
        return env[TOKEN_ENV], "env"
    kr = _keyring()
    if kr is None or not base_url:
        return None, None
    try:
        token = kr.get_password(SERVICE, _account(base_url))
    except Exception:                         # a locked or broken store: no token
        return None, None
    return (token, "keyring") if token else (None, None)


def set_token(base_url: str, token: str) -> None:
    _need_store().set_password(SERVICE, _account(base_url), token)


def clear_token(base_url: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, _account(base_url))
    except Exception:                         # nothing stored: already clear
        pass
