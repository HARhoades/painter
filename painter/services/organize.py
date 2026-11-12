"""Sorting downloaded submissions into section folders (offline)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import shutil

from painter.domain.matching import best_matches, letters_key
from painter.domain.naming import slug
from painter.domain.roster import catch_all_sections
from painter.errors import Cancelled, InvalidInput
from painter.events import NULL, ItemDone, Reporter, Stage
from painter.storage.tabular import read_records, write_csv


def read_roster_csv(path: Path) -> list[dict]:
    """Rows of a --roster-csv file (header names, not positions, are used)."""
    try:
        _, rows = read_records(path)
    except OSError as exc:
        raise InvalidInput(f"Can't read roster {path}: {exc}")
    need = {"Student Canvas ID", "Section Name"}
    missing = need - set(rows[0].keys() if rows else need)
    if not rows or missing:
        raise InvalidInput(f"{path} doesn't look like a --roster-csv file"
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
            if any(not (s or "").strip() for s in section_specs):
                raise InvalidInput("--section needs a value; an empty one would "
                                 "match everything.")
            for spec in section_specs:
                hits = set(best_matches(spec, self.sections,
                                        lambda n: (self.sections[n],), lambda n: (n,)))
                if not hits:
                    raise InvalidInput(f"--section {spec!r} matches no section in the roster")
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
            for key in {letters_key(last + first), letters_key(first + last), letters_key(full)}:
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
        key = letters_key(re.split(r"_\d", stem, maxsplit=1)[0])
        uids = self.by_name.get(key, set())
        if len(uids) == 1:
            return next(iter(uids)), "name"
        if len(uids) > 1:
            return None, "name matches several students"
        return None, "no roster match"


@dataclass
class OrganizeRequest:
    src: Path                              # folder to sort (a run or assignment folder)
    roster_csv: Path                       # from --roster-csv
    section_specs: tuple[str, ...] = ()    # only these sections
    dest: Path | None = None               # copy into this tree instead of moving


@dataclass
class OrganizeItem:
    """One file or folder found while planning, matched to the roster or not."""
    path: Path
    label: str                             # path shown to the user, relative to src
    how: str                               # "id" / "name", or why it did not match
    uid: str | None = None
    student: str = ""
    section: str = ""
    target: Path | None = None             # where it goes (None: left in place)
    exists: bool = False                   # target already there: skipped
    note: str = ""                         # " [in A, B; used A]" for several sections


@dataclass
class OrganizePlan:
    """What an organize run would do. Nothing on disk has changed yet."""
    src_root: Path
    dest_root: Path
    copying: bool
    section_dirs: dict[str, str]           # section name -> folder name
    make_dirs: list[Path]                  # section folders to create
    items: list[OrganizeItem]              # in the order they were found
    counts: dict[str, int]                 # section -> items it receives
    ambiguous: int                         # students in more than one section

    @property
    def verb(self) -> str:
        return "copy" if self.copying else "move"

    @property
    def unmatched(self) -> list[OrganizeItem]:
        return [i for i in self.items if i.uid is None]


@dataclass
class OrganizeResult:
    done: int
    skipped: int
    log_path: Path


LOG_COLUMNS = ["Item", "Student", "Student Canvas ID", "Section", "Destination",
               "Matched By", "Result"]


def plan_organize(req: OrganizeRequest) -> OrganizePlan:
    """Work out where every student folder or file goes. Reads only."""
    src_root = Path(req.src)
    if not src_root.is_dir():
        raise InvalidInput(f"--organize: {src_root} is not a folder")
    index = RosterIndex(read_roster_csv(Path(req.roster_csv)),
                        list(req.section_specs) or None)
    if not index.sections:
        raise InvalidInput("The roster has no section names to organize by.")
    dest_root = Path(req.dest) if req.dest else src_root
    copying = dest_root.resolve() != src_root.resolve()
    if copying and dest_root.resolve().is_relative_to(src_root.resolve()):
        raise InvalidInput("--organize-to can't be inside the folder being organized")

    # A section that holds every student (a course-wide default) never
    # receives anyone, so it doesn't get a folder.
    section_dirs = {sec: slug(sec, 40) for sec in index.sections
                    if sec not in index.catch_all}
    reserved = {slug(sec, 40) for sec in index.sections}
    plan = OrganizePlan(src_root, dest_root, copying, section_dirs, [], [], {},
                        len(index.ambiguous_section))

    def is_assignment_dir(d: Path) -> bool:
        """A folder of student folders (e.g. DATE-Scenario_7001 from --out)."""
        if index.match(d.name)[0]:
            return False
        try:
            return any(index.match(c.name)[0] for c in d.iterdir()
                       if not c.name.startswith("."))
        except OSError:
            return False

    def walk(src: Path, dest: Path, label: str) -> None:
        items = sorted(src.iterdir(), key=lambda x: x.name.casefold())
        # Section folders go where students are: here, unless this is a run
        # folder that only holds assignment folders.
        holds_students = any(index.match(i.name)[0] for i in items) or not any(
            i.is_dir() and i.name not in reserved and is_assignment_dir(i)
            for i in items)
        if holds_students:
            plan.make_dirs += [dest / d for d in section_dirs.values()]
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
                    walk(item, dest / item.name, f"{label}{item.name}/")
                    continue
                plan.items.append(OrganizeItem(item, f"{label}{item.name}", how))
                continue
            sec = index.section_of[uid]
            target = dest / section_dirs[sec] / item.name
            entry = OrganizeItem(
                item, f"{label}{item.name}", how, uid,
                index.students[uid].get("Student Full Name", ""), sec, target,
                exists=target.exists())
            if uid in index.ambiguous_section:
                entry.note = (" [in " + ", ".join(index.ambiguous_section[uid])
                              + f"; used {sec}]")
            if not entry.exists:
                plan.counts[sec] = plan.counts.get(sec, 0) + 1
            plan.items.append(entry)

    walk(src_root, dest_root, "")
    return plan


def execute_organize(plan: OrganizePlan, reporter: Reporter = NULL) -> OrganizeResult:
    """Carry out a plan: create section folders, move or copy, write the log."""
    for d in plan.make_dirs:
        d.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    done = skipped = 0
    stopped = False
    matched = [i for i in plan.items if i.uid is not None]
    reporter.event(Stage(f"{plan.verb.capitalize()} into section folders", total=len(matched)))
    for n, it in enumerate(plan.items, start=1):
        if it.uid is None:
            rows.append({"Item": it.label, "Student": "", "Student Canvas ID": "",
                         "Section": "", "Destination": "", "Matched By": "",
                         "Result": f"left in place: {it.how}"})
            continue
        if reporter.cancelled():
            stopped = True        # still write the log of what was moved
            break
        reporter.progress(done + skipped + 1, len(matched), it.label)
        if it.exists or it.target.exists():
            result = "skipped: already exists in the section folder"
            skipped += 1
        else:
            if plan.copying:
                it.target.parent.mkdir(parents=True, exist_ok=True)
                if it.path.is_dir():
                    shutil.copytree(it.path, it.target)
                else:
                    shutil.copy2(it.path, it.target)
            else:
                it.path.rename(it.target)
            result = f"{plan.verb}d"
            done += 1
        rows.append({"Item": it.label, "Student": it.student,
                     "Student Canvas ID": it.uid, "Section": it.section,
                     "Destination": str(it.target), "Matched By": it.how,
                     "Result": result + it.note})
        reporter.event(ItemDone("folder", it.label, result, it.note.strip(), it.target))

    log = write_csv(plan.dest_root / f"organize_log_{datetime.now():%Y%m%d_%H%M%S}.csv",
                    LOG_COLUMNS, rows)
    reporter.info(f"\nLog: {log}")
    result = OrganizeResult(done, skipped, log)
    if stopped:
        raise Cancelled(f"stopped after {done} item(s); log written", result)
    return result
