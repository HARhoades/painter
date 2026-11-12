import csv
import io
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

import canvas_fetch_submissions as cfs

ROSTER_ROWS = [
    {"Student Full Name": "Jane Doe", "Student Canvas ID": "501", "Student First Name": "Jane",
     "Student Last Name": "Doe", "Section Name": "A1-8", "Section Canvas ID": "11"},
    {"Student Full Name": "Jane Doe", "Student Canvas ID": "501", "Student First Name": "Jane",
     "Student Last Name": "Doe", "Section Name": "AI105 All", "Section Canvas ID": "10"},
    {"Student Full Name": "Rick Roe", "Student Canvas ID": "502", "Student First Name": "Rick",
     "Student Last Name": "Roe", "Section Name": "A2-8", "Section Canvas ID": "12"},
    {"Student Full Name": "Rick Roe", "Student Canvas ID": "502", "Student First Name": "Rick",
     "Student Last Name": "Roe", "Section Name": "AI105 All", "Section Canvas ID": "10"},
]


def write_roster(path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ROSTER_ROWS[0]))
        w.writeheader()
        w.writerows(ROSTER_ROWS)
    return path


def test_roster_index_matching():
    index = cfs.RosterIndex(ROSTER_ROWS, None)
    assert index.catch_all == {"AI105 All"}
    assert index.section_of == {"501": "A1-8", "502": "A2-8"}
    assert index.match("Doe-Jane_501") == ("501", "id")
    assert index.match("Doe-Jane_501__essay.pdf") == ("501", "id")
    assert index.match("doejane_501_5551234_essay.pdf") == ("501", "id")
    assert index.match("roerick_LATE_essay.pdf")[1] == "no roster match"
    assert index.match("Roe-Rick") == ("502", "name")
    assert index.match("doejane_501_502_x.pdf") == (None, "several roster IDs in the name")
    assert index.match("Nobody-Here_999") == (None, "no roster match")


def test_roster_index_section_filter():
    index = cfs.RosterIndex(ROSTER_ROWS, ["A1"])
    assert set(index.students) == {"501"}
    assert index.match("Roe-Rick_502") == (None, "student not in the selected --section")
    with pytest.raises(SystemExit):
        cfs.RosterIndex(ROSTER_ROWS, ["zzz"])


def test_read_roster_csv_rejects_other_files(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        cfs.read_roster_csv(p)
    assert len(cfs.read_roster_csv(write_roster(tmp_path / "roster.csv"))) == 4


def organize_args(src, roster, **over):
    base = dict(organize=str(src), roster=str(roster), section=None,
                organize_to=None, dry_run=False)
    base.update(over)
    return SimpleNamespace(**base)


def make_tree(root):
    (root / "Doe-Jane_501").mkdir(parents=True)
    (root / "Doe-Jane_501" / "essay.pdf").write_text("x")
    (root / "Roe-Rick_502").mkdir()
    (root / "Stranger_999").mkdir()


def test_organize_dry_run_changes_nothing(tmp_path, capsys):
    src = tmp_path / "03_DATE-Scenario"
    make_tree(src)
    roster = write_roster(tmp_path / "roster.csv")
    assert cfs.organize_submissions(organize_args(src, roster, dry_run=True)) == 0
    assert sorted(p.name for p in src.iterdir()) == ["Doe-Jane_501", "Roe-Rick_502", "Stranger_999"]
    out = capsys.readouterr()
    assert "Dry run: Move" in out.out
    assert "Stranger_999  (no roster match)" in out.err


def test_organize_moves_into_section_folders_and_logs(tmp_path, capsys):
    src = tmp_path / "03_DATE-Scenario"
    make_tree(src)
    roster = write_roster(tmp_path / "roster.csv")
    assert cfs.organize_submissions(organize_args(src, roster)) == 0
    capsys.readouterr()
    assert (src / "A1-8" / "Doe-Jane_501" / "essay.pdf").exists()
    assert (src / "A2-8" / "Roe-Rick_502").is_dir()
    assert (src / "Stranger_999").is_dir()                 # unmatched: left in place
    assert not (src / "AI105-All").exists()                # catch-all gets no folder
    logs = list(src.glob("organize_log_*.csv"))
    assert len(logs) == 1
    rows = list(csv.DictReader(open(logs[0], encoding="utf-8-sig")))
    assert {r["Result"] for r in rows} == {"moved", "left in place: no roster match"}
    # a second run is a no-op for what is already sorted
    assert cfs.organize_submissions(organize_args(src, roster)) == 0


def test_organize_copy_to_another_tree(tmp_path, capsys):
    src = tmp_path / "src"
    make_tree(src)
    roster = write_roster(tmp_path / "roster.csv")
    dest = tmp_path / "by_section"
    assert cfs.organize_submissions(organize_args(src, roster, organize_to=str(dest))) == 0
    assert (dest / "A1-8" / "Doe-Jane_501" / "essay.pdf").exists()
    assert (src / "Doe-Jane_501" / "essay.pdf").exists()
    with pytest.raises(SystemExit):
        cfs.organize_submissions(organize_args(src, roster, organize_to=str(src / "inside")))


def test_extract_zip_refuses_paths_that_escape(tmp_path, capsys):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ok/main.py", "print(1)")
        zf.writestr("../evil.txt", "x")
        zf.writestr("__MACOSX/junk", "x")
    dest = tmp_path / "out"
    assert cfs.extract(archive, dest) is True
    assert (dest / "ok" / "main.py").read_text() == "print(1)"
    assert not (tmp_path / "evil.txt").exists()
    assert not (dest / "__MACOSX").exists()
    assert "skipped unsafe path" in capsys.readouterr().out


def test_extract_tar_and_non_archives(tmp_path):
    archive = tmp_path / "a.tar"
    with tarfile.open(archive, "w") as tf:
        data = b"hello"
        info = tarfile.TarInfo("dir/hello.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    assert cfs.extract(archive, tmp_path / "t") is True
    assert (tmp_path / "t" / "dir" / "hello.txt").read_bytes() == b"hello"
    plain = tmp_path / "notes.gz"
    plain.write_text("not an archive")
    assert cfs.extract(plain, tmp_path / "n") is False
