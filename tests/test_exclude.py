"""Leaving students out of a selection (phase 5, step 4)."""
import pytest

from conftest import BASE
from painter.canvas.client import Canvas
from painter.domain.roster import Roster
from painter.domain.selection import Selection
from painter.errors import InvalidInput
from painter.services.submissions import DownloadRequest, download_submissions


@pytest.fixture
def roster(fake_canvas):
    return Roster.load(Canvas(BASE, "t"), 100)


def test_exclude_from_a_section(roster):
    res = Selection.of(sections=["A2-8"], exclude=["503"]).resolve(roster)
    assert res.student_ids == {502}
    assert ("warning", "Leaving out: De La Cruz, Ana") in res.notes


def test_exclude_alone_means_everyone_else(roster):
    assert Selection.of(exclude=["rroe"]).resolve(roster).student_ids == {501, 503}


def test_exclude_someone_not_selected_is_silent(roster):
    res = Selection.of(sections=["A1-8"], exclude=["rroe"]).resolve(roster)
    assert res.student_ids == {501}
    assert not any("Leaving out" in t for _, t in res.notes)


def test_exclude_unknown_is_an_error(roster):
    with pytest.raises(InvalidInput, match="nobody"):
        Selection.of(exclude=["nobody"]).resolve(roster)
    with pytest.raises(InvalidInput, match="--exclude"):
        Selection.of(exclude=[""]).resolve(roster)


def test_download_honours_exclude(fake_canvas, tmp_path):
    req = DownloadRequest(100, tmp_path, (7001,), Selection.of(sections=["A2-8"], exclude=["502"]),
                          excel_log=False)
    res = download_submissions(Canvas(BASE, "t"), req)
    assert not [r for r in res.rows if str(r.get("user_id")) == "502"]


def test_cli_exclude(fake_canvas, run_cli):
    code, out, err = run_cli("--base-url", BASE, "--course", "100", "list", "students",
                             "--exclude", "rroe")
    assert code == 0 and "Roe, Rick" not in out and "Doe, Jane" in out
    assert "Leaving out: Roe, Rick" in err
