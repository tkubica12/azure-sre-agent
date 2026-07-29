"""Typed local configuration model for labctl.

Configuration is intentionally small, non-secret, and file based. Operators
copy ``config.example.toml`` at the repository root to ``config.local.toml``
(git-ignored) and adjust values. labctl never writes secrets to either file;
authentication always uses the operator's existing Azure CLI and GitHub CLI
sessions.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Azure regions where Azure SRE Agent is currently confirmed supported for
#: this demonstration. Extend only after live validation (see PLAN.md).
SUPPORTED_AGENT_REGIONS: tuple[str, ...] = ("swedencentral",)

#: Matches the official Microsoft Terraform template's `agent_name`
#: validation (see infra/modules/sre_agent/variables.tf).
_AGENT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")

#: Valid Azure SRE Agent runtime upgrade channels (see
#: infra/modules/sre_agent/variables.tf).
SUPPORTED_UPGRADE_CHANNELS: tuple[str, ...] = ("Stable", "Preview")

#: Valid workload RBAC access levels (see infra/modules/sre_agent/variables.tf
#: `workload_access_level` and SPEC.md section 9). "narrow" is least
#: privilege; "broad" is an escape hatch matching the previously deployed
#: resource-group-wide Contributor grant.
SUPPORTED_WORKLOAD_ACCESS_LEVELS: tuple[str, ...] = ("narrow", "broad")

#: Sensible demo-sized cap on the agent's monthly Azure Agent Unit
#: allocation. Azure SRE Agent bills a fixed 4 AAUs per agent-hour always-on
#: (see https://learn.microsoft.com/azure/sre-agent/pricing-billing), which
#: alone totals ~2,880 AAU across a full calendar month even with zero
#: active-flow use. The official template's own default of 10,000 is a
#: permissive ceiling the template happens to ship with, not a documented
#: minimum requirement -- nothing in the product requires that value. This
#: cap keeps enough headroom for a full month of always-on cost plus dozens
#: of incident-investigation/remediation passes (each ~10-90 AAU per
#: Microsoft's own worked examples) without silently authorizing a much
#: larger real spend than a presenter-operated demo needs.
MAX_SENSIBLE_MONTHLY_AAU_ALLOCATION = 5000

#: Repository-relative marker files used to locate the repository root when
#: labctl is invoked from a subdirectory.
_ROOT_MARKERS: tuple[str, ...] = ("config.example.toml", "AGENTS.md")

CONFIG_EXAMPLE_FILENAME = "config.example.toml"
CONFIG_LOCAL_FILENAME = "config.local.toml"


class ConfigError(RuntimeError):
    """Raised when local configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class AzureConfig:
    region: str
    subscription_id: str = ""
    tenant_id: str = ""


@dataclass(frozen=True, slots=True)
class ResourceGroupsConfig:
    agent: str
    workload: str


@dataclass(frozen=True, slots=True)
class TagsConfig:
    repository: str
    environment: str
    owner: str
    deployment_id: str


@dataclass(frozen=True, slots=True)
class GithubConfig:
    repository: str


@dataclass(frozen=True, slots=True)
class AgentConfig:
    name: str
    monthly_aau_allocation: int
    upgrade_channel: str = "Preview"
    model_provider: str = "Anthropic"
    model_name: str = "Automatic"
    data_plane_endpoint: str = ""
    workload_access_level: str = "narrow"


@dataclass(frozen=True, slots=True)
class WorkloadConfig:
    """Non-secret settings for the PulseMart workload deployed in Milestone 2
    (see SPEC.md sections 6-9)."""

    alert_notification_email: str = ""
    alert_threshold_5xx: int = 3
    log_retention_days: int = 30


@dataclass(frozen=True, slots=True)
class PathsConfig:
    terraform_state_dir: str
    evidence_dir: str


