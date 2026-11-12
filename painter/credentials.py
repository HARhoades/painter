"""Where the Canvas token lives for the window (and any front end that wants it).

The token is kept in the operating system's credential store (Windows
Credential Manager) through `keyring`, never in a file. CANVAS_API_TOKEN
still wins when it is set, so the command line and the window agree.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from painter.config import TOKEN_ENV
from painter.errors import MissingDependency

SERVICE = "painter"


def _keyring():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _account(base_url: str) -> str:
    """One stored token per Canvas host."""
    return (urlsplit(base_url).hostname or base_url).lower()


def keyring_available() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        from keyring.backends.fail import Keyring as FailKeyring
    except ImportError:                       # pragma: no cover - old keyring
        return True
    return not isinstance(kr.get_keyring(), FailKeyring)


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
    if not keyring_available():
        raise MissingDependency(
            "No credential store is available, so the token can't be remembered. "
            f"Set the {TOKEN_ENV} environment variable instead.")
    _keyring().set_password(SERVICE, _account(base_url), token)


def clear_token(base_url: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, _account(base_url))
    except Exception:                         # nothing stored: already clear
        pass
