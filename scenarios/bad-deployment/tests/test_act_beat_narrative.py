"""Narrative-consistency checks for the `bad-deployment` scenario's Act beat
(see AGENTS.md repository layout: "scenarios/<slug>/tests/: ... exact
automated checks for each demonstration scene", and PLAN.md Milestone 5 "Act
beat rework").

Product-owner decision, 2026-07-30: the agent itself executes the real
rollback (Autonomous mode), not the presenter via `labctl demo reset`. These
checks guard against silently drifting back to the old, disproven narrative
(a Review-mode approval gate, or a read-only `rollback-advisor`) without
anyone noticing, since none of `labctl`'s own unit tests read this scenario's
prose content.

Run with the `labctl` virtualenv's Python, which already has PyYAML
installed:

    & 'labctl\\.venv\\Scripts\\python.exe' -m pytest scenarios\\bad-deployment\\tests
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_DIR = REPO_ROOT / "agent"
RUNBOOK = REPO_ROOT / "scenarios" / "bad-deployment" / "runbook" / "README.md"
SCENARIO_YAML = REPO_ROOT / "scenarios" / "bad-deployment" / "scenario.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_containerapp_5xx_response_plan_is_autonomous_not_review() -> None:
    doc = _load_yaml(AGENT_DIR / "automations" / "incident-filters" / "checkout-5xx.yaml")

    assert doc["spec"]["agentMode"] == "Autonomous"


def test_rollback_advisor_holds_the_write_tool() -> None:
    doc = _load_yaml(AGENT_DIR / "config" / "subagents" / "rollback-advisor.yaml")

    assert "RunAzCliWriteCommands" in doc["spec"]["tools"]


def test_incident_investigator_does_not_hold_the_write_tool() -> None:
    """The tool-scoping guarantee this demo relies on: only `rollback-advisor`
    can mutate Azure; `incident-investigator` stays structurally read-only."""

    doc = _load_yaml(AGENT_DIR / "config" / "subagents" / "incident-investigator.yaml")

    assert "RunAzCliWriteCommands" not in doc["spec"]["tools"]


def test_runbook_describes_agent_executed_remediation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "The agent itself performs the real rollback" in text
    # The old, disproven narrative must not silently come back.
    assert "you perform the real approved mitigation yourself" not in text
    assert "longer the demo's Act beat" in text


def test_scenario_summary_describes_agent_executed_rollback() -> None:
    doc = _load_yaml(SCENARIO_YAML)

    assert "executes a real traffic rollback" in doc["summary"]
