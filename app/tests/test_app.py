"""Tests for the PulseMart FastAPI application.

These tests run with ``APPLICATIONINSIGHTS_CONNECTION_STRING`` unset, so
telemetry uses a local no-op TracerProvider (see pulsemart/telemetry.py).
They validate HTTP behavior and the deterministic failure mode contract from
SPEC.md section 7, not real Azure export.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pulsemart.main import create_app
from pulsemart.settings import Settings


def _client(**overrides: str) -> TestClient:
    settings = Settings(
        pulsemart_release=overrides.get("pulsemart_release", "test-release"),
        pulsemart_environment=overrides.get("pulsemart_environment", "test"),
        container_app_revision=overrides.get("container_app_revision", "test-revision"),
        demo_failure_mode=overrides.get("demo_failure_mode", ""),
    )
    return TestClient(create_app(settings))


def test_dashboard_serves_html() -> None:
    client = _client()
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PulseMart" in response.text


def test_healthz_is_always_ok() -> None:
    client = _client()
    assert client.get("/healthz").json() == {"status": "ok"}


def test_healthz_stays_ok_during_checkout_failure_mode() -> None:
    client = _client(demo_failure_mode="checkout-500")
    assert client.get("/healthz").json() == {"status": "ok"}


def test_api_status_reports_release_and_revision() -> None:
    client = _client(pulsemart_release="2024.01.01-abc123", container_app_revision="rev-42")
    body = client.get("/api/status").json()
    assert body["release"] == "2024.01.01-abc123"
    assert body["revision"] == "rev-42"
    assert body["environment"] == "test"
    assert body["failure_mode"] is None
    assert "timestamp" in body


def test_api_status_reports_active_failure_mode() -> None:
    client = _client(demo_failure_mode="checkout-500")
    body = client.get("/api/status").json()
    assert body["failure_mode"] == "checkout-500"


def test_checkout_succeeds_when_healthy() -> None:
    client = _client()
    response = client.post("/api/checkout")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert "order_id" in body
    assert body["amount_usd"] > 0


def test_checkout_returns_500_deterministically_in_failure_mode() -> None:
    client = _client(demo_failure_mode="checkout-500")
    for _ in range(5):
        response = client.post("/api/checkout")
        assert response.status_code == 500
        body = response.json()
        assert body["status"] == "failed"
        assert "order_id" in body
        assert "error" in body


def test_no_public_endpoint_toggles_failure_mode() -> None:
    """There must be no HTTP surface to mutate DEMO_FAILURE_MODE."""

    client = _client()
    for path in ("/api/fail", "/api/failure-mode", "/api/demo", "/api/admin"):
        response = client.post(path)
        assert response.status_code in (404, 405)


def test_settings_rejects_unsupported_failure_mode() -> None:
    import os

    from pulsemart.settings import load_settings

    os.environ["DEMO_FAILURE_MODE"] = "not-a-real-mode"
    try:
        with pytest.raises(ValueError):
            load_settings()
    finally:
        del os.environ["DEMO_FAILURE_MODE"]
