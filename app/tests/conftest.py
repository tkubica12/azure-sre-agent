"""Shared pytest fixtures for PulseMart tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _no_azure_monitor_connection(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure tests never attempt to export telemetry to a real Azure Monitor
    resource, regardless of the operator's shell environment.
    """

    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    yield
