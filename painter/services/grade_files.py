"""Grade files: creating blank ones from the roster, and parsing filled-in ones."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from painter.canvas.client import Canvas
from painter.domain.naming import slug
from painter.domain.roster import Roster, resolve_sections, section_instructors
from painter.errors import Cancelled, InvalidInput
from painter.events import NULL, ItemDone, Reporter, Stage, emit, watches_canvas
from painter.domain.assignments import require_one


# --------------------------------------------------------------------------
# Generating grade files from the Canvas roster
# --------------------------------------------------------------------------
# AY27-1, AY 2027 Term 1, 2026-2027 Term 1 ... -> ("27", "1")
TERM_PATTERNS = [
    re.compile(r"\bAY\s*(?P<year>\d{2,4})\s*[-–/ ]\s*(?P<term>\d)\b", re.I),
    re.compile(r"\bAY\s*(?P<year>\d{2,4})\b.*?\b(?:term|semester|sem)\s*(?P<term>\d)\b", re.I),
    re.compile(r"\b\d{4}\s*[-–]\s*(?P<year>\d{4})\b.*?\b(?:term|semester|sem)\s*(?P<term>\d)\b", re.I),
]


def parse_term_name(name: str | None) -> tuple[str, str] | None:
    """Pull (AY, semester) out of a Canvas term name; None if it doesn't fit."""
    for pattern in TERM_PATTERNS:
        m = pattern.search(name or "")
        if m:
            return m.group("year")[-2:], m.group("term")
    return None


# Prefix styles: how much of the section name starts each file name. A prefix
# is always there, so two sections' files for one assignment never share a name.
PREFIX_STYLES = ("short", "full", "instructor")
BASE_MAX = 40          # characters of the assignment part of a file name


# A course-number-shaped word (AI105, CS301, MA153A): when a section name starts
# with one, it is the course, not the section.
COURSE_LIKE = re.compile(r"[A-Za-z]{2,}\d{3,}[A-Za-z]?")


def section_words(section_name: str, lead: str = "") -> list[str]:
    """The words that name the section itself.

    Canvas section names often carry the course code in front and the
    instructor behind: 'AI105    A1 8  - RHOADES, H' -> ['A1', '8']. The part
    after ' - ' is dropped, and so is a first word that is the course (`lead`,
    the word every section in the course starts with, or a course-number
    shape). 'A1-8' -> ['A1', '8'].
    """
    name = (section_name or "").strip()
    head = re.split(r"\s+[-–]\s+", name, maxsplit=1)[0]
    words = [w for w in re.split(r"[\s_–-]+", head) if w]
    if len(words) > 1 and ((lead and words[0].casefold() == lead.casefold())
                           or COURSE_LIKE.fullmatch(words[0])):
        words = words[1:]
    return words or [name or "section"]


def course_lead(section_names) -> str:
    """The first word every section name shares (the course code), or ""."""
    firsts = {(re.split(r"[\s_–-]+", (n or "").strip(), maxsplit=1) or [""])[0].casefold()
              for n in section_names if (n or "").strip()}
    names = [n for n in section_names if (n or "").strip()]
    if len(names) < 2 or len(firsts) != 1:
        return ""
    return re.split(r"[\s_–-]+", names[0].strip(), maxsplit=1)[0]


def section_prefix(section_name: str, style: str = "short", instructor: str = "",
                   lead: str = "") -> str:
    """File name prefix from a section name.

    short: 'AI105 A1 8 - RHOADES, H' -> 'A1';  full: -> 'A1-8';
    instructor: -> 'A1-Rhoades' (just 'A1' without one).
    """
    if style not in PREFIX_STYLES:
        raise InvalidInput(f"Unknown prefix style {style!r}: use one of "
                           f"{', '.join(PREFIX_STYLES)}.")
    words = section_words(section_name, lead)
    if style == "full":
        return slug("-".join(words), 30)
    short = slug(words[0], 20)
    if style == "instructor" and (instructor or "").strip():
        return f"{short}-{slug(instructor, 20)}"
    return short


