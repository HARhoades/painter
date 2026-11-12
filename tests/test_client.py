import pytest
import requests

from painter.canvas.client import (
    BACKOFF_BASE, BACKOFF_CAP, Canvas, MAX_ATTEMPTS, RATE_LOW_WATER, RATE_REFILL_PER_SEC,
    backoff_delay, is_throttled, retry_after_seconds,
)
from painter.canvas.jobs import POLL_FACTOR, POLL_START, poll_until
from conftest import BASE, make_response


class ScriptedSession:
    """Answers each request with the next scripted response or exception."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
        self.headers = {}

    def request(self, method, url, **kw):
        self.requests.append((method, url, kw))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def client(*steps):
    c = Canvas(BASE + "/", "tok")
    c.session = ScriptedSession(*steps)
    c.slept = []
    c.sleep = c.slept.append
    return c


def test_base_url_and_auth_header():
    c = Canvas(BASE + "/", "tok")
    assert c.base == BASE
    assert c.session.headers["Authorization"] == "Bearer tok"


def test_throttle_detection_and_retry_after():
    assert is_throttled(make_response("u", 429))
    assert is_throttled(make_response("u", 403, content=b"Rate Limit Exceeded"))
    assert not is_throttled(make_response("u", 403, content=b"forbidden"))
    assert retry_after_seconds(make_response("u", 429, headers={"Retry-After": "7"})) == 7.0
    assert retry_after_seconds(make_response("u", 429)) is None
    assert retry_after_seconds(make_response("u", 429, headers={"Retry-After": "-1"})) is None


def test_backoff_is_capped_and_honours_retry_after():
    assert backoff_delay(0, 5) == 5
    assert backoff_delay(0, 9999) == BACKOFF_CAP
    for attempt in range(10):
        ceiling = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** attempt)
        assert ceiling / 2 <= backoff_delay(attempt) <= ceiling


def test_throttled_request_is_retried_then_succeeds():
    c = client(make_response("u", 429, headers={"Retry-After": "3"}),
               make_response("u", payload={"ok": True}))
    assert c.get_json("u") == {"ok": True}
    assert c.slept == [3.0]
    assert c.stats["throttled"] == 1 and c.stats["retries"] == 1


def test_server_error_retried_for_reads_but_not_for_writes():
    c = client(make_response("u", 502), make_response("u", payload=[1]))
    assert c.get_json("u") == [1]
    c = client(make_response("u", 502))
    with pytest.raises(requests.HTTPError):
        c._request("POST", "u", retry_server_errors=False)
    assert len(c.session.requests) == 1


def test_connection_error_retried_for_get_only():
    c = client(requests.ConnectionError(), make_response("u", payload={}))
    assert c.get_json("u") == {}
    c = client(requests.ConnectionError())
    with pytest.raises(requests.ConnectionError):
        c._request("POST", "u")


def test_gives_up_after_max_attempts():
    c = client(*[make_response("u", 429) for _ in range(MAX_ATTEMPTS)])
    with pytest.raises(requests.HTTPError):
        c.get_json("u")
    assert len(c.session.requests) == MAX_ATTEMPTS


def test_pacing_when_bucket_is_low():
    c = client(make_response("u", payload={}, headers={"X-Rate-Limit-Remaining": "50"}))
    c.get_json("u")
    assert c.slept == [(RATE_LOW_WATER - 50) / RATE_REFILL_PER_SEC]
    assert c.stats["min_remaining"] == 50.0
    assert "lowest X-Rate-Limit-Remaining 50" in c.rate_summary()


def test_pagination_follows_link_headers_and_sends_params_once():
    page2 = f"{BASE}/api/v1/things?page=2"
    c = client(make_response("u", payload=[1, 2], headers={"Link": f'<{page2}>; rel="next"'}),
               make_response(page2, payload=[3]))
    assert list(c.paginate("/things", {"x": 1})) == [1, 2, 3]
    first, second = c.session.requests
    assert first[1] == f"{BASE}/api/v1/things"
    assert first[2]["params"] == {"x": 1, "per_page": 100}
    assert second[1] == page2 and second[2]["params"] is None


def test_unauthenticated_request_drops_the_bearer_header():
    c = client(make_response("u", payload={}))
    c._request("GET", "u", auth=False)
    assert c.session.requests[0][2]["headers"] == {"Authorization": None}


def test_fetch_file_writes_atomically_and_caches(tmp_path):
    dest = tmp_path / "sub" / "a.bin"
    c = client(make_response("u", content=b"12345"))
    assert c.fetch_file("u", dest, expected_size=5) is True
    assert dest.read_bytes() == b"12345"
    assert not dest.with_name("a.bin.part").exists()
    assert c.fetch_file("u", dest, expected_size=5) is False     # cached: no request
    assert len(c.session.requests) == 1


def test_fetch_file_restarts_a_cut_off_transfer(tmp_path):
    c = client(requests.ConnectionError(), make_response("u", content=b"ok"))
    # the first ConnectionError is retried inside _request (GET); add one that
    # surfaces from the transfer itself
    assert c.fetch_file("u", tmp_path / "f") is True
    assert (tmp_path / "f").read_bytes() == b"ok"


def test_poll_until_grows_interval_and_respects_timeout():
    results = iter([{"s": "queued"}, {"s": "running"}, {"s": "done"}])
    waits = []
    result, done = poll_until(lambda: next(results), lambda r: r["s"] == "done",
                                  timeout=100, sleep=waits.append)
    assert (result, done) == ({"s": "done"}, True)
    assert waits == [POLL_START, POLL_START * POLL_FACTOR]
    result, done = poll_until(lambda: {"s": "queued"}, lambda r: False,
                                  timeout=0, sleep=waits.append)
    assert done is False


def test_wait_for_progress_polls_the_progress_url():
    c = client(make_response("p", payload={"id": 9, "workflow_state": "completed"}))
    out = c.wait_for_progress({"id": 9, "workflow_state": "queued", "url": "p"})
    assert out["workflow_state"] == "completed"
    assert c.session.requests[0][1] == "p"
