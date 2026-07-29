from __future__ import annotations

import pytest
from conftest import make_config

import labctl.status as status_mod
from labctl.context import AgentContext, WorkloadContext
from labctl.state import DeploymentState


def _context() -> WorkloadContext:
    return WorkloadContext(
        agent_resource_group="rg-agent",
        workload_resource_group="rg-workload",
        container_registry_name="crpulsemartdemo",
        container_registry_login_server="crpulsemartdemo.azurecr.io",
        workload_identity_id="id",
        workload_identity_client_id="client-id",
        log_analytics_workspace_id="law-guid",
        log_analytics_resource_id="/subscriptions/x/law",
        app_insights_app_id="appi-guid",
        app_insights_resource_id="/subscriptions/x/appi",
        app_insights_connection_string="InstrumentationKey=secret",
        container_apps_environment_id="/subscriptions/x/cae",
        container_app_name="ca-pulsemart-demo",
        container_app_id=(
            "/subscriptions/sub-1/resourceGroups/rg-workload/providers/Microsoft.App/"
            "containerApps/ca-pulsemart-demo"
        ),
        container_app_fqdn="ca-pulsemart-demo.example.azurecontainerapps.io",
        action_group_id="/subscriptions/x/ag",
        metric_alert_id="/subscriptions/x/alert",
        metric_alert_name="alert-pulsemart-checkout-5xx",
    )


def _agent_context() -> AgentContext:
    return AgentContext(
        agent_id=(
            "/subscriptions/sub-1/resourceGroups/rg-agent/providers/Microsoft.App/agents/"
            "sre-agent-demo"
        ),
        agent_name="sre-agent-demo",
        agent_resource_group="rg-agent",
        portal_url="https://sre.azure.com/#/agent/sub-1/rg-agent/sre-agent-demo",
        data_plane_endpoint="https://sre-agent-demo.swedencentral.azuresre.ai",
        uami_id="/subscriptions/sub-1/resourceGroups/rg-agent/.../sre-agent-demo-uami",
        uami_principal_id="uami-principal",
        uami_client_id="uami-client",
        system_identity_principal_id="system-principal",
        agent_app_insights_id="/subscriptions/sub-1/appi-agent",
        agent_app_insights_app_id="appi-agent-guid",
        agent_log_analytics_id="/subscriptions/sub-1/law-agent",
        agent_log_analytics_workspace_id="law-agent-guid",
        connector_names=("app-insights", "log-analytics", "azure-monitor"),
    )


def test_status_reports_not_deployed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(status_mod.ctx, "load_workload_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(status_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    messages: list[str] = []

    exit_code = status_mod.run_status(make_config(tmp_path), echo=messages.append)

    assert exit_code == 0
    assert any("NOT DEPLOYED" in m for m in messages)
    assert not any("InstrumentationKey" in m for m in messages)


def test_status_reports_deployed_endpoint_and_no_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    context = _context()
    monkeypatch.setattr(
        status_mod.ctx, "load_workload_context", lambda config, **_kw: (context, None)
    )
    monkeypatch.setattr(status_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(
        status_mod,
        "load_deployment_state",
        lambda config: DeploymentState(
            image_tag="abc123-def456",
            baseline_revision_name="ca-pulsemart-demo--baseline-abc123-def456",
            deployed_at="2026-01-01T00:00:00+00:00",
        ),
    )
    messages: list[str] = []

    exit_code = status_mod.run_status(make_config(tmp_path), echo=messages.append)

    joined = "\n".join(messages)
    assert exit_code == 0
    assert "https://ca-pulsemart-demo.example.azurecontainerapps.io" in joined
    assert "abc123-def456" in joined
    assert "InstrumentationKey" not in joined
    assert "secret" not in joined


def test_status_reports_deployed_agent_with_cost_note_and_no_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path, result_factory
) -> None:
    workload_context = _context()
    agent_context = _agent_context()
    monkeypatch.setattr(
        status_mod.ctx, "load_workload_context", lambda config, **_kw: (workload_context, None)
    )
    monkeypatch.setattr(
        status_mod.ctx, "load_agent_context", lambda config, **_kw: (agent_context, None)
    )
    monkeypatch.setattr(
        status_mod.verify_mod.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            {
                "properties": {
                    "provisioningState": "Succeeded",
                    "runningState": "Running",
                    "powerState": "Running",
                    "defaultModel": {"provider": "Anthropic", "name": "Automatic"},
                    "actionConfiguration": {"accessLevel": "High", "mode": "Review"},
                    "monthlyAgentUnitLimit": 10000,
                },
                "identity": {
                    "type": "SystemAssigned, UserAssigned",
                    "principalId": "system-principal",
                    "userAssignedIdentities": {agent_context.uami_id: {}},
                },
            },
            result_factory(stdout="{}"),
        ),
    )
    monkeypatch.setattr(
        status_mod.verify_mod.azure_cli,
        "role_assignments",
        lambda object_id, scope, **_kw: (
            ["Reader", "Log Analytics Reader", "Contributor"],
            result_factory(stdout="[]"),
        ),
    )
    monkeypatch.setattr(
        status_mod.verify_mod.azure_cli,
        "signed_in_object_id",
        lambda **_kw: ("deployer-oid", result_factory()),
    )
    monkeypatch.setattr(
        status_mod.verify_mod.agent_azure,
        "connector_list",
        lambda agent_id, **_kw: (
            [
                {"name": "app-insights", "properties": {"provisioningState": "Succeeded"}},
                {"name": "log-analytics", "properties": {"provisioningState": "Succeeded"}},
                {"name": "azure-monitor", "properties": {"provisioningState": "Succeeded"}},
            ],
            result_factory(stdout="[]"),
        ),
    )
    messages: list[str] = []

    exit_code = status_mod.run_status(make_config(tmp_path), echo=messages.append)

    joined = "\n".join(messages)
    assert exit_code == 0
    assert "sre-agent-demo" in joined
    assert "billed continuously" in joined
    assert "content directory not found" in joined
    assert "InstrumentationKey" not in joined
