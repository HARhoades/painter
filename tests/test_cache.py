"""The local cache: storage, freshness, snapshots and per-student counts."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from painter.domain.freshness import (
    WINDOWS, classify, describe, needs_check, oldest, when,
)
from painter.domain.roster import Roster
from painter.services.snapshots import (
    assignments_from_data, assignments_to_data, files_from_data, files_to_data,
)
from painter.services.submissions import (
    AssignmentFiles, AssignmentInfo, assignment_files, count_files, count_from, file_counts,
)
from painter.storage.cache import KINDS, CacheStore, Kind

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)


# ---- storage ----
def test_round_trip_and_one_folder_per_kind(tmp_path):
    c = CacheStore(tmp_path)
    c.write("assignments", "a.test_1_100", {"x": 1}, NOW)
    c.write("rosters", "a.test_1_100", {"y": 2}, NOW)
    got = c.read("assignments", "a.test_1_100")
    assert got.data == {"x": 1} and got.fetched_at == NOW
    assert (tmp_path / "assignments" / "a.test_1_100.json").exists()
    assert (tmp_path / "rosters" / "a.test_1_100.json").exists()
    assert c.read("filecounts", "a.test_1_100") is None
    assert not list(tmp_path.rglob("*.part"))


def test_damaged_or_foreign_files_read_as_not_cached(tmp_path):
    c = CacheStore(tmp_path)
    c.write("assignments", "k", {"ok": True})
    c.path("assignments", "k").write_text("{not json", encoding="utf-8")
    assert c.read("assignments", "k") is None
    c.path("assignments", "k").write_text(json.dumps(
        {"schema": 99, "fetched_at": NOW.isoformat(), "data": {}}), encoding="utf-8")
    assert c.read("assignments", "k") is None
    c.path("assignments", "k").write_text(json.dumps({"schema": 1}), encoding="utf-8")
    assert c.read("assignments", "k") is None


def test_keys_cannot_escape_the_folder(tmp_path):
    c = CacheStore(tmp_path)
    c.write("assignments", "../../evil", {"x": 1})
    assert all(tmp_path in p.parents for p in tmp_path.rglob("*.json"))


def test_clear_all_or_one_kind(tmp_path):
    c = CacheStore(tmp_path)
    for kind in KINDS:
        c.write(kind, "k", {})
    assert len(c.files()) == 3 and c.size() > 0
    c.clear(["rosters"])
    assert c.read("rosters", "k") is None and c.read("assignments", "k") is not None
    c.clear()
    assert c.files() == []


def test_a_new_kind_gets_its_own_folder_and_clears_alone(tmp_path):
    """How grade or comment files could be added later: one entry, own directory."""
    c = CacheStore(tmp_path, {**KINDS, "comments": Kind("comments", students=True)})
    c.write("comments", "k", {"c": 1})
    c.write("assignments", "k", {})
    assert (tmp_path / "comments" / "k.json").exists()
    c.clear(["comments"])
    assert c.read("comments", "k") is None and c.read("assignments", "k") is not None
    with pytest.raises(KeyError):
        CacheStore(tmp_path).write("comments", "k", {})        # unknown by default


def test_only_the_planned_kinds_exist_today():
    assert set(KINDS) == {"assignments", "rosters", "filecounts"}
    assert KINDS["rosters"].students and KINDS["filecounts"].students


# ---- freshness ----
def test_freshness_states_and_wording():
    at = NOW - timedelta(minutes=4)
    assert classify("assignments", None, now=NOW).state == "none"
    assert classify("assignments", at, now=NOW).state == "confirmed"
    assert classify("assignments", at, checking=True, now=NOW).state == "checking"
    old = NOW - WINDOWS["assignments"] - timedelta(seconds=1)
    assert classify("assignments", old, now=NOW).state == "stale"
    assert classify("assignments", at, error="offline", now=NOW).state == "failed"
    assert describe(classify("assignments", at, now=NOW), NOW) == "✓ Up to date · checked 4 min ago"
    assert describe(classify("assignments", old, checking=True, now=NOW), NOW).startswith("⟳ From")
    assert "not checked yet" in describe(classify("assignments", old, now=NOW), NOW)
    assert describe(classify("assignments", at, error="x", now=NOW), NOW).startswith("⚠ Couldn't")
    assert needs_check("rosters", NOW - timedelta(hours=23), NOW)is False
    assert needs_check("rosters", NOW - timedelta(hours=25), NOW)
    assert oldest(NOW, NOW - timedelta(hours=1)) == NOW - timedelta(hours=1)
    assert oldest(NOW, None) is None
    assert when(NOW - timedelta(seconds=10), NOW) == "just now"
    assert when(NOW - timedelta(hours=3), NOW) == "3 h ago"


# ---- snapshots ----
def test_assignments_and_counts_round_trip():
    items = [AssignmentInfo(7001, "DATE", "2026-09-01 03:59", False, True),
             AssignmentInfo(7002, "Quiz", "", True, True)]
    assert assignments_from_data(json.loads(json.dumps(assignments_to_data(items, "UTC")))) == items
    known = {7001: AssignmentFiles({501, 502}, {501: 2}, {501: 3, 502: 1})}
    back, at = files_from_data(json.loads(json.dumps(files_to_data(known, {7001: NOW}))))
    assert back == known and at == {7001: NOW}


def test_counts_hold_no_scores_grades_or_comments():
    blob = json.dumps(files_to_data({1: AssignmentFiles({5}, {5: 1}, {5: 1})}, {1: NOW}))
    for word in ("score", "grade", "comment"):
        assert word not in blob


def test_roster_round_trip_keeps_what_the_window_uses(fake_canvas):
    roster = Roster.load(*_canvas(fake_canvas))
    back = Roster.from_data(json.loads(json.dumps(roster.to_data())))
    assert back.users == {u: {k: v for k, v in d.items() if k in Roster.USER_FIELDS}
                          for u, d in roster.users.items()}
    assert back.sections_of_user == roster.sections_of_user
    assert back.users_of_section == roster.users_of_section
    assert back.catch_all == roster.catch_all
    with pytest.raises(KeyError):
        Roster.from_data({"sections": []})


def _canvas(fake):
    from conftest import BASE
    from painter.canvas.client import Canvas
    return Canvas(BASE, "test-token"), 100


# ---- per-student counts ----
@pytest.mark.parametrize("history", [False, True])
def test_local_totals_match_asking_canvas(fake_canvas, history):
    from painter.domain.selection import Selection
    canvas, course = _canvas(fake_canvas)
    roster = Roster.load(canvas, course)
    known = file_counts(canvas, course, (7001, 7002))
    assert set(known) == {7001, 7002} and isinstance(known[7001], AssignmentFiles)
    for sel in (Selection(), Selection.of(["A1-8"]), Selection.of(["A2-8"]),
                Selection.of(["A2-8"], exclude=["503"])):
        ids = sel.resolve(roster).student_ids if sel.active else None
        asked = count_files(canvas, course, (7001, 7002), sel, history)
        mine = count_from(known, (7001, 7002), ids, history)
        assert mine.files == asked.files and mine.students == asked.students
        assert {a: (c.submitted, c.files) for a, c in mine.per_assignment.items()} == \
            {a: (c.submitted, c.files) for a, c in asked.per_assignment.items()}


def test_file_counts_stop_between_assignments(fake_canvas):
    from painter.errors import Cancelled
    from painter.events import RecordingReporter
    canvas, course = _canvas(fake_canvas)
    with pytest.raises(Cancelled) as err:
        file_counts(canvas, course, (7001, 7002), reporter=RecordingReporter(cancel_after=1))
    assert set(err.value.result) == {7001}


def test_count_from_leaves_out_what_isnt_known():
    known = {1: AssignmentFiles({5, 6}, {5: 2}, {5: 2})}
    got = count_from(known, (1, 2), {5})
    assert set(got.per_assignment) == {1} and got.files == 2 and got.students == 1