def _longer_prefix(section_name: str, style: str, instructor: str, lead: str) -> str:
    """The prefix used when the chosen one is shared: the full section, plus the
    instructor for that style ('A1-8', 'A1-8-Rhoades')."""
    full = section_prefix(section_name, "full", lead=lead)
    if style == "instructor" and (instructor or "").strip():
        full = f"{full}-{slug(instructor, 20)}"
    return full


def base_name(text: str) -> str:
    """The assignment part of a file name: safe on disk and at most BASE_MAX long."""
    return slug(text, BASE_MAX)


def grade_file_name(prefix: str, base: str, ay: str | None = None,
                    term: str | None = None) -> str:
    """<prefix>-<base>[-<AY>-<semester>].txt, e.g. A1-DATE-Scenario-27-1.txt.
    The AY and semester are left out unless both are given."""
    stem = f"{prefix}-{base}"
    if ay and term:
        stem += f"-{ay}-{term}"
    return stem + ".txt"


@dataclass(frozen=True)
class Naming:
    """How one run names its files."""
    style: str = "short"
    ay: str | None = None            # both None: no AY or semester in the names
    term: str | None = None


def name_section_files(sections: list[tuple[int, str, str]], base: str, naming: Naming,
                       lead: str = "") -> tuple[dict[int, str], dict[int, str]]:
    """File name per section for one assignment, and a note per section whose
    name had to be longer.

    sections: (section id, section name, instructor). Names are compared
    without case, as on Windows. Every section in a group that would share a
    name gets the longer prefix (A1 5 and A1 8 become A1-5 and A1-8, so no one
    file is named differently from the rest); if even those are shared, the
    section id is added to each.
    """
    level = {sid: 0 for sid, _, _ in sections}

    def name_of(sid, sname, instructor):
        if level[sid] == 0:
            prefix = section_prefix(sname, naming.style, instructor, lead)
        else:
            prefix = _longer_prefix(sname, naming.style, instructor, lead)
            if level[sid] == 2 or (naming.style == "full" and level[sid] == 1):
                prefix = f"{prefix}-{sid}"
        return grade_file_name(prefix, base, naming.ay, naming.term)

    while True:
        names = {sid: name_of(sid, sname or str(sid), instr) for sid, sname, instr in sections}
        groups: dict[str, list[int]] = {}
        for sid, n in names.items():
            groups.setdefault(n.casefold(), []).append(sid)
        shared = [g for g in groups.values() if len(g) > 1 and any(level[s] < 2 for s in g)]
        if not shared:
            break
        for g in shared:
            for sid in g:
                level[sid] = min(level[sid] + 1, 2)
    by_id = {sid: sname or str(sid) for sid, sname, _ in sections}
    notes = {sid: f"note: {by_id[sid]} shares its short name with another chosen section; "
                  f"using {names[sid]}"
             for sid, lv in level.items() if lv}
    return names, notes


def render_grade_file(assignment: dict | None, label: str, section: dict,
                      instructor: str, students: list[dict]) -> str:
    """The grade file itself: an [ASSIGNMENT] and [SECTION] header, then one
    [STUDENT] block per student with name and Canvas id filled in."""
    # Without an assignment, title= is left blank to fill in, as documented;
    # the label only names the file (review finding 14).
    title = assignment.get("name", "") if assignment else ""
    out = ["[ASSIGNMENT]",
           f"title={title}",
           f"id={(assignment or {}).get('id', '')}",
           "",
           "[SECTION]",
           f"title={section.get('name', '')}",
           f"instructor={instructor}",
           f"id={section['id']}",
           ""]
    for user in students:
        out += ["[STUDENT]",
                f"name={user.get('sortable_name') or user.get('name') or ''}",
                f"id={user['id']}",          # Canvas user ID, not the SIS ID
                "grade=",
                "comments=",
                ""]
    return "\n".join(out).rstrip("\n") + "\n"


