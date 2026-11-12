"""Comparing student names written different ways."""
from __future__ import annotations

import re


# --------------------------------------------------------------------------
# Sorting downloaded submissions into section folders
# --------------------------------------------------------------------------
def _letters(text: str) -> str:
    """Lower-case letters only, for comparing names written different ways."""
    return "".join(ch for ch in (text or "").casefold() if ch.isalpha())


def _name_tokens(text: str | None) -> set[str]:
    return set(re.findall(r"\w+", (text or "").casefold()))


def name_matches(name: str, user: dict) -> bool:
    """Every word of `name` appears in the student's Canvas name.

    Word-based, so "Jane Doe", "Doe, Jane" and "Doe Jane" all match, and a
    name without the middle name still matches one that has it.
    """
    want = _name_tokens(name)
    if not want:
        return False
    have = set().union(*(_name_tokens(user.get(k))
                         for k in ("name", "sortable_name", "short_name")))
    return want <= have
