"""Sorting downloaded submissions into section folders (offline)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import re
import shutil
import sys

from painter.domain.matching import _letters
from painter.domain.naming import slug
from painter.domain.roster import catch_all_sections


def read_roster_csv(path: Path) -> list[dict]:
    """Rows of a --roster-csv file (header names, not positions, are used)."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        raise SystemExit(f"Can't read roster {path}: {exc}")
    need = {"Student Canvas ID", "Section Name"}
    missing = need - set(rows[0].keys() if rows else need)
    if not rows or missing:
        raise SystemExit(f"{path} doesn't look like a --roster-csv file"
                         + (f" (missing {', '.join(sorted(missing))})" if missing else
                            " (no rows)"))
    return rows


class RosterIndex:
    """Lookups over a roster CSV for matching folder names to students."""

    def __init__(self, rows: list[dict], section_specs: list[str] | None):
        self.sections: dict[str, str] = {}          # section name -> section id
        by_student: dict[str, list[str]] = {}       # canvas id -> section names
        self.students: dict[str, dict] = {}
        for r in rows:
            uid = (r.get("Student Canvas ID") or "").strip()
            sec = (r.get("Section Name") or "").strip()
            if not uid:
                continue
            self.students.setdefault(uid, r)
            if sec:
                self.sections.setdefault(sec, (r.get("Section Canvas ID") or "").strip())
                if sec not in by_student.setdefault(uid, []):
                    by_student[uid].append(sec)

        self.filtered_out: set[str] = set()
        if section_specs:
            keep = set()
            for spec in section_specs:
                hits = {n for n, sid in self.sections.items()
                        if spec == sid or spec.casefold() in n.casefold()}
                if not hits:
                    raise SystemExit(f"--section {spec!r} matches no section in the roster")
                keep |= hits
            self.sections = {n: i for n, i in self.sections.items() if n in keep}
            by_student = {u: [s for s in secs if s in keep]
                          for u, secs in by_student.items()}
            by_student = {u: secs for u, secs in by_student.items() if secs}
            self.filtered_out = set(self.students) - set(by_student)
            self.students = {u: r for u, r in self.students.items() if u in by_student}

        # A course-wide default section loses ties (same rule as downloads).
        everyone = catch_all_sections(by_student)
        self.catch_all = everyone
        self.section_of: dict[str, str] = {}
        self.ambiguous_section: dict[str, list[str]] = {}
        for uid, secs in by_student.items():
            pick = [s for s in secs if s not in everyone] or secs
            self.section_of[uid] = pick[0]
            if len(pick) > 1:
                self.ambiguous_section[uid] = pick

        # Name keys: "lastfirst" (Canvas bulk-download style), "firstlast",
        # and the sortable form this script writes ("Last-First").
        self.by_name: dict[str, set[str]] = {}
        for uid, r in self.students.items():
            first = r.get("Student First Name", "")
            last = r.get("Student Last Name", "")
            full = r.get("Student Full Name", "")
            for key in {_letters(last + first), _letters(first + last), _letters(full)}:
                if key:
                    self.by_name.setdefault(key, set()).add(uid)

    def match(self, name: str) -> tuple[str | None, str]:
        """(canvas id, how) for a file or folder name, or (None, reason)."""
        # Folder "Doe-Jane_884321", --flat file "Doe-Jane_884321__essay.pdf".
        stem = name.split("__", 1)[0]
        # 1. This script's names end in _<id>.
        for cand in (stem, Path(stem).stem):
            m = re.search(r"_(\d+)$", cand)
            if m and m.group(1) in self.students:
                return m.group(1), "id"
        # 2. Any number in the name that is a roster ID (Canvas bulk
        #    downloads: "doejane_884321_5551234_essay.pdf"; "LATE_" prefixes).
        numbers = set(re.findall(r"\d+", name))
        if numbers & self.filtered_out and not numbers & set(self.students):
            return None, "student not in the selected --section"
        hits = {t for t in numbers if t in self.students}
        if len(hits) == 1:
            return hits.pop(), "id"
        if len(hits) > 1:
            return None, "several roster IDs in the name"
        # 3. The name alone, with the ID and any extras stripped.
        key = _letters(re.split(r"_\d", stem, maxsplit=1)[0])
        uids = self.by_name.get(key, set())
        if len(uids) == 1:
            return next(iter(uids)), "name"
        if len(uids) > 1:
            return None, "name matches several students"
        return None, "no roster match"


