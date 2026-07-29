from __future__ import annotations

import json
from pathlib import Path

from conftest import make_config, make_result

from labctl.context import (
    build_agent_context,
    build_workload_context,
    load_agent_context,
    load_terraform_outputs,
    load_workload_context,
)

FULL_OUTPUTS = {
    "agent_resource_group_name": {"value": "rg-agent", "sensitive": False},
    "workload_resource_group_name": {"value": "rg-workload", "sensitive": False},
    "container_registry_name": {"value": "crpulsemartdemo123456", "sensitive": False},
    "container_registry_login_server": {
        "value": "crpulsemartdemo123456.azurecr.io",
        "sensitive": False,
    },
    "workload_identity_id": {"value": "/subscriptions/x/.../id-pulsemart-workload-demo"},
    "workload_identity_client_id": {"value": "11111111-1111-1111-1111-111111111111"},
    "log_analytics_workspace_id": {"value": "22222222-2222-2222-2222-222222222222"},
    "log_analytics_resource_id": {"value": "/subscriptions/x/.../law-pulsemart-demo"},
    "app_insights_app_id": {"value": "33333333-3333-3333-3333-333333333333"},
    "app_insights_resource_id": {"value": "/subscriptions/x/.../appi-pulsemart-demo"},
    "app_insights_connection_string": {
        "value": "InstrumentationKey=secret;IngestionEndpoint=https://example",
        "sensitive": True,
    },
    "container_apps_environment_id": {"value": "/subscriptions/x/.../cae-pulsemart-demo"},
    "container_app_name": {"value": "ca-pulsemart-demo"},
    "container_app_id": {"value": "/subscriptions/x/.../ca-pulsemart-demo"},
    "container_app_fqdn": {
        "value": "ca-pulsemart-demo.happyplant-123.swedencentral.azurecontainerapps.io"
    },
    "action_group_id": {"value": "/subscriptions/x/.../ag-pulsemart-checkout-demo"},
    "metric_alert_id": {"value": "/subscriptions/x/.../alert-pulsemart-checkout-5xx"},
    "metric_alert_name": {"value": "alert-pulsemart-checkout-5xx"},
}


def test_build_workload_context_with_complete_outputs() -> None:
    outputs = {name: entry["value"] for name, entry in FULL_OUTPUTS.items()}

    context = build_workload_context(outputs)

    assert context is not None
    assert context.container_app_name == "ca-pulsemart-demo"
    assert (
        context.endpoint_url()
        == "https://ca-pulsemart-demo.happyplant-123.swedencentral.azurecontainerapps.io"
    )
    non_sensitive = context.non_sensitive_dict()
    assert "app_insights_connection_string" not in non_sensitive


def test_build_workload_context_returns_none_when_incomplete() -> None:
    outputs = {name: entry["value"] for name, entry in FULL_OUTPUTS.items()}
    del outputs["container_app_fqdn"]

    assert build_workload_context(outputs) is None


def test_load_terraform_outputs_parses_cli_json(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def runner(args, **kwargs):
        assert args[0] == "output"
        return make_result(stdout=json.dumps(FULL_OUTPUTS))

    outputs, result = load_terraform_outputs(config, runner=runner)

    assert result.ok
    assert outputs is not None
    assert outputs["container_app_name"] == "ca-pulsemart-demo"


def test_load_terraform_outputs_returns_none_on_failure(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def runner(args, **kwargs):
        return make_result(stdout="", stderr="no state file", returncode=1)

    outputs, result = load_terraform_outputs(config, runner=runner)

    assert outputs is None
    assert not result.ok


def test_load_workload_context_end_to_end(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def runner(args, **kwargs):
        return make_result(stdout=json.dumps(FULL_OUTPUTS))

    context, result = load_workload_context(config, runner=runner)

    assert context is not None
    assert context.container_registry_login_server == "crpulsemartdemo123456.azurecr.io"


FULL_AGENT_OUTPUTS = {
    "agent_resource_group_name": {"value": "rg-agent"},
    "agent_id": {
        "value": "/subscriptions/sub-1/resourceGroups/rg-agent/providers/Microsoft.App/agents/"
        "sre-agent-demo"
    },
    "agent_name": {"value": "sre-agent-demo"},
    "agent_portal_url": {"value": "https://sre.azure.com/#/agent/sub-1/rg-agent/sre-agent-demo"},
    "agent_data_plane_endpoint": {"value": "https://sre-agent-demo.swedencentral.azuresre.ai"},
    "agent_uami_id": {
        "value": "/subscriptions/sub-1/resourceGroups/rg-agent/.../sre-agent-demo-uami"
    },
    "agent_uami_principal_id": {"value": "11111111-1111-1111-1111-111111111111"},
    "agent_uami_client_id": {"value": "22222222-2222-2222-2222-222222222222"},
    "agent_system_identity_principal_id": {"value": "33333333-3333-3333-3333-333333333333"},
    "agent_connector_names": {"value": ["app-insights", "log-analytics", "azure-monitor"]},
    "agent_app_insights_id": {"value": "/subscriptions/sub-1/.../appi-sre-agent-demo"},
    "agent_app_insights_app_id": {"value": "44444444-4444-4444-4444-444444444444"},
    "agent_log_analytics_id": {"value": "/subscriptions/sub-1/.../law-sre-agent-demo"},
    "agent_log_analytics_workspace_id": {"value": "55555555-5555-5555-5555-555555555555"},
}


def test_build_agent_context_with_complete_outputs() -> None:
    outputs = {name: entry["value"] for name, entry in FULL_AGENT_OUTPUTS.items()}

    context = build_agent_context(outputs)

    assert context is not None
    assert context.agent_name == "sre-agent-demo"
    assert context.connector_names == ("app-insights", "log-analytics", "azure-monitor")
    assert "agent_app_insights_id" in context.non_sensitive_dict()


def test_build_agent_context_returns_none_when_incomplete() -> None:
    outputs = {name: entry["value"] for name, entry in FULL_AGENT_OUTPUTS.items()}
    del outputs["agent_id"]

    assert build_agent_context(outputs) is None


def test_build_agent_context_returns_none_when_connector_names_not_a_list() -> None:
    outputs = {name: entry["value"] for name, entry in FULL_AGENT_OUTPUTS.items()}
    outputs["agent_connector_names"] = "not-a-list"

    assert build_agent_context(outputs) is None


def test_load_agent_context_end_to_end(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def runner(args, **kwargs):
        return make_result(stdout=json.dumps(FULL_AGENT_OUTPUTS))

    context, result = load_agent_context(config, runner=runner)

    assert context is not None
    assert context.agent_name == "sre-agent-demo"