@dataclass
class GradeFilesRequest:
    course_id: int
    out_dir: Path
    section_specs: tuple[str, ...] = ()      # empty: every section
    assignment_ids: tuple[int, ...] = ()     # at most one; empty leaves title/id blank
    label: str | None = None                 # base name; default: the assignment name
    ay: str | None = None                    # default: from the course term name
    term: str | None = None
    force: bool = False                      # overwrite existing files
    prefix_style: str = "short"              # see PREFIX_STYLES
    include_term: bool = True                # add -<AY>-<semester> to the names


@dataclass
class GradeFilesResult:
    out_dir: Path
    written: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)       # existed, not overwritten


def _assignment_and_label(canvas: Canvas, req: GradeFilesRequest) -> tuple[dict | None, str]:
    """The assignment (optional: without it the header is left blank to fill
    in) and the base name for the files."""
    label = req.label
    assignment = require_one(canvas, req.course_id, req.assignment_ids,
                             "grade files are made for at most one assignment.",
                             optional=True)
    if assignment:
        label = label or assignment.get("name") or str(assignment["id"])
    if not label:
        raise InvalidInput("Without --assignment, pass --label NAME for "
                           "the filename, e.g. --label DATE.")
    return assignment, base_name(label)


def _academic_term(canvas: Canvas, course_id: int, ay: str | None, term: str | None,
                   reporter: Reporter) -> tuple[str, str]:
    """AY (two digits) and semester: as given, else from the course's term name."""
    if not (ay and term):
        term_name = ((canvas.course(course_id).get("term") or {}).get("name") or "")
        parsed = parse_term_name(term_name)
        if not parsed:
            raise InvalidInput(
                f"Could not read an academic year and semester from the course "
                f"term name {term_name!r}. Pass --ay and --term, e.g. --ay 27 --term 1, "
                f"or leave them out of the names with --no-term.")
        ay, term = ay or parsed[0], term or parsed[1]
        reporter.info(f"Term {term_name!r} -> AY{ay}, semester {term}")
    return ay[-2:], term


def _naming(canvas: Canvas, course_id: int, style: str, include_term: bool,
            ay: str | None, term: str | None, reporter: Reporter) -> Naming:
    section_prefix("", style)                 # an unknown style fails before any work
    if not include_term:
        return Naming(style)
    return Naming(style, *_academic_term(canvas, course_id, ay, term, reporter))


