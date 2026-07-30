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
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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


def _classify_result(result: HttpResult) -> tuple[int, int, int]:
    if result.ok and result.status_code < 400:
        return 1, 0, 0
    if result.ok:
        return 0, 1, 0
    return 0, 0, 1


def generate_checkout_load_for(
    url: str,
    *,
    duration_seconds: float,
    concurrency: int = 4,
    timeout: float = 15.0,
    target_count: int | None = None,
    poster: Poster = http_post,
) -> LoadResult:
    """POST to ``url`` continuously for ``duration_seconds``.

    Used by partial canary incidents where a small traffic slice needs
    sustained mixed production-like traffic while Azure Monitor evaluates and
    the agent investigates.
    """

    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be positive, got {duration_seconds}.")
    if concurrency <= 0:
        raise ValueError(f"concurrency must be positive, got {concurrency}.")
    if target_count is not None and target_count <= 0:
        raise ValueError(f"target_count must be positive when provided, got {target_count}.")

    start = time.monotonic()
    deadline = start + duration_seconds
    spacing_seconds = duration_seconds / target_count if target_count is not None else 0.0
    next_submit = start
    submitted = 0
    total = 0
    succeeded = 0
    failed = 0
    transport_errors = 0

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures: set[Future[HttpResult]] = set()
        while time.monotonic() < deadline or futures:
            while (
                time.monotonic() < deadline
                and len(futures) < concurrency
                and (target_count is None or submitted < target_count)
                and time.monotonic() >= next_submit
            ):
                futures.add(pool.submit(poster, url, timeout=timeout, retries=0))
                submitted += 1
                next_submit = start + (submitted * spacing_seconds)
            if not futures:
                if target_count is not None and submitted >= target_count:
                    break
                sleep_for = max(0.0, min(0.5, next_submit - time.monotonic()))
                if sleep_for:
                    time.sleep(sleep_for)
                continue
            wait_timeout = 0.5
            if target_count is not None and submitted < target_count:
                wait_timeout = max(0.0, min(wait_timeout, next_submit - time.monotonic()))
            done, futures = wait(futures, timeout=wait_timeout, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                ok_count, fail_count, transport_count = _classify_result(result)
                total += 1
                succeeded += ok_count
                failed += fail_count
                transport_errors += transport_count

    return LoadResult(
        total=total,
        succeeded=succeeded,
        failed=failed,
        transport_errors=transport_errors,
        duration_seconds=time.monotonic() - start,
    )


__all__ = ["LoadResult", "generate_checkout_load", "generate_checkout_load_for", "Poster"]
