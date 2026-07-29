"""Local, non-secret deployment metadata persisted under the ignored
Terraform state directory (see AGENTS.md "State and configuration").

This is deliberately separate from Terraform state: it records the
Azure-CLI-owned facts Terraform does not track because of the `template`/
`ingress` lifecycle ignore rule (see infra/modules/container_app), such as
which immutable image tag and revision suffix is currently the known-good
baseline. `labctl verify`/`status`/`demo *` read it back; it is regenerated,
never hand-edited.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from labctl.config import Config

DEPLOYMENT_STATE_FILENAME = "deployment.json"
PROVISION_STATE_FILENAME = "provision.json"


@dataclass(frozen=True, slots=True)
class DeploymentState:
    image_tag: str = ""
    image_ref: str = ""
    baseline_revision_suffix: str = ""
    baseline_revision_name: str = ""
    deployed_at: str = ""
    git_commit: str = ""
    terraform_outputs: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True, slots=True)
class ProvisionState:
    """Local, non-secret record of the last `labctl provision` run (see
    :mod:`labctl.provision`). Purely informational for `labctl status`;
    `labctl verify` always re-reads the live agent data plane rather than
    trusting this file, since it is the only source of truth for whether
    content actually exists on the agent.
    """

    provisioned_at: str = ""
    ok: bool = False
    github_wired: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def _state_path(config: Config) -> Path:
    return config.terraform_state_path() / DEPLOYMENT_STATE_FILENAME


def _provision_state_path(config: Config) -> Path:
    return config.terraform_state_path() / PROVISION_STATE_FILENAME


def load_deployment_state(config: Config) -> DeploymentState:
    path = _state_path(config)
    if not path.is_file():
        return DeploymentState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DeploymentState()
    if not isinstance(raw, dict):
        return DeploymentState()
    known_fields = {f for f in DeploymentState.__dataclass_fields__}
    filtered = {k: v for k, v in raw.items() if k in known_fields}
    return DeploymentState(**filtered)


def save_deployment_state(config: Config, state: DeploymentState) -> Path:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.to_json(), encoding="utf-8")
    return path


def _scenario_state_path(config: Config, slug: str) -> Path:
    return config.terraform_state_path() / f"scenario-{slug}.json"


@dataclass(frozen=True, slots=True)
class ScenarioState:
    """Local, non-secret record of one scenario's current fault/reset phase
    and the exact revision names involved (see AGENTS.md "Record and restore
    the known-good baseline revision/traffic in `.state/`" and SPEC.md
    section 7: Terraform ignores scenario-owned traffic/template fields, so
    `labctl` is the only source of truth for which revision is currently the
    fault revision).
    """

    slug: str = ""
    fault_active: bool = False
    fault_revision_name: str = ""
    fault_revision_suffix: str = ""
    baseline_revision_name: str = ""
    triggered_at: str = ""
    alert_fired_at: str = ""
    incident_thread_id: str = ""
    incident_thread_title: str = ""
    last_reset_at: str = ""
    run_count: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def load_scenario_state(config: Config, slug: str) -> ScenarioState:
    path = _scenario_state_path(config, slug)
    if not path.is_file():
        return ScenarioState(slug=slug)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ScenarioState(slug=slug)
    if not isinstance(raw, dict):
        return ScenarioState(slug=slug)
    known_fields = {f for f in ScenarioState.__dataclass_fields__}
    filtered = {k: v for k, v in raw.items() if k in known_fields}
    filtered.setdefault("slug", slug)
    return ScenarioState(**filtered)


def save_scenario_state(config: Config, state: ScenarioState) -> Path:
    path = _scenario_state_path(config, state.slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.to_json(), encoding="utf-8")
    return path


def load_provision_state(config: Config) -> ProvisionState:
    path = _provision_state_path(config)
    if not path.is_file():
        return ProvisionState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ProvisionState()
    if not isinstance(raw, dict):
        return ProvisionState()
    known_fields = {f for f in ProvisionState.__dataclass_fields__}
    filtered = {k: v for k, v in raw.items() if k in known_fields}
    return ProvisionState(**filtered)


def save_provision_state(config: Config, state: ProvisionState) -> Path:
    path = _provision_state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.to_json(), encoding="utf-8")
    return path


__all__ = [
    "DEPLOYMENT_STATE_FILENAME",
    "DeploymentState",
    "load_deployment_state",
    "save_deployment_state",
    "PROVISION_STATE_FILENAME",
    "ProvisionState",
    "load_provision_state",
    "save_provision_state",
    "ScenarioState",
    "load_scenario_state",
    "save_scenario_state",
]
