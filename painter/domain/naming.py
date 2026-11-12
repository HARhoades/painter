"""Names for files and folders on disk."""
from __future__ import annotations

import os
import re


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------
def slug(text: str, maxlen: int = 60) -> str:
    """Make a string safe for use as a single path component."""
    text = re.sub(r"[^\w\s.,-]", "", text or "").strip()
    text = re.sub(r"[\s,]+", "-", text)
    return text[:maxlen].strip("-.") or "unnamed"


def safe_filename(name: str) -> str:
    """Strip any directory components a client may have snuck into a filename."""
    name = os.path.basename(name.replace("\\", "/"))
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name or "file"


def student_dir_name(sub: dict) -> str:
    user = sub.get("user") or {}
    name = user.get("sortable_name") or user.get("name") or "Anonymous"
    return f"{slug(name, 45)}_{sub.get('user_id', 'unknown')}"


def flat_filename(sub: dict, fname: str) -> str:
    """Prefix a filename with the student so a shared folder never collides.

    Reuses student_dir_name(), so the prefix matches the folder name the
    default layout would have used, including the Canvas user ID that keeps
    two students with the same name apart.
    """
    return f"{student_dir_name(sub)}__{fname}"
