from __future__ import annotations

from labctl.http_client import HttpResult
from labctl.load import generate_checkout_load, generate_checkout_load_for


def _poster(status_codes: list[int]):
    calls: list[str] = []

    def poster(url, *, timeout, retries):
        calls.append(url)
        status = status_codes[len(calls) - 1]
        return HttpResult(ok=True, status_code=status, body="")

    return poster, calls


def test_generate_checkout_load_counts_successes_and_failures() -> None:
    poster, calls = _poster([200, 200, 500, 500, 500])

    result = generate_checkout_load(
        "https://example/api/checkout", count=5, concurrency=2, timeout=1.0, poster=poster
    )

    assert result.total == 5
    assert result.succeeded == 2
    assert result.failed == 3
    assert result.transport_errors == 0
    assert len(calls) == 5


def test_generate_checkout_load_counts_transport_errors_separately() -> None:
    def poster(url, *, timeout, retries):
        return HttpResult(ok=False, status_code=0, body="", error="connection refused")

    result = generate_checkout_load(
        "https://example/api/checkout", count=3, concurrency=1, timeout=1.0, poster=poster
    )

    assert result.total == 3
    assert result.succeeded == 0
    assert result.failed == 0
    assert result.transport_errors == 3


def test_generate_checkout_load_rejects_non_positive_count() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_checkout_load("https://example", count=0, poster=lambda *a, **k: None)


def test_generate_checkout_load_rejects_non_positive_concurrency() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_checkout_load(
            "https://example", count=1, concurrency=0, poster=lambda *a, **k: None
        )


def test_generate_checkout_load_for_sustains_until_duration() -> None:
    status_codes = [200, 500, 200, 500, 200, 500, 200, 500]
    calls = {"count": 0}

    def poster(url, *, timeout, retries):
        calls["count"] += 1
        return HttpResult(
            ok=True,
            status_code=status_codes[(calls["count"] - 1) % len(status_codes)],
            body="",
        )

    result = generate_checkout_load_for(
        "https://example/api/checkout",
        duration_seconds=0.02,
        concurrency=2,
        timeout=1.0,
        poster=poster,
    )

    assert result.total >= 2
    assert result.succeeded > 0
    assert result.failed > 0


def test_generate_checkout_load_for_can_pace_a_target_count() -> None:
    poster, calls = _poster([200, 500, 200])

    result = generate_checkout_load_for(
        "https://example/api/checkout",
        duration_seconds=0.03,
        concurrency=2,
        target_count=3,
        timeout=1.0,
        poster=poster,
    )

    assert result.total == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert len(calls) == 3


def test_generate_checkout_load_for_rejects_non_positive_duration() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_checkout_load_for(
            "https://example", duration_seconds=0, poster=lambda *a, **k: None
        )
