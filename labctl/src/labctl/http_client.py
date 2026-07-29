"""Minimal HTTP client for probing the deployed PulseMart endpoint.

Uses only the standard library (``urllib.request``) to keep labctl's
dependency set small (see AGENTS.md "Implement labctl as a typed Python CLI
with a small dependency set"). Bounded timeout and retry semantics mirror
:mod:`labctl.procutil`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HttpResult:
    ok: bool
    status_code: int
    body: str
    error: str = ""

    def json(self) -> Any | None:
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            return None


def _request(
    url: str, *, method: str, timeout: float, headers: dict[str, str] | None = None
) -> HttpResult:
    request = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8", "replace")
            return HttpResult(ok=True, status_code=response.status, body=body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        # A non-2xx response is still a completed request; callers decide
        # whether that status code is expected (e.g. verifying the demo's
        # deterministic HTTP 500 failure mode).
        return HttpResult(ok=True, status_code=exc.code, body=body)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return HttpResult(ok=False, status_code=0, body="", error=str(exc))


def get(
    url: str, *, timeout: float = 10.0, retries: int = 2, retry_delay: float = 2.0
) -> HttpResult:
    return _retrying(lambda: _request(url, method="GET", timeout=timeout), retries, retry_delay)


def post(
    url: str, *, timeout: float = 15.0, retries: int = 1, retry_delay: float = 2.0
) -> HttpResult:
    return _retrying(lambda: _request(url, method="POST", timeout=timeout), retries, retry_delay)


def _retrying(call: Callable[[], HttpResult], retries: int, retry_delay: float) -> HttpResult:
    attempt = 0
    result = call()
    while not result.ok and attempt < retries:
        time.sleep(retry_delay)
        result = call()
        attempt += 1
    return result


__all__ = ["HttpResult", "get", "post"]
