"""Loader for `scenarios/<slug>/scenario.yaml` (see AGENTS.md repository
layout: "scenarios/: Failure definitions, operator metadata, runbooks, and
exact automated checks for each demonstration scene").

Kept separate from :mod:`labctl.scenario` (which implements the
prepare/trigger/verify/reset orchestration) so the declarative content can be
loaded and validated independently, and so unit tests can exercise parsing
without any Azure access.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from labctl.config import Config

SCENARIOS_DIR_NAME = "scenarios"
SCENARIO_FILENAME = "scenario.yaml"


class ScenarioError(RuntimeError):
    """Raised when a scenario definition is missing or invalid."""


def scenarios_root(config: Config) -> Path:
    return config.repo_root / SCENARIOS_DIR_NAME


@dataclass(frozen=True, slots=True)
class FaultDefinition:
    env: dict[str, str]
    revision_suffix_prefix: str


@dataclass(frozen=True, slots=True)
class AlertDefinition:
    name: str
    expected_time_to_fire_minutes: tuple[int, int]
    max_wait_seconds: float
    poll_interval_seconds: float


@dataclass(frozen=True, slots=True)
class LoadDefinition:
    request_count: int
    concurrency: int
    request_timeout_seconds: float
    min_failures_required: int


@dataclass(frozen=True, slots=True)
class IncidentDefinition:
    response_plan: str
    handling_subagent: str
    title_contains: str
    severity: str


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    slug: str
    title: str
    summary: str
    estimated_duration_minutes: int
    fault: FaultDefinition
    alert: AlertDefinition
    load: LoadDefinition
    incident: IncidentDefinition
    checks: dict[str, tuple[str, ...]]


def list_scenario_slugs(config: Config) -> list[str]:
    """Every scenario directory directly under `scenarios/` that contains a
    `scenario.yaml` file, sorted for deterministic `labctl demo list` output.
    """

    root = scenarios_root(config)
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and (entry / SCENARIO_FILENAME).is_file()
    )


def _require(document: dict[str, Any], key: str) -> Any:
    if key not in document:
        raise ScenarioError(f"scenario.yaml is missing required key '{key}'.")
    return document[key]


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = _require(document, key)
    if not isinstance(value, dict):
        raise ScenarioError(f"scenario.yaml key '{key}' must be a table.")
    return value


def parse_scenario_definition(document: dict[str, Any], *, slug: str) -> ScenarioDefinition:
    fault_raw = _section(document, "fault")
    env_raw = fault_raw.get("env", {})
    if not isinstance(env_raw, dict):
        raise ScenarioError("scenario.yaml 'fault.env' must be a table.")
    fault = FaultDefinition(
        env={str(k): str(v) for k, v in env_raw.items()},
        revision_suffix_prefix=str(fault_raw.get("revision_suffix_prefix", "fault")),
    )

    alert_raw = _section(document, "alert")
    time_range = alert_raw.get("expected_time_to_fire_minutes", [1, 6])
    if not (isinstance(time_range, list) and len(time_range) == 2):
        raise ScenarioError(
            "scenario.yaml 'alert.expected_time_to_fire_minutes' must be a two-item list."
        )
    alert = AlertDefinition(
        name=str(_require(alert_raw, "name")),
        expected_time_to_fire_minutes=(int(time_range[0]), int(time_range[1])),
        max_wait_seconds=float(alert_raw.get("max_wait_seconds", 480.0)),
        poll_interval_seconds=float(alert_raw.get("poll_interval_seconds", 15.0)),
    )

    load_raw = _section(document, "load")
    load = LoadDefinition(
        request_count=int(_require(load_raw, "request_count")),
        concurrency=int(load_raw.get("concurrency", 4)),
        request_timeout_seconds=float(load_raw.get("request_timeout_seconds", 15.0)),
        min_failures_required=int(_require(load_raw, "min_failures_required")),
    )

    incident_raw = _section(document, "incident")
    incident = IncidentDefinition(
        response_plan=str(_require(incident_raw, "response_plan")),
        handling_subagent=str(_require(incident_raw, "handling_subagent")),
        title_contains=str(_require(incident_raw, "title_contains")),
        severity=str(incident_raw.get("severity", "Sev2")),
    )

    checks_raw = document.get("checks", {})
    if not isinstance(checks_raw, dict):
        raise ScenarioError("scenario.yaml 'checks' must be a table.")
    checks = {
        str(phase): tuple(str(c) for c in items)
        for phase, items in checks_raw.items()
        if isinstance(items, list)
    }

    return ScenarioDefinition(
        slug=slug,
        title=str(_require(document, "title")),
        summary=str(document.get("summary", "")),
        estimated_duration_minutes=int(document.get("estimated_duration_minutes", 15)),
        fault=fault,
        alert=alert,
        load=load,
        incident=incident,
        checks=checks,
    )


def load_scenario_definition(config: Config, slug: str) -> ScenarioDefinition:
    path = scenarios_root(config) / slug / SCENARIO_FILENAME
    if not path.is_file():
        available = ", ".join(list_scenario_slugs(config)) or "(none found)"
        raise ScenarioError(
            f"No scenario named '{slug}' (expected {path}). Available scenarios: {available}."
        )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioError(f"Failed to parse {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ScenarioError(f"{path} must contain a YAML mapping at the top level.")
    if str(document.get("slug", slug)) != slug:
        raise ScenarioError(
            f"{path} declares slug={document.get('slug')!r}, but is stored under '{slug}/'."
        )
    return parse_scenario_definition(document, slug=slug)


__all__ = [
    "SCENARIOS_DIR_NAME",
    "SCENARIO_FILENAME",
    "ScenarioError",
    "scenarios_root",
    "FaultDefinition",
    "AlertDefinition",
    "LoadDefinition",
    "IncidentDefinition",
    "ScenarioDefinition",
    "list_scenario_slugs",
    "parse_scenario_definition",
    "load_scenario_definition",
]
