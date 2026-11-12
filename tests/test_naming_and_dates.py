from datetime import timezone, timedelta

from painter.domain.duedates import DueDates, fmt_lateness, fmt_ts, parse_ts
from painter.domain.naming import flat_filename, safe_filename, slug, student_dir_name


def test_slug_makes_one_safe_path_component():
    assert slug("DATE Scenario") == "DATE-Scenario"
    assert slug("Doe, Jane") == "Doe-Jane"
    assert slug("a/b\\c:d*e") == "abcde"
    assert slug("") == "unnamed"
    assert slug(None) == "unnamed"
    assert slug("...trailing...") == "trailing"
    assert len(slug("x" * 200)) == 60
    assert slug("x" * 200, 10) == "x" * 10


def test_safe_filename_strips_directories_and_reserved_characters():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\Users\\x\\report.pdf") == "report.pdf"
    assert safe_filename('a<b>c:"d|e?f*.txt') == "a_b_c__d_e_f_.txt"
    assert safe_filename("") == "file"


def test_student_folder_and_flat_names():
    sub = {"user_id": 501, "user": {"sortable_name": "Doe, Jane", "name": "Jane Doe"}}
    assert student_dir_name(sub) == "Doe-Jane_501"
    assert flat_filename(sub, "essay.pdf") == "Doe-Jane_501__essay.pdf"
    assert student_dir_name({}) == "Anonymous_unknown"


def test_timestamps():
    assert parse_ts(None) is None
    assert parse_ts("not a date") is None
    assert parse_ts("2026-03-04T23:59:00Z").tzinfo is not None
    assert fmt_ts("2026-03-04T23:59:00Z") == "2026-03-04 23:59"
    est = timezone(timedelta(hours=-5))
    assert fmt_ts("2026-03-04T23:59:00Z", est) == "2026-03-04 18:59"
    assert fmt_ts(None) == ""


def test_lateness():
    assert fmt_lateness(0) == ""
    assert fmt_lateness(None) == ""
    assert fmt_lateness("junk") == ""
    assert fmt_lateness(30) == "<1m"
    assert fmt_lateness(86400 * 2 + 3600 * 3 + 60 * 14) == "2d 3h 14m"
    assert fmt_lateness(3600) == "1h"


def test_due_dates_precedence():
    assignment = {
        "due_at": "2026-09-01T00:00:00Z",
        "all_dates": [{"base": True, "due_at": "2026-09-02T00:00:00Z"}],
        "overrides": [
            {"course_section_id": 11, "due_at": "2026-09-05T00:00:00Z"},
            {"course_section_id": 12, "due_at": "2026-09-08T00:00:00Z"},
            {"student_ids": [503], "due_at": "2026-09-20T00:00:00Z"},
            {"course_section_id": 13, "due_at": None},
        ],
    }
    due = DueDates(assignment)
    assert due.effective(999, []) == ("2026-09-02T00:00:00Z", "everyone")
    assert due.effective(501, [11]) == ("2026-09-05T00:00:00Z", "section override")
    assert due.effective(501, [11, 12]) == (
        "2026-09-08T00:00:00Z", "section override (most lenient of 2)")
    assert due.effective(503, [11]) == ("2026-09-20T00:00:00Z", "student override")
    assert due.effective(501, [11, 13]) == (None, "section override (no due date)")


def test_attachment_filenames_keep_clashing_names_apart():
    """Review finding 7."""
    from painter.domain.naming import attachment_filenames
    atts = [{"id": 1, "display_name": "essay.pdf"}, {"id": 2, "display_name": "Essay.PDF"},
            {"id": 3, "display_name": "notes.txt"}, {"id": 4, "display_name": "README"},
            {"id": 5, "display_name": "README"}]
    assert attachment_filenames(atts) == [
        "essay__a1.pdf", "Essay__a2.PDF", "notes.txt", "README__a4", "README__a5"]
