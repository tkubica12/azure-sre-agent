"""Generic authenticated HTTP client for the Azure SRE Agent data-plane API.

Distinct from :mod:`labctl.http_client` (which only issues simple,
unauthenticated GET/POST health checks against the deployed PulseMart
workload) because the agent's own data-plane endpoint
(``https://<agent>.<region>.azuresre.ai``) needs method flexibility
(GET/PUT/POST), a bearer ``Authorization`` header, JSON and multipart
request bodies, and diagnostics that are safe to print (never containing the
token) -- see AGENTS.md "avoid logging tokens ... secret values" and SPEC.md
section 11.

Uses only the standard library, matching :mod:`labctl.http_client`'s
dependency-minimalism (see AGENTS.md "small dependency set").
"""

from __future__ import annotations

import json as _json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DataPlaneResponse:
    """Outcome of one HTTP call to the agent data-plane.

    ``ok`` means the HTTP transaction itself completed (a connection was
    made and a response received), independent of the status code; callers
    inspect ``status_code`` to decide success, matching the convention
    already used by :class:`labctl.http_client.HttpResult`.
    """

    ok: bool
    status_code: int
    body: str
    error: str = ""

    def json(self) -> Any | None:
        try:
            return _json.loads(self.body)
        except _json.JSONDecodeError:
            return None

    def success(self) -> bool:
        return self.ok and 200 <= self.status_code < 300


def _do_request(
    url: str,
    *,
    method: str,
    timeout: float,
    headers: dict[str, str] | None,
    data: bytes | None,
) -> DataPlaneResponse:
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8", "replace")
            return DataPlaneResponse(ok=True, status_code=response.status, body=body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        # A non-2xx response is still a completed HTTP transaction; callers
        # decide whether that status code is expected or a real failure.
        return DataPlaneResponse(ok=True, status_code=exc.code, body=body)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return DataPlaneResponse(ok=False, status_code=0, body="", error=str(exc))


def request(
    url: str,
    *,
    method: str,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    retry_delay: float = 3.0,
) -> DataPlaneResponse:
    """Perform one HTTP request with bounded retries on connection failure
    only (a completed non-2xx response is not retried here; callers that
    want retry-on-status behavior implement it themselves, since PUT
    semantics for this API are idempotent but not universally safe to
    blind-retry on every status code).
    """

    attempt = 0
    result = _do_request(url, method=method, timeout=timeout, headers=headers, data=data)
    while not result.ok and attempt < retries:
        time.sleep(retry_delay)
        result = _do_request(url, method=method, timeout=timeout, headers=headers, data=data)
        attempt += 1
    return result


def build_multipart_body(
    field_name: str, filename: str, content: bytes, mime_type: str
) -> tuple[bytes, str]:
    """Build a minimal single-file ``multipart/form-data`` body.

    Mirrors the official template's ``DataPlane-UploadMultipart`` helper
    (see ``bicep/Apply-Extras.ps1``). Returns ``(body_bytes, boundary)``.
    """

    boundary = f"labctl-{uuid.uuid4().hex}"
    lf = "\r\n"
    header = (
        f"--{boundary}{lf}"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"{lf}'
        f"Content-Type: {mime_type}{lf}{lf}"
    ).encode()
    footer = f"{lf}--{boundary}--{lf}".encode()
    return header + content + footer, boundary


__all__ = ["DataPlaneResponse", "request", "build_multipart_body"]
