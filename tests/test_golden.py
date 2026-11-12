"""Replays tests/golden/scenarios.py and compares with the saved transcripts.

These pin the command line's behaviour byte for byte while the logic is moved
out of it (phase 3). See tests/golden/scenarios.py for how to regenerate.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from golden.scenarios import SCENARIOS  # noqa: E402

HERE = Path(__file__).resolve().parent / "golden" / "transcripts"
RECORD = os.environ.get("PAINTER_GOLDEN_RECORD") == "1"
TS = re.compile(r"\d{8}_\d{6}")
UTC_MINUTE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")    # "started ... UTC"
ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)?")


class Ctx:
    def __init__(self, fake, tmp, monkeypatch, capsys):
        self.fake, self.tmp, self.monkeypatch, self.capsys = fake, tmp, monkeypatch, capsys
        self.steps = []

    def norm(self, text: str) -> str:
        text = text.replace(str(self.tmp), "<TMP>").replace(str(Path.home()), "<HOME>")
        return ISO.sub("<ISO>", UTC_MINUTE.sub("<UTC-MINUTE>", TS.sub("<TS>", text)))

    def run(self, *argv):
        from painter.cli.main import main
        from golden.legacy_argv import translate
        argv = translate(list(argv))
        self.monkeypatch.setattr(sys, "argv", ["painter", *argv])
        before_calls, before_forms = len(self.fake.calls), len(self.fake.posted_forms)
        try:
            code = main()
        except SystemExit as exc:
            code = exc.code
        except Exception as exc:                      # recorded, not hidden
            code = f"raised {type(exc).__name__}: {exc}"
        out, err = self.capsys.readouterr()
        self.steps.append({
            "argv": [self.norm(a) for a in argv],
            "exit": code if isinstance(code, (int, type(None))) else self.norm(str(code)),
            "stdout": self.norm(out).splitlines(),
            "stderr": self.norm(err).splitlines(),
            "requests": [f"{m} {p}" + (f" {json.dumps(q, sort_keys=True)}" if q else "")
                         for m, p, q in self.fake.calls[before_calls:]],
            "posted": self.fake.posted_forms[before_forms:],
        })

    def files(self) -> dict:
        out = {}
        for p in sorted(self.tmp.rglob("*")):
            if not p.is_file():
                continue
            rel = self.norm(str(p.relative_to(self.tmp)).replace("\\", "/"))
            data = p.read_bytes()
            if p.suffix in (".csv", ".txt", ".json", ".md"):
                out[rel] = self.norm(data.decode("utf-8", "replace")).splitlines()
            elif p.suffix == ".xlsx":
                out[rel] = "<xlsx>"
            elif zipfile.is_zipfile(io.BytesIO(data)):
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    out[rel] = {n: hashlib.sha256(zf.read(n)).hexdigest()[:16]
                                for n in sorted(zf.namelist())}
            else:
                out[rel] = hashlib.sha256(data).hexdigest()[:16]
        return out


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_golden(name, fake_canvas, tmp_path, monkeypatch, capsys):
    work = tmp_path / "w"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("COLUMNS", "100")          # argparse wraps usage to this
    ctx = Ctx(fake_canvas, work, monkeypatch, capsys)
    SCENARIOS[name](ctx)
    got = {"steps": ctx.steps, "files": ctx.files()}
    path = HERE / f"{name}.json"
    if RECORD:
        HERE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(got, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    assert path.exists(), f"no transcript for {name}; record with PAINTER_GOLDEN_RECORD=1"
    want = json.loads(path.read_text(encoding="utf-8"))
    assert got == want