@watches_canvas()
def make_grade_files(canvas: Canvas, req: GradeFilesRequest,
                     reporter: Reporter = NULL) -> GradeFilesResult:
    """Write one blank grade file per section."""
    roster = Roster.load(canvas, req.course_id)

    if req.section_specs:
        section_ids, notes = resolve_sections(roster, list(req.section_specs))
        emit(notes, reporter)
    else:
        section_ids = {s["id"] for s in roster.sections}
        reporter.info("No --section given: writing a file for every section in the course.")

    assignment, label = _assignment_and_label(canvas, req)
    naming = _naming(canvas, req.course_id, req.prefix_style, req.include_term,
                     req.ay, req.term, reporter)
    instructors = section_instructors(canvas, req.course_id)
    out_dir = Path(req.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = GradeFilesResult(out_dir)
    _write_section_files(_Batch(roster, instructors, naming, out_dir, req.force,
                                reporter, result), section_ids, assignment, label)
    reporter.info(f"\n{len(result.written)} file(s) written to {out_dir}")
    return result


@dataclass
class _Batch:
    """What every file in one run shares."""
    roster: Roster
    instructors: dict
    naming: Naming
    out_dir: Path
    force: bool
    reporter: Reporter
    result: GradeFilesResult


def students_of(roster: Roster, sid: int) -> list[dict]:
    """A section's students, sorted by name."""
    return sorted((roster.users[u] for u in roster.users_of_section.get(sid, set())),
                  key=lambda u: u.get("sortable_name") or u.get("name") or "")


def planned_names(roster: Roster, instructors: dict, section_ids, base: str,
                  naming: Naming) -> tuple[dict[int, str], dict[int, str]]:
    """File name per section that has students, for one assignment (what the
    run will write, and what the window previews)."""
    instructors = {int(k): v for k, v in (instructors or {}).items()}
    sections = [(sid, roster.section_by_id[sid].get("name") or str(sid),
                 (instructors.get(sid) or [""])[0])
                for sid in section_ids if roster.users_of_section.get(sid)]
    lead = course_lead([s.get("name") for s in roster.sections
                        if s["id"] not in roster.catch_all])
    return name_section_files(sections, base, naming, lead)


def _write_section_files(b: _Batch, section_ids, assignment: dict | None,
                         label: str) -> None:
    """One file per section with students, for one assignment."""
    roster, reporter = b.roster, b.reporter
    # Teachers first, TAs only where a section has no teacher: the same rule
    # as the roster CSV (review finding 6).
    names, notes = planned_names(roster, b.instructors, section_ids, label, b.naming)
    for sid in sorted(section_ids,
                      key=lambda i: roster.section_by_id[i].get("name") or ""):
        section = roster.section_by_id[sid]
        section_name = section.get("name") or str(sid)
        students = students_of(roster, sid)
        if not students:
            reporter.info(f"  {section_name}: no students, skipped")
            continue
        teachers = b.instructors.get(sid, [])
        if len(teachers) > 1:
            reporter.info(f"  note: {section_name} has several instructors "
                          f"({', '.join(teachers)}); using {teachers[0]}")
        if sid in notes:
            reporter.info(f"  {notes[sid]}")
        path = b.out_dir / names[sid]
        if path.exists() and not b.force:
            reporter.info(f"  ! {path} exists; not overwritten (use --force)")
            b.result.kept.append(path)
            reporter.event(ItemDone("file", path.name, "kept", section_name, path))
            continue
        path.write_text(
            render_grade_file(assignment, label, section,
                              teachers[0] if teachers else "", students),
            encoding="utf-8")
        reporter.info(f"  {path}  ({len(students)} students)")
        b.result.written.append(path)
        reporter.event(ItemDone("file", path.name, "written", section_name, path))


def batch_labels(assignments: list[dict], chosen: dict | None = None) -> dict[int, str]:
    """A base name per assignment: the one chosen for it, else its name. Two
    assignments never share one (compared without case): the later gets its id."""
    chosen = chosen or {}
    out: dict[int, str] = {}
    seen: set[str] = set()
    for a in assignments:
        label = base_name((chosen.get(a["id"]) or "").strip() or a.get("name")
                          or str(a["id"]))
        if label.casefold() in seen:
            label = f"{label}-{a['id']}"
        seen.add(label.casefold())
        out[a["id"]] = label
    return out


@dataclass
class GradeFilesBatch:
    """Blank files for several assignments and sections at once (the window)."""
    course_id: int
    out_dir: Path
    assignment_ids: tuple[int, ...]
    section_ids: tuple[int, ...]
    force: bool = False
    ay: str | None = None                    # default: from the course term name
    term: str | None = None
    prefix_style: str = "short"              # see PREFIX_STYLES
    include_term: bool = True
    bases: dict = field(default_factory=dict)   # assignment id -> base name typed in


@watches_canvas()
def make_grade_files_for(canvas: Canvas, req: GradeFilesBatch,
                         reporter: Reporter = NULL) -> GradeFilesResult:
    """One blank file per chosen section for each chosen assignment; the roster,
    instructors and term are read once."""
    if not req.assignment_ids:
        raise InvalidInput("Pick at least one assignment.")
    if not req.section_ids:
        raise InvalidInput("Pick at least one section.")
    roster = Roster.load(canvas, req.course_id)
    unknown = [s for s in req.section_ids if s not in roster.section_by_id]
    if unknown:
        raise InvalidInput(f"Section {unknown[0]} is no longer in this course.")
    by_id = {a["id"]: a for a in canvas.assignments(req.course_id)}
    missing = [a for a in req.assignment_ids if a not in by_id]
    if missing:
        raise InvalidInput(f"Assignment {missing[0]} is no longer in this course.")
    chosen = [by_id[a] for a in req.assignment_ids]
    naming = _naming(canvas, req.course_id, req.prefix_style, req.include_term,
                     req.ay, req.term, reporter)
    out_dir = Path(req.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = GradeFilesResult(out_dir)
    b = _Batch(roster, section_instructors(canvas, req.course_id), naming, out_dir,
               req.force, reporter, result)
    labels = batch_labels(chosen, req.bases)
    for i, a in enumerate(chosen, 1):
        if reporter.cancelled():
            raise Cancelled(f"stopped after {len(result.written)} file(s)", result)
        reporter.event(Stage(a.get("name") or str(a["id"]), len(req.section_ids), i, len(chosen)))
        reporter.info(f"{a.get('name')}:")
        _write_section_files(b, req.section_ids, a, labels[a["id"]])
    reporter.info(f"\n{len(result.written)} file(s) written to {out_dir}")
    return result


# --------------------------------------------------------------------------
# Posting grades and comments
# --------------------------------------------------------------------------
GRADE_FILE_KEYS = {
    "ASSIGNMENT": ("title", "id"),
    "SECTION": ("title", "instructor", "id"),
    "STUDENT": ("name", "id", "grade", "comments"),
}


class GradeFileError(Exception):
    def __init__(self, path: Path, line: int | None, message: str):
        where = f"{path.name}:{line}" if line else path.name
        super().__init__(f"{where}: {message}")


@dataclass
class GradeEntry:
    line: int
    name: str
    id: str
    grade: str
    comments: str

    @property
    def key(self) -> str:
        """Which student this is within one file: the Canvas id, else the name."""
        return f"id:{self.id}" if self.id else f"name:{self.name.casefold()}"

    @property
    def blank(self) -> bool:
        return not (self.grade or self.comments)


@dataclass
class GradeFile:
    path: Path
    assignment_id: int
    assignment_title: str
    section_id: int | None
    section_title: str
    instructor: str
    entries: list[GradeEntry]
    blank_entries: int = 0     # named students with no grade and no comment
    students: list[GradeEntry] = field(default_factory=list)   # every named student,
                                                               # filled in or not


def parse_grade_file(path: Path) -> GradeFile:
    """Read a grade file of [ASSIGNMENT], [SECTION] and [STUDENT] blocks.

    A line that does not start with a key known to its block continues the
    previous comments= value, so comments can span lines. Anything else
    unexpected is an error, reported with its line number.
    """
    return grade_file_from_blocks(path, _read_blocks(path))


def grade_file_from_blocks(path: Path, blocks: list[dict]) -> GradeFile:
    assigns = [b for b in blocks if b["_kind"] == "ASSIGNMENT"]
    if len(assigns) != 1:
        raise GradeFileError(path, None, f"expected one [ASSIGNMENT] block, found {len(assigns)}")
    sections = [b for b in blocks if b["_kind"] == "SECTION"]
    if len(sections) > 1:
        raise GradeFileError(path, None, f"expected at most one [SECTION] block, found {len(sections)}")
    a = assigns[0]
    s = sections[0] if sections else {}
    entries, blank, students = _student_entries(path, blocks)
    return GradeFile(
        path=path,
        assignment_id=_int_field(path, a, "id", required=True),
        assignment_title=(a.get("title") or "").strip(),
        section_id=_int_field(path, s, "id", required=False) if s else None,
        section_title=(s.get("title") or "").strip(),
        instructor=(s.get("instructor") or "").strip(),
        entries=entries,
        blank_entries=blank,
        students=students,
    )


def _read_blocks(path: Path) -> list[dict]:
    return read_blocks_text(path, path.read_text(encoding="utf-8-sig"))


def read_blocks_text(path: Path, text: str) -> list[dict]:
    """The file as a list of blocks: {"_kind", "_line", "_spans", key: value, ...}.

    _spans[key] = [first, last] line numbers of that value, continuation lines
    included (blank lines after it are not); _end is the block's last
    non-blank line. Editing in the window rewrites exactly these lines.
    """
    blocks: list[dict] = []
    current: dict | None = None
    last_key = None

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()

        header = re.fullmatch(r"\[\s*([A-Za-z]+)\s*\]", stripped)
        if header:
            kind = header.group(1).upper()
            if kind not in GRADE_FILE_KEYS:
                raise GradeFileError(path, lineno, f"unknown block [{header.group(1)}]")
            current = {"_kind": kind, "_line": lineno, "_spans": {}, "_end": lineno}
            blocks.append(current)
            last_key = None
            continue

        if current is None:
            if stripped:
                raise GradeFileError(path, lineno, "text before the first [BLOCK] header")
            continue

        kv = re.match(r"\s*([A-Za-z_]+)\s*=(.*)$", line)
        if kv and kv.group(1).lower() in GRADE_FILE_KEYS[current["_kind"]]:
            key = kv.group(1).lower()
            if key in current:
                raise GradeFileError(path, lineno, f"'{key}' appears twice in one block")
            current[key] = kv.group(2).strip()
            current["_spans"][key] = [lineno, lineno]
            current["_end"] = lineno
            last_key = key
            continue

        if last_key == "comments":
            # Indentation is for readability in the file; don't send it.
            current["comments"] += "\n" + stripped
            if stripped:
                current["_spans"]["comments"][1] = lineno
                current["_end"] = lineno
            continue
        if stripped:
            raise GradeFileError(path, lineno, f"unexpected line: {stripped!r}")
    return blocks


def _int_field(path: Path, block: dict, key: str, required: bool) -> int | None:
    value = (block.get(key) or "").strip()
    if not value:
        if required:
            raise GradeFileError(path, block["_line"], f"[{block['_kind']}] needs {key}=")
        return None
    try:
        return int(value)
    except ValueError:
        raise GradeFileError(path, block["_line"],
                             f"[{block['_kind']}] {key}={value!r} is not a number")


def _student_entries(path: Path, blocks: list[dict]) -> tuple[list[GradeEntry], int,
                                                              list[GradeEntry]]:
    """The [STUDENT] blocks with a grade or comment, how many named students
    had neither, and every named student. Empty template slots are ignored."""
    entries, blank, students = [], 0, []
    for b in blocks:
        if b["_kind"] != "STUDENT":
            continue
        e = GradeEntry(line=b["_line"],
                       name=(b.get("name") or "").strip(),
                       id=(b.get("id") or "").strip(),
                       grade=(b.get("grade") or "").strip(),
                       comments=(b.get("comments") or "").strip())
        if not (e.name or e.id):
            if e.grade or e.comments:
                raise GradeFileError(path, e.line,
                                     "student has a grade or comment but no name or id")
            continue                      # unused template slot
        students.append(e)
        if not (e.grade or e.comments):
            blank += 1
            continue
        entries.append(e)
    return entries, blank, students


def overlapping(files: list[GradeFile]) -> list[list[GradeFile]]:
    """Groups of two or more files for the same assignment and section, in the
    order given. Posting all of them sends the later file's grades over the
    earlier's, so the window warns about them."""
    groups: dict[tuple, list[GradeFile]] = {}
    for gf in files:
        section = gf.section_id if gf.section_id is not None else \
            (gf.section_title or "").casefold()
        groups.setdefault((gf.assignment_id, section), []).append(gf)
    return [g for g in groups.values() if len(g) > 1]


def find_grade_files(root: Path, limit: int = 500, recursive: bool = True) -> list[Path]:
    """Grade files in root (and its subfolders, if recursive), newest first.
    Only .txt files; anything unreadable is the caller's to report."""
    root = Path(root)
    try:
        if not root.is_dir():
            return []
    except OSError:
        return []
    found = []
    for p in (root.rglob("*.txt") if recursive else root.glob("*.txt")):
        try:
            if p.is_file():
                found.append((p.stat().st_mtime, p))
        except OSError:
            continue
    found.sort(key=lambda t: (-t[0], str(t[1])))
    return [p for _, p in found[:limit]]
