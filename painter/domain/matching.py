"""Every rule for recognising a student or a section, in one place.

Three name rules, each for a different kind of input:

  name_contains   --section / --student specs: a case-insensitive substring,
                  tried only after exact IDs and exact names (match_tier)
  letters_key     folder and file names ("doejane_501", "Doe-Jane"): letters
                  only, so punctuation and spacing don't matter
  same_words      names typed in grade files or shown by New Quizzes: every
                  word of the name appears in the Canvas name, in any order

and one ID rule: a value equals the Canvas user ID, SIS user ID or login.
StudentMatcher applies them to a roster's users.
"""
from __future__ import annotations

import re


# ---- name rules ------------------------------------------------------------------
def letters_key(text: str | None) -> str:
    """Lower-case letters only, for comparing names written different ways."""
    return "".join(ch for ch in (text or "").casefold() if ch.isalpha())


def name_words(text: str | None) -> set[str]:
    return set(re.findall(r"\w+", (text or "").casefold()))


def same_words(name: str, user: dict) -> bool:
    """Every word of `name` appears in the student's Canvas name.

    Word-based, so "Jane Doe", "Doe, Jane" and "Doe Jane" all match, and a
    name without the middle name still matches one that has it.
    """
    want = name_words(name)
    if not want:
        return False
    have = set().union(*(name_words(user.get(k))
                         for k in ("name", "sortable_name", "short_name")))
    return want <= have


def name_contains(spec: str, name: str | None) -> bool:
    return bool(name) and spec.strip().casefold() in name.casefold()


# Old names, still imported by the old script and tests.
_letters, _name_tokens, name_matches = letters_key, name_words, same_words


# ---- specs: exact ID, then exact name, then partial name --------------------------
# Spec matching runs in tiers and stops at the first tier with any hit, so an
# exact ID never also pulls in sections whose names merely contain it, and
# "A1" picks section "A1" over "A1-8" and "A10-3" (review finding 10).
EXACT_ID, EXACT_NAME, PARTIAL_NAME = 0, 1, 2


def match_tier(spec: str, ids, names) -> int | None:
    """How well spec identifies something with these ids and names, or None."""
    spec = spec.strip()
    if not spec:
        return None
    if spec in {str(i) for i in ids if i not in (None, "")}:
        return EXACT_ID
    folded = spec.casefold()
    names = [n for n in names if n]
    if any(folded == n.casefold() for n in names):
        return EXACT_NAME
    if any(name_contains(spec, n) for n in names):
        return PARTIAL_NAME
    return None


def best_matches(spec: str, items, ids_of, names_of) -> list:
    """The items in the best tier that spec reaches (empty if none)."""
    tiers = {}
    for item in items:
        t = match_tier(spec, ids_of(item), names_of(item))
        if t is not None:
            tiers.setdefault(t, []).append(item)
    return tiers[min(tiers)] if tiers else []


def section_ids(s: dict):
    return (s.get("id"), s.get("sis_section_id"))


def section_names(s: dict):
    return (s.get("name"),)


def student_ids(u: dict):
    """The values a student can be identified by: Canvas ID, SIS ID, login."""
    return (u.get("id"), u.get("sis_user_id"), u.get("login_id"))


def student_names(u: dict):
    return (u.get("name"), u.get("sortable_name"))


def match_section(spec: str, section: dict) -> bool:
    """Does one --section spec identify this section (any tier)?"""
    return match_tier(spec, section_ids(section), section_names(section)) is not None


def match_student(spec: str, user: dict) -> bool:
    """Does one --student spec identify this roster entry (any tier)?"""
    return match_tier(spec, student_ids(user), student_names(user)) is not None


# ---- students --------------------------------------------------------------------
class StudentMatcher:
    """The roster's users, found by ID, spec, or name."""

    def __init__(self, users):
        self.users = list(users)

    def by_id(self, value: str) -> list[dict]:
        """Users whose Canvas ID, SIS ID or login is exactly value."""
        value = (value or "").strip()
        if not value:
            return []
        return [u for u in self.users
                if value in {str(i) for i in student_ids(u) if i not in (None, "")}]

    def by_spec(self, spec: str) -> list[dict]:
        """--student: the best tier of exact ID, exact name, partial name."""
        return best_matches(spec, self.users, student_ids, student_names)

    def by_words(self, name: str) -> list[dict]:
        """Grade files, New Quiz pages: every word of name in the Canvas name."""
        return [u for u in self.users if same_words(name, u)]

    def value_lookups(self) -> list[tuple[str, dict, object]]:
        """For recognising a column of a report: (what, value -> user id,
        normaliser) for Canvas ID, SIS ID, login, and names unique by
        letters_key, in that order of preference."""
        by_name: dict[str, set[int]] = {}
        for u in self.users:
            for n in student_names(u):
                if letters_key(n):
                    by_name.setdefault(letters_key(n), set()).add(u["id"])
        return [
            ("Canvas user ID", {str(u["id"]): u["id"] for u in self.users}, str.strip),
            ("SIS user ID", {str(u["sis_user_id"]): u["id"] for u in self.users
                             if u.get("sis_user_id")}, str.strip),
            ("login", {str(u["login_id"]).casefold(): u["id"] for u in self.users
                       if u.get("login_id")}, lambda v: v.strip().casefold()),
            ("name", {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1},
             letters_key),
        ]
