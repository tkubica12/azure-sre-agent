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

import re
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "labctl" / "src"))

from labctl.procutil import run_command  # noqa: E402

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


def _tracked_paths() -> list[Path]:
    result = run_command(["git", "ls-files", "-z"], cwd=REPO_ROOT, timeout=30.0, retries=0)
    assert result.ok, result.diagnostic()
    return [REPO_ROOT / p for p in result.stdout.split("\0") if p]


def _local_azure_identifiers() -> list[tuple[str, bytes]]:
    config_path = REPO_ROOT / "config.local.toml"
    if not config_path.is_file():
        return []
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    azure = data.get("azure")
    if not isinstance(azure, dict):
        return []
    identifiers = []
    for key in ("subscription_id", "tenant_id"):
        value = azure.get(key)
        if isinstance(value, str) and value:
            identifiers.append((f"azure.{key}", value.encode("utf-8")))
    return identifiers


def test_tracked_files_contain_no_obvious_secrets_or_live_azure_ids() -> None:
    """Defense in depth alongside `labctl`'s own subprocess-output redaction
    (see AGENTS.md "avoid logging ... secret values"): version-controlled
    content must never carry literal tokens, connection strings, or the live
    subscription/tenant identifiers from ignored local config.
    """

    secret_patterns = {
        "storage account key": re.compile(rb"accountkey=([A-Za-z0-9+/=]{24,})", re.IGNORECASE),
        "instrumentation key": re.compile(
            rb"instrumentationkey=([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})", re.IGNORECASE
        ),
        "client secret": re.compile(
            rb"client_secret\s*[:=]\s*['\"]?([A-Za-z0-9._~+/=-]{12,})", re.IGNORECASE
        ),
        "GitHub token": re.compile(rb"gh[opsu]_[A-Za-z0-9_]{20,}"),
    }
    local_identifiers = _local_azure_identifiers()
    for path in _tracked_paths():
        relative_parts = path.relative_to(REPO_ROOT).parts
        data = path.read_bytes()
        if "tests" not in relative_parts:
            for label, pattern in secret_patterns.items():
                for match in pattern.finditer(data):
                    value = match.group(1)
                    if label == "instrumentation key" and value.startswith(b"00000000-"):
                        continue
                    assert False, f"possible {label} in tracked file {path}"
        for label, identifier in local_identifiers:
            assert identifier not in data, f"live {label} appears in tracked file {path}"
