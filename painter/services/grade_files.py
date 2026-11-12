"""Grade files: creating blank ones from the roster, and parsing filled-in ones."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from painter.canvas.client import Canvas
from painter.errors import NotFound
from painter.domain.naming import slug
from painter.domain.roster import Roster, instructor_label, resolve_sections


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
    title = (assignment or {}).get("name", "") if assignment else label
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


def make_grade_files(canvas: Canvas, args) -> int:
    """--make-grade-files: write one blank grade file per section."""
    roster = Roster(canvas.sections(args.course),
                    canvas.student_enrollments(args.course))

    if args.section:
        section_ids = resolve_sections(roster, args.section)
    else:
        section_ids = {s["id"] for s in roster.sections}
        print("No --section given: writing a file for every section in the course.")

    # Assignment is optional; without it the header is left blank to fill in.
    assignment = None
    label = args.assignment_label
    if args.assignment:
        if len(args.assignment) > 1:
            raise SystemExit("--make-grade-files takes at most one --assignment.")
        try:
            assignment = canvas.assignment(args.course, args.assignment[0])
        except NotFound as exc:
            raise SystemExit(f"Assignment {args.assignment[0]} not found in course "
                             f"{args.course} ({exc}).")
        label = label or (assignment.get("name") or "").split()[0]
    if not label:
        raise SystemExit("Without --assignment, pass --assignment-label NAME for "
                         "the filename, e.g. --assignment-label DATE.")
    label = slug(label, 30)

    # AY and semester: from --ay/--term, else from the course's term name.
    ay, term = args.ay, args.term
    if not (ay and term):
        term_name = ((canvas.course(args.course).get("term") or {}).get("name") or "")
        parsed = parse_term_name(term_name)
        if not parsed:
            raise SystemExit(
                f"Could not read an academic year and semester from the course "
                f"term name {term_name!r}. Pass --ay and --term, e.g. --ay 27 --term 1.")
        ay, term = ay or parsed[0], term or parsed[1]
        print(f"Term {term_name!r} -> AY{ay}, semester {term}")
    ay = ay[-2:]

    instructors: dict[int, list[str]] = {}
    for enr in canvas.teacher_enrollments(args.course):
        sid = enr.get("course_section_id")
        name = instructor_label(enr)
        if sid is None or not name:
            continue
        instructors.setdefault(sid, [])
        if name not in instructors[sid]:
            instructors[sid].append(name)

    out_dir = Path(args.grade_file_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    used: dict[str, str] = {}      # filename -> section name that claimed it
    for sid in sorted(section_ids,
                      key=lambda i: roster.section_by_id[i].get("name") or ""):
        section = roster.section_by_id[sid]
        students = sorted(
            (roster.users[u] for u in roster.users_of_section.get(sid, set())),
            key=lambda u: u.get("sortable_name") or u.get("name") or "")
        if not students:
            print(f"  {section.get('name')}: no students, skipped")
            continue
        teachers = instructors.get(sid, [])
        if len(teachers) > 1:
            print(f"  note: {section.get('name')} has several instructors "
                  f"({', '.join(teachers)}); using {teachers[0]}")

        # Two sections can share a prefix (A2-8 and A2-9 both reduce to "A2"),
        # so the second one keeps its full section name instead of clobbering
        # the first.
        section_name = section.get("name") or str(sid)
        name = grade_file_name(section_name, label, ay, term)
        if name in used:
            print(f"  note: {section_name} and {used[name]} share a prefix; "
                  f"using the full section name for {section_name}")
            name = (f"{slug(section_name, 20)}-{label}"
                    f"_Grading-{ay}-{term}.txt")
        used[name] = section_name
        path = out_dir / name
        if path.exists() and not args.force:
            print(f"  ! {path} exists; not overwritten (use --force)")
            continue
        path.write_text(
            render_grade_file(assignment, label, section,
                              teachers[0] if teachers else "", students),
            encoding="utf-8")
        print(f"  {path}  ({len(students)} students)")
        written += 1

    print(f"\n{written} file(s) written to {out_dir}")
    return 0


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

    def int_field(block: dict, key: str, required: bool) -> int | None:
        value = (block.get(key) or "").strip()
        if not value:
            if required:
                raise GradeFileError(path, block["_line"],
                                     f"[{block['_kind']}] needs {key}=")
            return None
        try:
            return int(value)
        except ValueError:
            raise GradeFileError(path, block["_line"],
                                 f"[{block['_kind']}] {key}={value!r} is not a number")

    assigns = [b for b in blocks if b["_kind"] == "ASSIGNMENT"]
    if len(assigns) != 1:
        raise GradeFileError(path, None, f"expected one [ASSIGNMENT] block, found {len(assigns)}")
    sections = [b for b in blocks if b["_kind"] == "SECTION"]
    if len(sections) > 1:
        raise GradeFileError(path, None, f"expected at most one [SECTION] block, found {len(sections)}")
    a = assigns[0]
    s = sections[0] if sections else {}

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

    return GradeFile(
        path=path,
        assignment_id=int_field(a, "id", required=True),
        assignment_title=(a.get("title") or "").strip(),
        section_id=int_field(s, "id", required=False) if s else None,
        section_title=(s.get("title") or "").strip(),
        instructor=(s.get("instructor") or "").strip(),
        entries=entries,
        blank_entries=blank,
    )
