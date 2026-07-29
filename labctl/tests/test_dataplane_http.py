from __future__ import annotations

import urllib.error

import labctl.dataplane_http as dataplane_http
from labctl.dataplane_http import build_multipart_body, request


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def test_request_returns_ok_true_on_a_successful_response(monkeypatch) -> None:
    monkeypatch.setattr(
        dataplane_http.urllib.request,
        "urlopen",
        lambda req, timeout: _FakeResponse(200, b'{"value": []}'),
    )

    result = request("https://agent.example/api/v2/repos", method="GET")

    assert result.ok
    assert result.status_code == 200
    assert result.json() == {"value": []}
    assert result.success()


def test_request_treats_http_error_as_a_completed_transaction(monkeypatch) -> None:
    def raise_http_error(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url,
            405,
            "Method Not Allowed",
            None,
            None,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(dataplane_http.urllib.request, "urlopen", raise_http_error)

    result = request("https://agent.example/api/v2/repos/x", method="PUT")

    assert result.ok
    assert result.status_code == 405
    assert not result.success()


def test_request_retries_on_connection_failure_then_succeeds(monkeypatch) -> None:
    attempts = {"count": 0}

    def flaky(req, timeout):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise urllib.error.URLError("connection refused")
        return _FakeResponse(200, b"{}")

    monkeypatch.setattr(dataplane_http.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(dataplane_http.time, "sleep", lambda _seconds: None)

    result = request("https://agent.example/api/v2/repos", method="GET", retries=2, retry_delay=0)

    assert result.ok
    assert attempts["count"] == 2


def test_request_gives_up_after_exhausting_retries(monkeypatch) -> None:
    monkeypatch.setattr(
        dataplane_http.urllib.request,
        "urlopen",
        lambda req, timeout: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    monkeypatch.setattr(dataplane_http.time, "sleep", lambda _seconds: None)

    result = request("https://agent.example/api/v2/repos", method="GET", retries=1, retry_delay=0)

    assert not result.ok
    assert result.status_code == 0
    assert "down" in result.error


def test_build_multipart_body_wraps_content_with_a_unique_boundary() -> None:
    body, boundary = build_multipart_body("files", "architecture.md", b"# Title", "text/markdown")

    text = body.decode("utf-8")
    assert boundary in text
    assert 'filename="architecture.md"' in text
    assert "Content-Type: text/markdown" in text
    assert text.strip().endswith(f"--{boundary}--")
    assert "# Title" in text


def test_build_multipart_body_boundaries_are_unique_per_call() -> None:
    _body1, boundary1 = build_multipart_body("files", "a.md", b"a", "text/markdown")
    _body2, boundary2 = build_multipart_body("files", "b.md", b"b", "text/markdown")

    assert boundary1 != boundary2
