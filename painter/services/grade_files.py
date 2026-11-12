"""Grade files: creating blank ones from the roster, and parsing filled-in ones."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from painter.canvas.client import Canvas
from painter.domain.naming import slug
from painter.domain.roster import Roster, resolve_sections, section_instructors
from painter.errors import InvalidInput
from painter.events import NULL, ItemDone, Reporter, emit, watches_canvas
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


def section_prefix(section_name: str) -> str:
    """Filename prefix from a section name: 'A1-8' -> 'A1', 'A1' -> 'A1'."""
    head = re.split(r"[-–_\s]", (section_name or "").strip(), maxsplit=1)[0]
    return slug(head, 20)


def grade_file_name(section_name: str, label: str, ay: str, term: str) -> str:
    """<Section><Number>-<ASSIGNMENT>_Grading-AY<YY>-<SEMESTER>, e.g.
    A1-DATE_Grading-27-1.txt (the AY is written as the two-digit year)."""
    return f"{section_prefix(section_name)}-{label}_Grading-{ay}-{term}.txt"


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
    label: str | None = None                 # filename label; default: first word of
                                             # the assignment name
    ay: str | None = None                    # default: from the course term name
    term: str | None = None
    force: bool = False                      # overwrite existing files


@dataclass
class GradeFilesResult:
    out_dir: Path
    written: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)       # existed, not overwritten


def _assignment_and_label(canvas: Canvas, req: GradeFilesRequest) -> tuple[dict | None, str]:
    """The assignment (optional: without it the header is left blank to fill
    in) and the label that names the files."""
    label = req.label
    assignment = require_one(canvas, req.course_id, req.assignment_ids,
                             "--make-grade-files takes at most one --assignment.",
                             optional=True)
    if assignment:
        label = label or (assignment.get("name") or "").split()[0]
    if not label:
        raise InvalidInput("Without --assignment, pass --assignment-label NAME for "
                           "the filename, e.g. --assignment-label DATE.")
    return assignment, slug(label, 30)


def _academic_term(canvas: Canvas, req: GradeFilesRequest,
                   reporter: Reporter) -> tuple[str, str]:
    """AY (two digits) and semester: from --ay/--term, else the course's term name."""
    ay, term = req.ay, req.term
    if not (ay and term):
        term_name = ((canvas.course(req.course_id).get("term") or {}).get("name") or "")
        parsed = parse_term_name(term_name)
        if not parsed:
            raise InvalidInput(
                f"Could not read an academic year and semester from the course "
                f"term name {term_name!r}. Pass --ay and --term, e.g. --ay 27 --term 1.")
        ay, term = ay or parsed[0], term or parsed[1]
        reporter.info(f"Term {term_name!r} -> AY{ay}, semester {term}")
    return ay[-2:], term


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
    ay, term = _academic_term(canvas, req, reporter)

    # Teachers first, TAs only where a section has no teacher: the same rule
    # as the roster CSV (review finding 6).
    instructors = section_instructors(canvas, req.course_id)

    out_dir = Path(req.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = GradeFilesResult(out_dir)
    used: dict[str, str] = {}      # filename -> section name that claimed it
    for sid in sorted(section_ids,
                      key=lambda i: roster.section_by_id[i].get("name") or ""):
        section = roster.section_by_id[sid]
        students = sorted(
            (roster.users[u] for u in roster.users_of_section.get(sid, set())),
            key=lambda u: u.get("sortable_name") or u.get("name") or "")
        if not students:
            reporter.info(f"  {section.get('name')}: no students, skipped")
            continue
        teachers = instructors.get(sid, [])
        if len(teachers) > 1:
            reporter.info(f"  note: {section.get('name')} has several instructors "
                          f"({', '.join(teachers)}); using {teachers[0]}")

        # Two sections can share a prefix (A2-8 and A2-9 both reduce to "A2"),
        # so the second one keeps its full section name instead of clobbering
        # the first.
        section_name = section.get("name") or str(sid)
        name = grade_file_name(section_name, label, ay, term)
        if name in used:
            reporter.info(f"  note: {section_name} and {used[name]} share a prefix; "
                          f"using the full section name for {section_name}")
            name = (f"{slug(section_name, 20)}-{label}"
                    f"_Grading-{ay}-{term}.txt")
        used[name] = section_name
        path = out_dir / name
        if path.exists() and not req.force:
            reporter.info(f"  ! {path} exists; not overwritten (use --force)")
            result.kept.append(path)
            reporter.event(ItemDone("file", path.name, "kept", section_name, path))
            continue
        path.write_text(
            render_grade_file(assignment, label, section,
                              teachers[0] if teachers else "", students),
            encoding="utf-8")
        reporter.info(f"  {path}  ({len(students)} students)")
        result.written.append(path)
        reporter.event(ItemDone("file", path.name, "written", section_name, path))

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


def parse_grade_file(path: Path) -> GradeFile:
    """Read a grade file of [ASSIGNMENT], [SECTION] and [STUDENT] blocks.

    A line that does not start with a key known to its block continues the
    previous comments= value, so comments can span lines. Anything else
    unexpected is an error, reported with its line number.
    """
    blocks = _read_blocks(path)
    assigns = [b for b in blocks if b["_kind"] == "ASSIGNMENT"]
    if len(assigns) != 1:
        raise GradeFileError(path, None, f"expected one [ASSIGNMENT] block, found {len(assigns)}")
    sections = [b for b in blocks if b["_kind"] == "SECTION"]
    if len(sections) > 1:
        raise GradeFileError(path, None, f"expected at most one [SECTION] block, found {len(sections)}")
    a = assigns[0]
    s = sections[0] if sections else {}
    entries, blank = _student_entries(path, blocks)
    return GradeFile(
        path=path,
        assignment_id=_int_field(path, a, "id", required=True),
        assignment_title=(a.get("title") or "").strip(),
        section_id=_int_field(path, s, "id", required=False) if s else None,
        section_title=(s.get("title") or "").strip(),
        instructor=(s.get("instructor") or "").strip(),
        entries=entries,
        blank_entries=blank,
    )


def _read_blocks(path: Path) -> list[dict]:
    """The file as a list of blocks: {"_kind", "_line", key: value, ...}."""
    blocks: list[dict] = []
    current: dict | None = None
    last_key = None

    text = path.read_text(encoding="utf-8-sig")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()

        header = re.fullmatch(r"\[\s*([A-Za-z]+)\s*\]", stripped)
        if header:
            kind = header.group(1).upper()
            if kind not in GRADE_FILE_KEYS:
                raise GradeFileError(path, lineno, f"unknown block [{header.group(1)}]")
            current = {"_kind": kind, "_line": lineno}
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
            last_key = key
            continue

        if last_key == "comments":
            # Indentation is for readability in the file; don't send it.
            current["comments"] += "\n" + stripped
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


def _student_entries(path: Path, blocks: list[dict]) -> tuple[list[GradeEntry], int]:
    """The [STUDENT] blocks with a grade or comment, and how many named
    students had neither. Empty template slots are ignored."""
    entries, blank = [], 0
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
        if not (e.grade or e.comments):
            blank += 1
            continue
        entries.append(e)
    return entries, blank
