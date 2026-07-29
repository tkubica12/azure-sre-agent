"""`labctl status`: summarize current local and Azure state with portal deep
links (see SPEC.md section 11). Read-only; never mutates Azure or Terraform
state.
"""

from __future__ import annotations

from collections.abc import Callable

from labctl import context as ctx
from labctl import verify as verify_mod
from labctl.config import Config
from labctl.state import load_deployment_state, load_provision_state

Echo = Callable[[str], None]

PORTAL_RESOURCE_URL = "https://portal.azure.com/#@/resource{resource_id}/overview"


def _portal_link(resource_id: str) -> str:
    return PORTAL_RESOURCE_URL.format(resource_id=resource_id)


def run_status(config: Config, *, echo: Echo = print) -> int:
    echo(f"Config: {config.source_path}")
    echo(f"Region: {config.azure.region}")
    echo(
        f"Resource groups: agent={config.resource_groups.agent}, "
        f"workload={config.resource_groups.workload}"
    )

    workload_context, result = ctx.load_workload_context(config)
    if workload_context is None:
        echo("\nWorkload: NOT DEPLOYED (run `labctl deploy --yes`).")
        if result is not None and not result.ok:
            echo(f"  ({result.diagnostic()})")
    else:
        deployment_state = load_deployment_state(config)
        echo("\nWorkload: DEPLOYED")
        echo(f"  Endpoint:            {workload_context.endpoint_url()}")
        echo(f"  Container App:       {workload_context.container_app_name}")
        echo(f"  Container Registry:  {workload_context.container_registry_login_server}")
        if deployment_state.image_tag:
            echo(f"  Image tag:           {deployment_state.image_tag}")
            echo(f"  Baseline revision:   {deployment_state.baseline_revision_name}")
            echo(f"  Deployed at:         {deployment_state.deployed_at}")
        echo(f"  Container App portal: {_portal_link(workload_context.container_app_id)}")
        echo(
            "  Application Insights portal: "
            f"{_portal_link(workload_context.app_insights_resource_id)}"
        )
        echo(f"  Log Analytics portal: {_portal_link(workload_context.log_analytics_resource_id)}")
        echo(f"  Metric alert:        {workload_context.metric_alert_name}")
        echo(
            "  Cost posture:        Basic ACR, Consumption Container Apps environment "
            "(scale-to-zero capable), Log Analytics daily quota, "
            f"{config.workload.log_retention_days}-day retention. See AGENTS.md/SPEC.md section 14."
        )

    agent_context, agent_result = ctx.load_agent_context(config)
    if agent_context is None:
        echo("\nAzure SRE Agent: NOT DEPLOYED (run `labctl deploy --yes`).")
        if agent_result is not None and not agent_result.ok:
            echo(f"  ({agent_result.diagnostic()})")
    else:
        echo("\nAzure SRE Agent: DEPLOYED")
        echo(f"  Name:                {agent_context.agent_name}")
        echo(f"  Portal:              {agent_context.portal_url}")
        echo(f"  Data-plane endpoint: {agent_context.data_plane_endpoint}")

        provisioning_result, agent_data = verify_mod.check_agent_provisioning(agent_context)
        echo(
            f"  Provisioning:        [{provisioning_result.status.value}] "
            f"{provisioning_result.detail}"
        )
        properties = agent_data.get("properties") if agent_data is not None else None
        properties_dict = properties if isinstance(properties, dict) else {}
        echo(f"  Running state:       {properties_dict.get('runningState', 'Unknown')}")
        echo(f"  Power state:         {properties_dict.get('powerState', 'Unknown')}")

        identities_result = verify_mod.check_agent_identities(agent_context, agent_data)
        echo(
            f"  Identities:          [{identities_result.status.value}] {identities_result.detail}"
        )

        if workload_context is not None:
            rbac_result = verify_mod.check_agent_workload_rbac(
                config, agent_context, workload_context
            )
            echo(f"  Workload RBAC:       [{rbac_result.status.value}] {rbac_result.detail}")
        else:
            echo("  Workload RBAC:       [WARN] workload is not deployed; nothing to check.")

        admin_rbac_result = verify_mod.check_agent_admin_rbac(agent_context)
        echo(
            f"  Agent-scope RBAC:    [{admin_rbac_result.status.value}] {admin_rbac_result.detail}"
        )

        connectors_result = verify_mod.check_agent_connectors(agent_context)
        echo(
            f"  Connectors:          [{connectors_result.status.value}] {connectors_result.detail}"
        )

        configuration_result = verify_mod.check_agent_configuration(config, agent_data)
        echo(
            f"  Configuration:       [{configuration_result.status.value}] "
            f"{configuration_result.detail}"
        )
        echo(
            "  Cost posture:        This agent is billed continuously (Azure Agent Units) until "
            "deleted, independent of whether it is actively investigating anything. Run "
            "`labctl destroy --yes` to stop billing. See SPEC.md section 14."
        )

        echo("\nAzure SRE Agent data-plane content (Milestone 4, `labctl provision`):")
        provision_state = load_provision_state(config)
        if provision_state.provisioned_at:
            echo(
                f"  Last `labctl provision` run: {provision_state.provisioned_at} "
                f"({'ok' if provision_state.ok else 'completed with failures'})."
            )
        else:
            echo("  `labctl provision` has not been run yet from this machine.")
        content_results = verify_mod.check_agent_data_plane_content(
            config, agent_context, agent_data
        )
        name_width = max((len(r.name) for r in content_results), default=4)
        for content_result in content_results:
            echo(
                f"  [{content_result.status.value:<4}] {content_result.name.ljust(name_width)}"
                f"  {content_result.detail}"
            )
        return 0

    echo(
        "\nAzure SRE Agent data-plane content (Milestone 4, `labctl provision`): agent is not "
        "deployed yet; run `labctl deploy --yes` first."
    )
    return 0


__all__ = ["run_status"]
