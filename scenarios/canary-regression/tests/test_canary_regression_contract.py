from __future__ import annotations

from pathlib import Path

import yaml


SCENARIO = Path(__file__).resolve().parents[1] / "scenario.yaml"


def test_canary_regression_uses_partial_traffic_and_distinct_fault() -> None:
    document = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))

    assert document["slug"] == "canary-regression"
    assert document["fault"]["traffic_weight"] == 10
    assert document["fault"]["env"] == {"CHECKOUT_PRICING_PROFILE": "strict-decimal"}
    assert "PAYMENT_GATEWAY_PROFILE" not in document["fault"]["env"]


def test_canary_regression_has_real_alert_and_sustained_load() -> None:
    document = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))

    assert document["alert"]["name"] == "alert-pulsemart-canary-regression"
    assert document["alert"]["target_resource"] == "app_insights"
    assert document["load"]["duration_seconds"] >= 300
    assert document["load"]["min_failures_required"] >= 6
