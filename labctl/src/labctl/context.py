"""Shared helpers for reading back the workload's deployed Azure context
(Terraform outputs) so `deploy`, `verify`, `status`, and `destroy` agree on
exactly what was created, without duplicating parsing logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labctl import terraform_cli
from labctl.config import Config
from labctl.procutil import CommandResult

TERRAFORM_DIR = Path("infra") / "environments" / "demo"


def terraform_cwd(config: Config) -> Path:
    return config.repo_root / TERRAFORM_DIR


@dataclass(frozen=True, slots=True)
class WorkloadContext:
    agent_resource_group: str
    workload_resource_group: str
    container_registry_name: str
    container_registry_login_server: str
    workload_identity_id: str
    workload_identity_client_id: str
    log_analytics_workspace_id: str
    log_analytics_resource_id: str
    app_insights_app_id: str
    app_insights_resource_id: str
    app_insights_connection_string: str
    container_apps_environment_id: str
    container_app_name: str
    container_app_id: str
    container_app_fqdn: str
    action_group_id: str
    metric_alert_id: str
    metric_alert_name: str

    def endpoint_url(self) -> str:
        return f"https://{self.container_app_fqdn}"

    def non_sensitive_dict(self) -> dict[str, Any]:
        """Every field except the Application Insights connection string,
        safe to persist under .state/ or print to the console.
        """

        data = {
            "agent_resource_group": self.agent_resource_group,
            "workload_resource_group": self.workload_resource_group,
            "container_registry_name": self.container_registry_name,
            "container_registry_login_server": self.container_registry_login_server,
            "workload_identity_id": self.workload_identity_id,
            "workload_identity_client_id": self.workload_identity_client_id,
            "log_analytics_workspace_id": self.log_analytics_workspace_id,
            "log_analytics_resource_id": self.log_analytics_resource_id,
            "app_insights_app_id": self.app_insights_app_id,
            "app_insights_resource_id": self.app_insights_resource_id,
            "container_apps_environment_id": self.container_apps_environment_id,
            "container_app_name": self.container_app_name,
            "container_app_id": self.container_app_id,
            "container_app_fqdn": self.container_app_fqdn,
            "action_group_id": self.action_group_id,
            "metric_alert_id": self.metric_alert_id,
            "metric_alert_name": self.metric_alert_name,
        }
        return data


def _outputs_from_json(raw: dict[str, Any]) -> dict[str, Any]:
    return {name: entry.get("value") for name, entry in raw.items() if isinstance(entry, dict)}


def load_terraform_outputs(
    config: Config, *, runner: terraform_cli.TerraformRunner | None = None
) -> tuple[dict[str, Any] | None, CommandResult]:
    result = terraform_cli.output_json(terraform_cwd(config), runner=runner)
    if not result.ok:
        return None, result
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, result
    if not isinstance(raw, dict):
        return None, result
    return _outputs_from_json(raw), result


def build_workload_context(outputs: dict[str, Any]) -> WorkloadContext | None:
    required = (
        "agent_resource_group_name",
        "workload_resource_group_name",
        "container_registry_name",
        "container_registry_login_server",
        "workload_identity_id",
        "workload_identity_client_id",
        "log_analytics_workspace_id",
        "log_analytics_resource_id",
        "app_insights_app_id",
        "app_insights_resource_id",
        "app_insights_connection_string",
        "container_apps_environment_id",
        "container_app_name",
        "container_app_id",
        "container_app_fqdn",
        "action_group_id",
        "metric_alert_id",
        "metric_alert_name",
    )
    if any(outputs.get(key) in (None, "") for key in required):
        return None
    return WorkloadContext(
        agent_resource_group=str(outputs["agent_resource_group_name"]),
        workload_resource_group=str(outputs["workload_resource_group_name"]),
        container_registry_name=str(outputs["container_registry_name"]),
        container_registry_login_server=str(outputs["container_registry_login_server"]),
        workload_identity_id=str(outputs["workload_identity_id"]),
        workload_identity_client_id=str(outputs["workload_identity_client_id"]),
        log_analytics_workspace_id=str(outputs["log_analytics_workspace_id"]),
        log_analytics_resource_id=str(outputs["log_analytics_resource_id"]),
        app_insights_app_id=str(outputs["app_insights_app_id"]),
        app_insights_resource_id=str(outputs["app_insights_resource_id"]),
        app_insights_connection_string=str(outputs["app_insights_connection_string"]),
        container_apps_environment_id=str(outputs["container_apps_environment_id"]),
        container_app_name=str(outputs["container_app_name"]),
        container_app_id=str(outputs["container_app_id"]),
        container_app_fqdn=str(outputs["container_app_fqdn"]),
        action_group_id=str(outputs["action_group_id"]),
        metric_alert_id=str(outputs["metric_alert_id"]),
        metric_alert_name=str(outputs["metric_alert_name"]),
    )


def load_workload_context(
    config: Config, *, runner: terraform_cli.TerraformRunner | None = None
) -> tuple[WorkloadContext | None, CommandResult | None]:
    outputs, result = load_terraform_outputs(config, runner=runner)
    if outputs is None:
        return None, result
    return build_workload_context(outputs), result


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Non-secret Terraform outputs describing the deployed Azure SRE Agent
    (see infra/modules/sre_agent and SPEC.md sections 6 and 9). Kept
    separate from :class:`WorkloadContext` since the agent and workload are
    provisioned as independent Terraform modules and consumed independently
    by `deploy`/`verify`/`status`.
    """

    agent_id: str
    agent_name: str
    agent_resource_group: str
    portal_url: str
    data_plane_endpoint: str
    uami_id: str
    uami_principal_id: str
    uami_client_id: str
    system_identity_principal_id: str
    agent_app_insights_id: str
    agent_app_insights_app_id: str
    agent_log_analytics_id: str
    agent_log_analytics_workspace_id: str
    connector_names: tuple[str, ...]

    def non_sensitive_dict(self) -> dict[str, Any]:
        """Every field, safe to persist under .state/ or print to the
        console (the agent context carries no connection strings)."""

        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_resource_group": self.agent_resource_group,
            "portal_url": self.portal_url,
            "data_plane_endpoint": self.data_plane_endpoint,
            "uami_id": self.uami_id,
            "uami_principal_id": self.uami_principal_id,
            "uami_client_id": self.uami_client_id,
            "system_identity_principal_id": self.system_identity_principal_id,
            "agent_app_insights_id": self.agent_app_insights_id,
            "agent_app_insights_app_id": self.agent_app_insights_app_id,
            "agent_log_analytics_id": self.agent_log_analytics_id,
            "agent_log_analytics_workspace_id": self.agent_log_analytics_workspace_id,
            "connector_names": list(self.connector_names),
        }


