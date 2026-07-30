"""Tests for the PulseMart FastAPI application.

These tests run with ``APPLICATIONINSIGHTS_CONNECTION_STRING`` unset, so
telemetry uses a local no-op TracerProvider (see pulsemart/telemetry.py).
They validate HTTP behavior and the deterministic payment-regression contract
from SPEC.md section 7, not real Azure export.
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
        payment_gateway_profile=overrides.get("payment_gateway_profile", "standard"),
        checkout_pricing_profile=overrides.get("checkout_pricing_profile", "standard"),
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


def test_healthz_stays_ok_during_checkout_regression() -> None:
    client = _client(payment_gateway_profile="legacy-acquirer")
    assert client.get("/healthz").json() == {"status": "ok"}


def test_api_status_reports_release_and_revision_without_private_configuration() -> None:
    client = _client(pulsemart_release="2024.01.01-abc123", container_app_revision="rev-42")
    body = client.get("/api/status").json()
    assert body["release"] == "2024.01.01-abc123"
    assert body["revision"] == "rev-42"
    assert "environment" not in body
    assert "payment_gateway_profile" not in body
    assert "checkout_pricing_profile" not in body
    assert "failure_mode" not in body
    assert "timestamp" in body


def test_api_status_does_not_expose_payment_profile() -> None:
    client = _client(payment_gateway_profile="legacy-acquirer")
    body = client.get("/api/status").json()
    assert "payment_gateway_profile" not in body
    assert "failure_mode" not in body


def test_checkout_succeeds_when_healthy() -> None:
    client = _client()
    response = client.post("/api/checkout")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert "order_id" in body
    assert body["amount_usd"] > 0


def test_checkout_returns_500_deterministically_during_payment_regression() -> None:
    client = _client(payment_gateway_profile="legacy-acquirer")
    for _ in range(5):
        response = client.post("/api/checkout")
        assert response.status_code == 500
        body = response.json()
        assert body["status"] == "failed"
        assert "order_id" in body
        assert body["error"] == "payment authorization temporarily unavailable"
        assert "demo" not in response.text.lower()
        assert "failure mode" not in response.text.lower()
        assert "checkout-500" not in response.text.lower()


def test_checkout_returns_500_deterministically_during_pricing_regression() -> None:
    client = _client(checkout_pricing_profile="strict-decimal")
    for _ in range(5):
        response = client.post("/api/checkout")
        assert response.status_code == 500
        body = response.json()
        assert body["status"] == "failed"
        assert "order_id" in body
        assert body["error"] == "checkout temporarily unavailable"
        assert "demo" not in response.text.lower()
        assert "failure mode" not in response.text.lower()
        assert "strict-decimal" not in response.text.lower()


def test_no_public_endpoint_toggles_payment_regression() -> None:
    """There must be no HTTP surface to mutate payment behavior."""

    client = _client()
    for path in ("/api/fail", "/api/failure-mode", "/api/demo", "/api/admin"):
        response = client.post(path)
        assert response.status_code in (404, 405)


def test_settings_rejects_unsupported_payment_profile() -> None:
    import os

    from pulsemart.settings import load_settings

    os.environ["PAYMENT_GATEWAY_PROFILE"] = "not-a-real-profile"
    try:
        with pytest.raises(ValueError):
            load_settings()
    finally:
        del os.environ["PAYMENT_GATEWAY_PROFILE"]


def test_settings_rejects_unsupported_checkout_pricing_profile() -> None:
    import os

    from pulsemart.settings import load_settings

    os.environ["CHECKOUT_PRICING_PROFILE"] = "not-a-real-profile"
    try:
        with pytest.raises(ValueError):
            load_settings()
    finally:
        del os.environ["CHECKOUT_PRICING_PROFILE"]
