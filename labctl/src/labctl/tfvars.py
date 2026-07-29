"""Build the Terraform variables file for `infra/environments/demo` from
`labctl`'s own typed configuration, so operators configure the environment
in exactly one place (`config.local.toml`) instead of duplicating values in
both a `.tfvars` file and TOML (see AGENTS.md "State and configuration").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from labctl.config import Config

TFVARS_FILENAME = "demo.tfvars.json"


def build_tfvars(config: Config) -> dict[str, Any]:
    return {
        "region": config.azure.region,
        "subscription_id": config.azure.subscription_id,
        "tenant_id": config.azure.tenant_id,
        "agent_resource_group_name": config.resource_groups.agent,
        "workload_resource_group_name": config.resource_groups.workload,
        "tags": {
            "repository": config.tags.repository,
            "environment": config.tags.environment,
            "owner": config.tags.owner,
            "deployment_id": config.tags.deployment_id,
        },
        "alert_notification_email": config.workload.alert_notification_email,
        "log_retention_days": config.workload.log_retention_days,
        "alert_threshold_5xx": config.workload.alert_threshold_5xx,
        "agent_name": config.agent.name,
        "agent_upgrade_channel": config.agent.upgrade_channel,
        "agent_monthly_aau_allocation": config.agent.monthly_aau_allocation,
        "agent_model_provider": config.agent.model_provider,
        "agent_model_name": config.agent.model_name,
        "agent_workload_access_level": config.agent.workload_access_level,
    }


def write_tfvars(config: Config) -> Path:
    """Write the generated tfvars file under the ignored Terraform state
    directory and return its path. Regenerated on every run so it always
    reflects the current `config.local.toml`; safe to overwrite.
    """

    state_dir = config.terraform_state_path()
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / TFVARS_FILENAME
    path.write_text(json.dumps(build_tfvars(config), indent=2) + "\n", encoding="utf-8")
    return path


__all__ = ["TFVARS_FILENAME", "build_tfvars", "write_tfvars"]
