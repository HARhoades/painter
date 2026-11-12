"""Settings shared by every front end."""
from __future__ import annotations

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


def default_browser_profile(env=None, platform: str | None = None) -> Path:
    """Where the signed-in browser profile for `painter quiz uploads` lives."""
    return app_data_dir(env, platform) / "browser-profile"