def organize_submissions(args) -> int:
    """--organize: move (or copy) student folders into one folder per section."""
    src_root = Path(args.organize)
    if not src_root.is_dir():
        raise SystemExit(f"--organize: {src_root} is not a folder")
    index = RosterIndex(read_roster_csv(Path(args.roster)), args.section)
    if not index.sections:
        raise SystemExit("The roster has no section names to organize by.")
    dest_root = Path(args.organize_to) if args.organize_to else src_root
    copying = dest_root.resolve() != src_root.resolve()
    if copying and dest_root.resolve().is_relative_to(src_root.resolve()):
        raise SystemExit("--organize-to can't be inside the folder being organized")

    # A section that holds every student (a course-wide default) never
    # receives anyone, so it doesn't get a folder.
    section_dirs = {sec: slug(sec, 40) for sec in index.sections
                    if sec not in index.catch_all}
    reserved = {slug(sec, 40) for sec in index.sections}
    dry = args.dry_run
    verb = "copy" if copying else "move"
    log_rows: list[dict] = []
    unmatched: list[str] = []
    counts: dict[str, int] = {}

    def is_assignment_dir(d: Path) -> bool:
        """A folder of student folders (e.g. 03_DATE-Scenario from --out)."""
        if index.match(d.name)[0]:
            return False
        try:
            return any(index.match(c.name)[0] for c in d.iterdir()
                       if not c.name.startswith("."))
        except OSError:
            return False

    def sort_folder(src: Path, dest: Path, label: str) -> None:
        items = sorted(src.iterdir(), key=lambda x: x.name.casefold())
        # Section folders go where students are: here, unless this is a run
        # folder that only holds assignment folders.
        holds_students = any(index.match(i.name)[0] for i in items) or not any(
            i.is_dir() and i.name not in reserved and is_assignment_dir(i)
            for i in items)
        if holds_students and not dry:
            for d in section_dirs.values():
                (dest / d).mkdir(parents=True, exist_ok=True)
        for item in items:
            if item.name.startswith(".") or item.name.startswith("organize_log_"):
                continue
            if item.is_dir() and item.name in reserved:
                continue                      # a section folder from an earlier run
            if item.suffix.lower() == ".xlsx" and item.name.startswith("submission_log_"):
                continue
            uid, how = index.match(item.name)
            if uid is None:
                if item.is_dir() and is_assignment_dir(item):
                    sort_folder(item, dest / item.name, f"{label}{item.name}/")
                    continue
                unmatched.append(f"{label}{item.name}  ({how})")
                log_rows.append({"Item": f"{label}{item.name}", "Student": "",
                                 "Student Canvas ID": "", "Section": "",
                                 "Destination": "", "Matched By": "",
                                 "Result": f"left in place: {how}"})
                continue
            row = index.students[uid]
            sec = index.section_of[uid]
            target = dest / section_dirs[sec] / item.name
            result = "dry run" if dry else f"{verb}d"
            if target.exists():
                result = "skipped: already exists in the section folder"
            elif not dry:
                if copying:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
                else:
                    item.rename(target)
            if not result.startswith("skipped"):
                counts[sec] = counts.get(sec, 0) + 1
            note = ""
            if uid in index.ambiguous_section:
                note = (" [in " + ", ".join(index.ambiguous_section[uid])
                        + f"; used {sec}]")
            print(f"  {label}{item.name} -> {target.relative_to(dest_root)}"
                  f"{'  (by name)' if how == 'name' else ''}{note}"
                  f"{'  SKIPPED, exists' if result.startswith('skipped') else ''}")
            log_rows.append({"Item": f"{label}{item.name}",
                             "Student": row.get("Student Full Name", ""),
                             "Student Canvas ID": uid, "Section": sec,
                             "Destination": str(target), "Matched By": how,
                             "Result": result + note})

    print(f"{'Dry run: ' if dry else ''}{verb.capitalize()} {src_root} -> "
          f"{dest_root} into {len(section_dirs)} section folder(s)")
    sort_folder(src_root, dest_root, "")

    print()
    for sec in sorted(section_dirs, key=str.casefold):
        print(f"  {section_dirs[sec]:<20} {counts.get(sec, 0):>4} item(s)")
    if unmatched:
        print(f"\n{len(unmatched)} item(s) not matched to the roster, left in place:",
              file=sys.stderr)
        for u in unmatched:
            print(f"  {u}", file=sys.stderr)
    if index.ambiguous_section:
        print(f"\nnote: {len(index.ambiguous_section)} student(s) are in more than "
              "one section; pass --section to choose", file=sys.stderr)

    if not dry:
        dest_root.mkdir(parents=True, exist_ok=True)
        log = dest_root / f"organize_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with open(log, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=["Item", "Student", "Student Canvas ID",
                                               "Section", "Destination",
                                               "Matched By", "Result"])
            w.writeheader()
            w.writerows(log_rows)
        print(f"\nLog: {log}")
    return 0
