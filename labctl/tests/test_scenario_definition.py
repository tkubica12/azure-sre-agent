from __future__ import annotations

import pytest
from conftest import make_config

from labctl.scenario_definition import (
    ScenarioError,
    list_scenario_slugs,
    load_scenario_definition,
    parse_scenario_definition,
)

MINIMAL_DOCUMENT: dict[str, object] = {
    "slug": "bad-deployment",
    "title": "Bad deployment",
    "summary": "A summary.",
    "estimated_duration_minutes": 15,
    "fault": {"env": {"DEMO_FAILURE_MODE": "checkout-500"}, "revision_suffix_prefix": "fault"},
    "alert": {
        "name": "alert-pulsemart-checkout-5xx",
        "expected_time_to_fire_minutes": [1, 6],
        "max_wait_seconds": 480,
        "poll_interval_seconds": 15,
    },
    "load": {
        "request_count": 40,
        "concurrency": 4,
        "request_timeout_seconds": 15,
        "min_failures_required": 6,
    },
    "checks": {"fault_active": ["checkout_returns_500"], "recovered": ["checkout_returns_200"]},
    "incident": {
        "response_plan": "checkout-5xx",
        "handling_subagent": "incident-investigator",
        "title_contains": "checkout",
        "severity": "Sev2",
    },
}


def test_parse_scenario_definition_reads_every_section() -> None:
    scenario = parse_scenario_definition(MINIMAL_DOCUMENT, slug="bad-deployment")

    assert scenario.slug == "bad-deployment"
    assert scenario.title == "Bad deployment"
    assert scenario.fault.env == {"DEMO_FAILURE_MODE": "checkout-500"}
    assert scenario.fault.revision_suffix_prefix == "fault"
    assert scenario.alert.name == "alert-pulsemart-checkout-5xx"
    assert scenario.alert.expected_time_to_fire_minutes == (1, 6)
    assert scenario.load.request_count == 40
    assert scenario.load.min_failures_required == 6
    assert scenario.incident.title_contains == "checkout"
    assert scenario.checks["fault_active"] == ("checkout_returns_500",)


def test_parse_scenario_definition_requires_fault_section() -> None:
    document = {k: v for k, v in MINIMAL_DOCUMENT.items() if k != "fault"}

    with pytest.raises(ScenarioError, match="fault"):
        parse_scenario_definition(document, slug="bad-deployment")


def test_parse_scenario_definition_requires_alert_name() -> None:
    document = dict(MINIMAL_DOCUMENT)
    document["alert"] = {k: v for k, v in MINIMAL_DOCUMENT["alert"].items() if k != "name"}  # type: ignore[union-attr]

    with pytest.raises(ScenarioError, match="name"):
        parse_scenario_definition(document, slug="bad-deployment")


def test_list_scenario_slugs_finds_directories_with_scenario_yaml(tmp_path) -> None:
    config = make_config(tmp_path)
    (tmp_path / "scenarios" / "bad-deployment").mkdir(parents=True)
    (tmp_path / "scenarios" / "bad-deployment" / "scenario.yaml").write_text(
        "slug: bad-deployment\ntitle: x\n", encoding="utf-8"
    )
    (tmp_path / "scenarios" / "empty-dir").mkdir(parents=True)

    assert list_scenario_slugs(config) == ["bad-deployment"]


def test_list_scenario_slugs_returns_empty_list_when_scenarios_dir_missing(tmp_path) -> None:
    config = make_config(tmp_path)

    assert list_scenario_slugs(config) == []


def test_load_scenario_definition_raises_for_unknown_slug(tmp_path) -> None:
    config = make_config(tmp_path)

    with pytest.raises(ScenarioError, match="No scenario named"):
        load_scenario_definition(config, "does-not-exist")


def test_load_scenario_definition_reads_the_real_shipped_scenario() -> None:
    """Guards against the shipped scenarios/bad-deployment/scenario.yaml
    drifting out of sync with the loader's schema."""

    repo_root = _real_repo_root()
    config = make_config(repo_root)

    scenario = load_scenario_definition(config, "bad-deployment")

    assert scenario.slug == "bad-deployment"
    assert scenario.fault.env.get("DEMO_FAILURE_MODE") == "checkout-500"
    assert scenario.incident.title_contains == "checkout"


def _real_repo_root():
    from pathlib import Path

    from labctl.config import find_repo_root

    return find_repo_root(Path(__file__).resolve())
