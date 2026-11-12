"""Shared fixtures: a fake Canvas that answers requests.Session.request.

Nothing here touches the network. The fake is installed by patching
requests.Session.request, so it works no matter which module builds the
Canvas client.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "https://canvas.test"
FILES = "https://files.test"


def make_response(url: str, status: int = 200, payload=None, content: bytes = b"",
                  headers: dict | None = None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = url
    r.reason = "OK" if status < 400 else "Error"
    r._content = json.dumps(payload).encode() if payload is not None else content
    r._content_consumed = True
    r.encoding = "utf-8"
    r.headers.update(headers or {})
    return r


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class FakeCanvas:
    """A one-course Canvas with two sections and three students."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.posted_forms: list[dict] = []
        # (METHOD, path) -> JSON payload, bytes, or a ready Response; checked first
        self.extra: dict[tuple[str, str], object] = {}
        self.course = {"id": 100, "name": "AI105", "term": {"name": "AY27-1"}}
        self.sections = [
            {"id": 11, "name": "A1-8", "sis_section_id": "SIS-A1", "course_id": 100},
            {"id": 12, "name": "A2-8", "sis_section_id": None, "course_id": 100},
        ]
        self.students = {
            501: {"id": 501, "name": "Jane Doe", "sortable_name": "Doe, Jane",
                  "short_name": "Jane Doe", "login_id": "jdoe2"},
            502: {"id": 502, "name": "Rick Roe", "sortable_name": "Roe, Rick",
                  "short_name": "Rick Roe", "login_id": "rroe"},
            503: {"id": 503, "name": "Ana De La Cruz", "sortable_name": "De La Cruz, Ana",
                  "short_name": "Ana De La Cruz", "login_id": "adelacruz"},
        }
        self.student_sections = {501: [11], 502: [12], 503: [12]}
        self.sis = {501: "S501", 502: "S502", 503: None}
        self.teachers = [
            {"user_id": 900, "type": "TeacherEnrollment", "course_section_id": 11,
             "user": {"id": 900, "name": "Hunter Rhoades", "sortable_name": "Rhoades, Hunter"}},
            {"user_id": 901, "type": "TeacherEnrollment", "course_section_id": 12,
             "user": {"id": 901, "name": "Pat Smith", "sortable_name": "Smith, Pat"}},
            {"user_id": 902, "type": "TaEnrollment", "course_section_id": 12,
             "user": {"id": 902, "name": "Terry Aide", "sortable_name": "Aide, Terry"}},
        ]
        self.assignments = [
            {"id": 7001, "name": "DATE Scenario", "due_at": "2026-09-01T03:59:00Z",
             "points_possible": 10.0, "grading_type": "points", "published": True,
             "submission_types": ["online_upload"],
             "all_dates": [{"base": True, "due_at": "2026-09-01T03:59:00Z"}],
             "overrides": [{"course_section_id": 12, "due_at": "2026-09-03T03:59:00Z"}]},
            {"id": 7002, "name": "Reflection", "due_at": None,
             "points_possible": 5.0, "grading_type": "points", "published": True,
             "submission_types": ["online_upload"], "all_dates": [], "overrides": []},
        ]
        self.file_bodies = {
            "/f/1": b"%PDF-1.4 jane essay",
            "/f/2": zip_bytes({"main.py": b"print('hi')\n", "data/in.txt": b"1 2 3\n"}),
        }
        self.submissions = {
            7001: {
                501: {"user_id": 501, "workflow_state": "submitted", "attempt": 1,
                      "submitted_at": "2026-08-31T20:00:00Z", "seconds_late": 0,
                      "late": False, "missing": False, "score": None, "grade": None,
                      "attachments": [{"id": 1, "display_name": "essay.pdf",
                                       "url": f"{FILES}/f/1",
                                       "size": len(self.file_bodies["/f/1"])}],
                      "submission_comments": []},
                502: {"user_id": 502, "workflow_state": "submitted", "attempt": 2,
                      "submitted_at": "2026-09-04T03:59:00Z", "seconds_late": 86400,
                      "late": True, "missing": False, "score": None, "grade": None,
                      "attachments": [{"id": 2, "display_name": "analysis.zip",
                                       "url": f"{FILES}/f/2",
                                       "size": len(self.file_bodies["/f/2"])}],
                      "submission_comments": [{"comment": "Already said this."}]},
                503: {"user_id": 503, "workflow_state": "unsubmitted", "attempt": None,
                      "submitted_at": None, "seconds_late": 0, "late": False,
                      "missing": True, "score": None, "grade": None,
                      "submission_comments": []},
            },
            7002: {uid: {"user_id": uid, "workflow_state": "unsubmitted",
                         "submitted_at": None, "submission_comments": []}
                   for uid in (501, 502, 503)},
        }

    # ---- request handling -------------------------------------------------
    def handle(self, session, method, url, **kw):
        parsed = urlparse(url)
        params = {k: v for k, v in parse_qs(parsed.query).items()}
        for k, v in (kw.get("params") or {}).items():
            params[k] = v if isinstance(v, list) else [v]
        path = parsed.path
        self.calls.append((method.upper(), path, params))
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin == FILES:
            if path in self.file_bodies:
                return make_response(url, content=self.file_bodies[path])
            return make_response(url, 404, {"errors": "no file"})
        if origin != BASE:
            raise AssertionError(f"unexpected host in test: {url}")
        hit = self.extra.get((method.upper(), path))
        if hit is not None:
            if isinstance(hit, requests.Response):
                return hit
            if isinstance(hit, bytes):
                return make_response(url, content=hit)
            return make_response(url, payload=hit)
        return self._api(method.upper(), path, params, kw, url)

    def _api(self, method, path, params, kw, url):
        ok = lambda payload: make_response(url, payload=payload)   # noqa: E731
        a = "/api/v1"
        if path == f"{a}/courses/100":
            return ok(self.course)
        if path == f"{a}/courses/100/sections":
            return ok(self.sections)
        if path.startswith(f"{a}/sections/"):
            sid = int(path.rsplit("/", 1)[1])
            hit = [s for s in self.sections if s["id"] == sid]
            return ok(hit[0]) if hit else make_response(url, 404, {})
        if path == f"{a}/courses/100/enrollments":
            types = params.get("type[]", [])
            if "StudentEnrollment" in types:
                return ok([{"user_id": uid, "course_section_id": sid,
                            "type": "StudentEnrollment", "sis_user_id": self.sis[uid],
                            "user": self.students[uid]}
                           for uid, sids in self.student_sections.items() for sid in sids])
            return ok(self.teachers)
        if path == f"{a}/courses/100/assignments":
            return ok(self.assignments)
        parts = path[len(a):].strip("/").split("/")
        if parts[:3] == ["courses", "100", "assignments"] and len(parts) >= 4:
            try:
                aid = int(parts[3])
            except ValueError:
                return make_response(url, 404, {})
            hit = [x for x in self.assignments if x["id"] == aid]
            if not hit:
                return make_response(url, 404, {"errors": "not found"})
            if len(parts) == 4:
                return ok(hit[0])
            if parts[4:] == ["submissions"]:
                return ok([dict(s, user=self.students[uid])
                           for uid, s in self.submissions[aid].items()])
            if parts[4:] == ["submissions", "update_grades"] and method == "POST":
                form = dict(kw.get("data") or {})
                self.posted_forms.append(form)
                self._apply_grades(aid, form)
                return ok({"id": 1, "workflow_state": "completed",
                           "url": f"{BASE}{a}/progress/1"})
        if path == f"{a}/progress/1":
            return ok({"id": 1, "workflow_state": "completed"})
        return make_response(url, 404, {"errors": f"no route {method} {path}"})

    def _apply_grades(self, aid, form):
        for key, value in form.items():
            _, uid, field = key.replace("]", "").split("[")
            sub = self.submissions[aid][int(uid)]
            if field == "posted_grade":
                sub["grade"] = sub["entered_grade"] = value
                sub["score"] = sub["entered_score"] = float(value.rstrip("%"))
            elif field == "excuse":
                sub["excused"] = True
            elif field == "text_comment":
                sub.setdefault("submission_comments", []).append({"comment": value})


@pytest.fixture
def fake_canvas(monkeypatch):
    fake = FakeCanvas()
    monkeypatch.setattr(requests.Session, "request",
                        lambda session, method, url, **kw: fake.handle(session, method, url, **kw))
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CANVAS_API_TOKEN", "test-token")
    return fake


@pytest.fixture
def run_cli(monkeypatch, capsys):
    """Run the command line exactly as a user would; returns (code, out, err)."""
    from painter.cli.main import main

    def run(*argv: str):
        monkeypatch.setattr(sys, "argv", ["canvas_fetch_submissions.py", *argv])
        try:
            code = main()
        except SystemExit as exc:
            code = exc.code
        out, err = capsys.readouterr()
        return code, out, err
    return run