@dataclass(frozen=True, slots=True)
class Config:
    repo_root: Path
    source_path: Path
    azure: AzureConfig
    resource_groups: ResourceGroupsConfig
    tags: TagsConfig
    github: GithubConfig
    agent: AgentConfig
    workload: WorkloadConfig
    paths: PathsConfig

    def terraform_state_path(self) -> Path:
        return self._resolve(self.paths.terraform_state_dir)

    def evidence_path(self) -> Path:
        return self._resolve(self.paths.evidence_dir)

    def _resolve(self, relative: str) -> Path:
        candidate = Path(relative)
        return candidate if candidate.is_absolute() else self.repo_root / candidate


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward from ``start`` (default: current directory) to find the
    repository root, identified by the presence of known marker files.
    """
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if all((directory / marker).is_file() for marker in _ROOT_MARKERS):
            return directory
    markers = ", ".join(_ROOT_MARKERS)
    raise ConfigError(
        f"Could not locate the repository root above {current}. "
        f"Expected to find all of: {markers}. "
        "Run labctl from within the azure-sre-agent repository."
    )


def _require(table: dict[str, Any], key: str, section: str) -> Any:
    if key not in table:
        raise ConfigError(
            f"Missing required key '{key}' in [{section}] section of the config file."
        )
    return table[key]


def _require_str(table: dict[str, Any], key: str, section: str) -> str:
    value = _require(table, key, section)
    if not isinstance(value, str):
        raise ConfigError(
            f"Expected '{key}' in [{section}] to be a string, got {type(value).__name__}."
        )
    return value


def _require_int(table: dict[str, Any], key: str, section: str) -> int:
    value = _require(table, key, section)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(
            f"Expected '{key}' in [{section}] to be an integer, got {type(value).__name__}."
        )
    return value


def _optional_str(table: dict[str, Any], key: str, default: str = "") -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"Expected '{key}' to be a string, got {type(value).__name__}.")
    return value


def _optional_int(table: dict[str, Any], key: str, default: int) -> int:
    value = table.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"Expected '{key}' to be an integer, got {type(value).__name__}.")
    return value


def _section(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name)
    if value is None:
        raise ConfigError(f"Missing required [{name}] section in the config file.")
    if not isinstance(value, dict):
        raise ConfigError(f"Expected [{name}] to be a table.")
    return value


def parse_config(document: dict[str, Any], *, repo_root: Path, source_path: Path) -> Config:
    """Parse and validate an already-loaded TOML document into a ``Config``."""

    azure_raw = _section(document, "azure")
    azure = AzureConfig(
        region=_require_str(azure_raw, "region", "azure"),
        subscription_id=_optional_str(azure_raw, "subscription_id"),
        tenant_id=_optional_str(azure_raw, "tenant_id"),
    )
    if azure.region not in SUPPORTED_AGENT_REGIONS:
        supported = ", ".join(SUPPORTED_AGENT_REGIONS)
        raise ConfigError(
            f"azure.region '{azure.region}' is not a currently supported Azure SRE "
            f"Agent region for this demonstration. Supported: {supported}."
        )

    rg_raw = _section(document, "resource_groups")
    resource_groups = ResourceGroupsConfig(
        agent=_require_str(rg_raw, "agent", "resource_groups"),
        workload=_require_str(rg_raw, "workload", "resource_groups"),
    )

    tags_raw = _section(document, "tags")
    tags = TagsConfig(
        repository=_require_str(tags_raw, "repository", "tags"),
        environment=_require_str(tags_raw, "environment", "tags"),
        owner=_require_str(tags_raw, "owner", "tags"),
        deployment_id=_require_str(tags_raw, "deployment_id", "tags"),
    )

    github_raw = _section(document, "github")
    github = GithubConfig(repository=_require_str(github_raw, "repository", "github"))
    if "/" not in github.repository:
        raise ConfigError("github.repository must be in 'owner/repo' form.")

    agent_raw = _section(document, "agent")
    agent = AgentConfig(
        name=_require_str(agent_raw, "name", "agent"),
        monthly_aau_allocation=_require_int(agent_raw, "monthly_aau_allocation", "agent"),
        upgrade_channel=_optional_str(agent_raw, "upgrade_channel", "Preview"),
        model_provider=_optional_str(agent_raw, "model_provider", "Anthropic"),
        model_name=_optional_str(agent_raw, "model_name", "Automatic"),
        data_plane_endpoint=_optional_str(agent_raw, "data_plane_endpoint"),
        workload_access_level=_optional_str(agent_raw, "workload_access_level", "narrow"),
    )
    if not (0 < agent.monthly_aau_allocation <= MAX_SENSIBLE_MONTHLY_AAU_ALLOCATION):
        raise ConfigError(
            f"agent.monthly_aau_allocation must be between 1 and "
            f"{MAX_SENSIBLE_MONTHLY_AAU_ALLOCATION} (a demo-sized cap; see SPEC.md section 14). "
            f"Got {agent.monthly_aau_allocation}. The official template's own 10,000 default is "
            "a permissive ceiling, not a required minimum."
        )
    if agent.workload_access_level not in SUPPORTED_WORKLOAD_ACCESS_LEVELS:
        supported = ", ".join(SUPPORTED_WORKLOAD_ACCESS_LEVELS)
        raise ConfigError(
            f"agent.workload_access_level '{agent.workload_access_level}' must be one of: "
            f"{supported}."
        )
    if not _AGENT_NAME_PATTERN.match(agent.name):
        raise ConfigError(
            f"agent.name '{agent.name}' must be lowercase alphanumeric with hyphens, "
            "2-63 characters (matching the Azure SRE Agent resource name requirement)."
        )
    if agent.upgrade_channel not in SUPPORTED_UPGRADE_CHANNELS:
        supported = ", ".join(SUPPORTED_UPGRADE_CHANNELS)
        raise ConfigError(
            f"agent.upgrade_channel '{agent.upgrade_channel}' must be one of: {supported}."
        )

    paths_raw = _section(document, "paths")
    paths = PathsConfig(
        terraform_state_dir=_require_str(paths_raw, "terraform_state_dir", "paths"),
        evidence_dir=_require_str(paths_raw, "evidence_dir", "paths"),
    )

    workload_raw = _section(document, "workload")
    workload = WorkloadConfig(
        alert_notification_email=_optional_str(workload_raw, "alert_notification_email"),
        alert_threshold_5xx=_optional_int(workload_raw, "alert_threshold_5xx", 3),
        log_retention_days=_optional_int(workload_raw, "log_retention_days", 30),
    )

    return Config(
        repo_root=repo_root,
        source_path=source_path,
        azure=azure,
        resource_groups=resource_groups,
        tags=tags,
        github=github,
        agent=agent,
        workload=workload,
        paths=paths,
    )


def load_config(*, repo_root: Path | None = None, explicit_path: Path | None = None) -> Config:
    """Load ``config.local.toml`` (or ``explicit_path``) from the repository root.

    Raises ``ConfigError`` with an actionable message if the file is missing,
    unreadable, or fails validation.
    """

    root = repo_root or find_repo_root()
    path = explicit_path or (root / CONFIG_LOCAL_FILENAME)
    if not path.is_file():
        example = root / CONFIG_EXAMPLE_FILENAME
        raise ConfigError(
            f"Local configuration file not found at {path}. "
            f"Copy {example} to {path} and adjust it for your environment."
        )
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    return parse_config(document, repo_root=root, source_path=path)


__all__ = [
    "SUPPORTED_AGENT_REGIONS",
    "SUPPORTED_UPGRADE_CHANNELS",
    "SUPPORTED_WORKLOAD_ACCESS_LEVELS",
    "MAX_SENSIBLE_MONTHLY_AAU_ALLOCATION",
    "CONFIG_EXAMPLE_FILENAME",
    "CONFIG_LOCAL_FILENAME",
    "ConfigError",
    "AzureConfig",
    "ResourceGroupsConfig",
    "TagsConfig",
    "GithubConfig",
    "AgentConfig",
    "WorkloadConfig",
    "PathsConfig",
    "Config",
    "find_repo_root",
    "parse_config",
    "load_config",
]
