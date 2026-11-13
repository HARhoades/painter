"""Student work and local caches stay out of git (phase 5 follow-up)."""
from pathlib import Path

from painter import config

ROOT = Path(__file__).resolve().parent.parent


def _ignored_lines():
    path = ROOT / ".gitignore"
    return {l.strip() for l in path.read_text(encoding="utf-8").splitlines()}


def test_every_private_folder_is_anchored_in_gitignore():
    lines = _ignored_lines()
    for name in config.IGNORED_DIRS:
        assert f"/{name}/" in lines, f"/{name}/ missing from .gitignore"


def test_downloads_default_to_an_ignored_folder():
    root = config.default_download_root()
    assert config.project_root() == ROOT
    assert root == ROOT / "submissions"
    assert not config.exposed_in_repo(root / "AI105-27-1")


def test_repo_folders_outside_the_ignored_ones_are_flagged(tmp_path):
    assert config.exposed_in_repo(ROOT / "docs")
    assert config.exposed_in_repo(ROOT)
    assert not config.exposed_in_repo(ROOT / ".painter-cache" / "rosters")
    assert not config.exposed_in_repo(tmp_path / "elsewhere")
    assert not config.exposed_in_repo("")


def test_real_cache_and_download_paths_are_ignored_by_git():
    """Ask git itself, not just the text of .gitignore (it needs no files to exist)."""
    import shutil
    import subprocess
    import pytest
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    from painter.storage.cache import KINDS, CacheStore
    store = CacheStore(ROOT / ".painter-cache")
    names = [store.path(k, "host_1_100").relative_to(ROOT).as_posix() for k in KINDS]
    names.append("submissions/AI105-27-1/Doe_Jane/work.docx")
    out = subprocess.run(["git", "check-ignore", *names], cwd=ROOT, text=True,
                         capture_output=True)
    if out.returncode == 128:                          # not a git checkout (e.g. a source zip)
        pytest.skip("not a git checkout")
    assert set(out.stdout.split()) == set(names)


def test_grading_code_never_uses_the_cache():
    """Grades and comments are queried, never kept: those flows don't import the cache."""
    import re
    pat = re.compile(r"storage\.cache|from painter\.storage import|painter\.services\.snapshots")
    guarded = [ROOT / "painter/services/grading.py", ROOT / "painter/services/grade_files.py",
               *sorted((ROOT / "painter/gui/views").glob("grades_*.py"))]
    assert len(guarded) >= 3
    for path in guarded:
        assert not pat.search(path.read_text(encoding="utf-8")), path.name


def test_cache_modules_do_not_mention_grades_in_their_payloads():
    text = (ROOT / "painter/services/snapshots.py").read_text(encoding="utf-8").lower()
    for word in ("score", "grade", "comment"):
        assert word not in text.replace("grading_type", ""), word