def build_agent_context(outputs: dict[str, Any]) -> AgentContext | None:
    required = (
        "agent_resource_group_name",
        "agent_id",
        "agent_name",
        "agent_portal_url",
        "agent_data_plane_endpoint",
        "agent_uami_id",
        "agent_uami_principal_id",
        "agent_uami_client_id",
        "agent_system_identity_principal_id",
        "agent_app_insights_id",
        "agent_app_insights_app_id",
        "agent_log_analytics_id",
        "agent_log_analytics_workspace_id",
    )
    if any(outputs.get(key) in (None, "") for key in required):
        return None
    connector_names = outputs.get("agent_connector_names")
    if not isinstance(connector_names, list):
        return None
    return AgentContext(
        agent_id=str(outputs["agent_id"]),
        agent_name=str(outputs["agent_name"]),
        agent_resource_group=str(outputs["agent_resource_group_name"]),
        portal_url=str(outputs["agent_portal_url"]),
        data_plane_endpoint=str(outputs["agent_data_plane_endpoint"]),
        uami_id=str(outputs["agent_uami_id"]),
        uami_principal_id=str(outputs["agent_uami_principal_id"]),
        uami_client_id=str(outputs["agent_uami_client_id"]),
        system_identity_principal_id=str(outputs["agent_system_identity_principal_id"]),
        agent_app_insights_id=str(outputs["agent_app_insights_id"]),
        agent_app_insights_app_id=str(outputs["agent_app_insights_app_id"]),
        agent_log_analytics_id=str(outputs["agent_log_analytics_id"]),
        agent_log_analytics_workspace_id=str(outputs["agent_log_analytics_workspace_id"]),
        connector_names=tuple(str(name) for name in connector_names),
    )


def load_agent_context(
    config: Config, *, runner: terraform_cli.TerraformRunner | None = None
) -> tuple[AgentContext | None, CommandResult | None]:
    outputs, result = load_terraform_outputs(config, runner=runner)
    if outputs is None:
        return None, result
    return build_agent_context(outputs), result


@dataclass(frozen=True, slots=True)
class ResourceGroupIds:
    """The exact, Terraform-authoritative resource-group IDs this
    deployment owns, used by `labctl destroy` to verify ownership against
    the real Terraform state rather than trusting resource *names* alone
    (see SPEC.md section 11 and `labctl.destroy`)."""

    agent_resource_group_id: str
    workload_resource_group_id: str


def load_resource_group_ids(
    config: Config, *, runner: terraform_cli.TerraformRunner | None = None
) -> tuple[ResourceGroupIds | None, CommandResult | None]:
    outputs, result = load_terraform_outputs(config, runner=runner)
    if outputs is None:
        return None, result
    agent_id = outputs.get("agent_resource_group_id")
    workload_id = outputs.get("workload_resource_group_id")
    if not agent_id or not workload_id:
        return None, result
    return ResourceGroupIds(
        agent_resource_group_id=str(agent_id), workload_resource_group_id=str(workload_id)
    ), result


__all__ = [
    "TERRAFORM_DIR",
    "WorkloadContext",
    "terraform_cwd",
    "load_terraform_outputs",
    "build_workload_context",
    "load_workload_context",
    "AgentContext",
    "build_agent_context",
    "load_agent_context",
    "ResourceGroupIds",
    "load_resource_group_ids",
]
