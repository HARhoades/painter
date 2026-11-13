"""Settings shared by every front end."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
import os
from pathlib import Path
import sys


TOKEN_ENV = "CANVAS_API_TOKEN"


LEGACY_BROWSER_PROFILE = "canvas-browser-profile"   # old default, relative to cwd


def app_data_dir(env=None, platform: str | None = None) -> Path:
    """Per-user local (not roaming, not synced) folder for Painter's own data.

    The tool itself lives under OneDrive on some machines, so anything that
    holds a signed-in session must not default to a folder next to it
    (review finding 8).
    """
    env = os.environ if env is None else env
    platform = platform or sys.platform
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    if platform.startswith("win"):
        base = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") \
            else home / "AppData" / "Local"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env["XDG_STATE_HOME"]) if env.get("XDG_STATE_HOME") \
            else home / ".local" / "state"
    return base / "painter"


# Folders (relative to the checkout) that .gitignore keeps out of git. Student
# work and local caches live only in these; tests keep this list and
# .gitignore in step.
IGNORED_DIRS = ("submissions", ".painter-cache")


def project_root() -> Path | None:
    """The source checkout Painter runs from (where .gitignore lives), or None
    when it is installed somewhere else."""
    root = Path(__file__).resolve().parent.parent
    return root if (root / "pyproject.toml").exists() and (root / ".gitignore").exists() else None


def default_download_root() -> Path:
    """Where downloads go unless the user picks a folder: inside the checkout's
    ignored submissions/ folder, so student work can't be committed by accident."""
    root = project_root()
    return root / IGNORED_DIRS[0] if root else Path.home() / "Documents" / "Painter"


def cache_root() -> Path:
    """Where the local cache lives: the checkout's ignored .painter-cache/, or a
    cache folder in the per-user app data when Painter is installed elsewhere."""
    root = project_root()
    return root / IGNORED_DIRS[1] if root else app_data_dir() / "cache"


def exposed_in_repo(path) -> bool:
    """True when `path` is inside the checkout but outside every ignored folder,
    so files saved there could be committed."""
    root = project_root()
    if root is None or not str(path).strip():
        return False
    try:
        rel = Path(path).expanduser().resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return not rel.parts or rel.parts[0] not in IGNORED_DIRS


def default_browser_profile(env=None, platform: str | None = None) -> Path:
    """Where the signed-in browser profile for `painter quiz uploads` lives."""
    return app_data_dir(env, platform) / "browser-profile"


# ---- settings for the window ---------------------------------------------

SETTINGS_FILE = "settings.json"


@dataclass
class Settings:
    """What the window remembers between runs. Never holds the token."""
    base_url: str = ""
    course_id: int | None = None
    download_folder: str = ""
    grades_folder: str = ""
    credential_id: str = ""                         # saved-token id last used, or "env"
    options: dict = field(default_factory=dict)     # download option defaults
    extra: dict = field(default_factory=dict)       # keys this version doesn't know


def settings_path(env=None, platform: str | None = None) -> Path:
    return app_data_dir(env, platform) / SETTINGS_FILE


def load_settings(path: Path | None = None) -> Settings:
    """Missing or unreadable file: defaults. Unknown keys are kept in .extra."""
    path = Path(path) if path else settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    known = {f.name for f in fields(Settings)} - {"extra"}
    s = Settings(**{k: v for k, v in data.items() if k in known})
    s.extra = {k: v for k, v in data.items() if k not in known}
    return s


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    path = Path(path) if path else settings_path()
    data = {k: v for k, v in asdict(settings).items() if k != "extra"}
    data = {**settings.extra, **data}
    if "token" in data:                              # belt and braces
        raise ValueError("the token is never written to settings")
    from painter.storage.atomic import atomic_write
    with atomic_write(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path
