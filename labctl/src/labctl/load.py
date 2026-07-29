"""Bounded synthetic checkout load generation for `labctl demo trigger`
(see SPEC.md section 5 "Scene 3: Bad deployment" and section 11's `demo
trigger` contract: "generate load ... wait for observable failure").

Uses only the standard library's ``concurrent.futures`` (already a
dependency-free part of Python 3.11+, matching AGENTS.md "small dependency
set") to drive a bounded number of concurrent ``POST /api/checkout``
requests and count outcomes. Never retries on a completed HTTP response --
an HTTP 500 here is an expected, counted outcome, not a transport failure.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from labctl.http_client import HttpResult
from labctl.http_client import post as http_post

#: Signature shared by `http_client.post` and any injected test double.
Poster = Callable[..., HttpResult]


@dataclass(frozen=True, slots=True)
class LoadResult:
    total: int
    succeeded: int
    failed: int
    transport_errors: int
    duration_seconds: float

    def summary(self) -> str:
        return (
            f"{self.total} requests in {self.duration_seconds:.1f}s: "
            f"{self.succeeded} succeeded, {self.failed} failed (5xx/4xx), "
            f"{self.transport_errors} transport errors"
        )


def generate_checkout_load(
    url: str,
    *,
    count: int,
    concurrency: int = 4,
    timeout: float = 15.0,
    poster: Poster = http_post,
) -> LoadResult:
    """POST to ``url`` (typically ``<endpoint>/api/checkout``) ``count``
    times using up to ``concurrency`` concurrent workers, with no retries
    (each attempt's real outcome is counted exactly once). Bounded by
    ``count * timeout / concurrency`` in the worst case, since every
    individual request already has its own ``timeout``.
    """

    if count <= 0:
        raise ValueError(f"count must be positive, got {count}.")
    if concurrency <= 0:
        raise ValueError(f"concurrency must be positive, got {concurrency}.")

    start = time.monotonic()
    results: list[HttpResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(poster, url, timeout=timeout, retries=0) for _ in range(count)]
        for future in futures:
            results.append(future.result())
    duration = time.monotonic() - start

    succeeded = sum(1 for r in results if r.ok and r.status_code < 400)
    failed = sum(1 for r in results if r.ok and r.status_code >= 400)
    transport_errors = sum(1 for r in results if not r.ok)

    return LoadResult(
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        transport_errors=transport_errors,
        duration_seconds=duration,
    )


__all__ = ["LoadResult", "generate_checkout_load", "Poster"]
