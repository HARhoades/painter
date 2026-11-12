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


def attachment_filenames(attachments: list[dict]) -> list[str]:
    """Safe, distinct filenames for one submission's attachments, in order.

    Names that clash (case-insensitively, as on Windows) all get the
    attachment ID appended -- report__a123.pdf -- so neither overwrites the
    other and every rerun maps each attachment to the same file. Names that
    don't clash are left as they are (review finding 7).
    """
    names = [safe_filename(a.get("display_name") or a.get("filename", ""))
             for a in attachments]
    counts: dict[str, int] = {}
    for n in names:
        counts[n.casefold()] = counts.get(n.casefold(), 0) + 1
    out = []
    for att, name in zip(attachments, names):
        if counts[name.casefold()] > 1:
            stem, dot, ext = name.rpartition(".")
            if not stem:                       # no extension, or ".hidden"
                stem, dot, ext = name, "", ""
            name = f"{stem}__a{att.get('id', 'x')}{dot}{ext}"
        out.append(name)
    return out


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
