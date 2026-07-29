"""Repository-wide validation for `scenarios/` (see AGENTS.md repository
layout: "tests/: End-to-end and repository-wide validation").

This suite deliberately does not import `labctl` itself (unit tests for the
loader's parsing logic live in `labctl/tests/test_scenario_definition.py`);
it instead validates the shipped content on disk matches the structure
AGENTS.md requires, independent of any one consumer. Run with the `labctl`
virtualenv's Python, which already has PyYAML installed:

    & 'labctl\\.venv\\Scripts\\python.exe' -m pytest tests
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"

REQUIRED_SCENARIO_KEYS = {
    "slug",
    "title",
    "summary",
    "estimated_duration_minutes",
    "fault",
    "alert",
    "load",
    "checks",
    "incident",
}


def _scenario_dirs() -> list[Path]:
    if not SCENARIOS_DIR.is_dir():
        return []
    return sorted(p for p in SCENARIOS_DIR.iterdir() if p.is_dir())


def test_at_least_one_scenario_is_defined() -> None:
    assert _scenario_dirs(), f"No scenario directories found under {SCENARIOS_DIR}"


@pytest.mark.parametrize("scenario_dir", _scenario_dirs(), ids=lambda p: p.name)
def test_scenario_directory_has_the_required_layout(scenario_dir: Path) -> None:
    """Per AGENTS.md: "scenarios/<scenario-slug>/: Failure definitions,
    operator metadata, runbooks, and exact automated checks"."""

    assert (scenario_dir / "scenario.yaml").is_file(), "missing scenario.yaml"
    assert (scenario_dir / "runbook").is_dir(), "missing runbook/ directory"
    assert (scenario_dir / "tests").is_dir(), "missing tests/ directory"
    assert list((scenario_dir / "runbook").glob("*.md")), "runbook/ has no markdown content"


@pytest.mark.parametrize("scenario_dir", _scenario_dirs(), ids=lambda p: p.name)
def test_scenario_yaml_has_every_required_section(scenario_dir: Path) -> None:
    document = yaml.safe_load((scenario_dir / "scenario.yaml").read_text(encoding="utf-8"))

    assert isinstance(document, dict)
    missing = REQUIRED_SCENARIO_KEYS - document.keys()
    assert not missing, f"{scenario_dir.name}/scenario.yaml is missing keys: {sorted(missing)}"
    assert document["slug"] == scenario_dir.name


@pytest.mark.parametrize("scenario_dir", _scenario_dirs(), ids=lambda p: p.name)
def test_scenario_yaml_contains_no_obvious_secrets(scenario_dir: Path) -> None:
    """Defense in depth alongside `labctl`'s own subprocess-output redaction
    (see AGENTS.md "avoid logging ... secret values"): scenario content is
    version-controlled, so it must never carry a literal token/connection
    string/key, only references to Container App secrets by name.
    """

    text = (scenario_dir / "scenario.yaml").read_text(encoding="utf-8")
    lowered = text.lower()
    for marker in ("accountkey=", "instrumentationkey=", "client_secret", "ghp_", "gho_"):
        assert marker not in lowered, f"possible secret marker {marker!r} in {scenario_dir}"
