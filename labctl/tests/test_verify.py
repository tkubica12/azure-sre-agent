from __future__ import annotations

import pytest

import labctl.verify as verify
from labctl import agent_content, workload_azure
from labctl.context import AgentContext, WorkloadContext
from labctl.http_client import HttpResult
from labctl.verify import Status, summarize

BASE_URL = "https://ca-pulsemart-demo.example.azurecontainerapps.io"


def _context(**overrides: object) -> WorkloadContext:
    defaults: dict[str, object] = dict(
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
        metric_alert_name="alert-pulsemart-containerapp-5xx",
    )
    defaults.update(overrides)
    return WorkloadContext(**defaults)  # type: ignore[arg-type]


def _agent_context(**overrides: object) -> AgentContext:
    defaults: dict[str, object] = dict(
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
    defaults.update(overrides)
    return AgentContext(**defaults)  # type: ignore[arg-type]


def test_check_endpoint_health_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify, "http_get", lambda url, **_kw: HttpResult(ok=True, status_code=200, body="{}")
    )

    result = verify.check_endpoint_health(BASE_URL)

    assert result.status == Status.PASS


def test_check_endpoint_health_fails_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify,
        "http_get",
        lambda url, **_kw: HttpResult(ok=False, status_code=0, body="", error="timeout"),
    )

    result = verify.check_endpoint_health(BASE_URL)

    assert result.status == Status.FAIL


def test_check_checkout_behavior_expects_200_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url, **_kw):
        return HttpResult(ok=True, status_code=200, body='{"revision": "rev"}')

    def fake_post(url, **_kw):
        return HttpResult(ok=True, status_code=200, body='{"status": "confirmed"}')

    monkeypatch.setattr(verify, "http_get", fake_get)
    monkeypatch.setattr(verify, "http_post", fake_post)

    result = verify.check_checkout_behavior(BASE_URL)

    assert result.status == Status.PASS


def test_check_checkout_behavior_fails_when_checkout_is_returning_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url, **_kw):
        return HttpResult(ok=True, status_code=200, body='{"revision": "rev"}')

    def fake_post(url, **_kw):
        return HttpResult(ok=True, status_code=500, body='{"status": "failed"}')

    monkeypatch.setattr(verify, "http_get", fake_get)
    monkeypatch.setattr(verify, "http_post", fake_post)

    result = verify.check_checkout_behavior(BASE_URL)

    assert result.status == Status.FAIL


def test_check_checkout_behavior_fails_on_unexpected_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url, **_kw):
        return HttpResult(ok=True, status_code=200, body='{"revision": "rev"}')

    def fake_post(url, **_kw):
        return HttpResult(ok=True, status_code=500, body='{"status": "failed"}')

    monkeypatch.setattr(verify, "http_get", fake_get)
    monkeypatch.setattr(verify, "http_post", fake_post)

    result = verify.check_checkout_behavior(BASE_URL)

    assert result.status == Status.FAIL


def test_check_revision_mode_pass(monkeypatch: pytest.MonkeyPatch, result_factory) -> None:
    def fake_show(name, rg, **_kw):
        return {
            "properties": {"configuration": {"activeRevisionsMode": "Multiple"}}
        }, result_factory(stdout="{}")

    monkeypatch.setattr(workload_azure, "containerapp_show", fake_show)

    result = verify.check_revision_mode(_context())

    assert result.status == Status.PASS


def test_check_revision_mode_fails_for_single_mode(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    def fake_show(name, rg, **_kw):
        return {"properties": {"configuration": {"activeRevisionsMode": "Single"}}}, result_factory(
            stdout="{}"
        )

    monkeypatch.setattr(workload_azure, "containerapp_show", fake_show)

    result = verify.check_revision_mode(_context())

    assert result.status == Status.FAIL


def test_check_traffic_target_pass_when_sums_to_100(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    def fake_show(name, rg, **_kw):
        return [{"revisionName": "ca-pulsemart-demo--baseline-x", "weight": 100}], result_factory(
            stdout="[]"
        )

    monkeypatch.setattr(workload_azure, "containerapp_ingress_traffic_show", fake_show)

    result = verify.check_traffic_target(_context())

    assert result.status == Status.PASS


def test_check_traffic_target_warns_when_not_100(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    def fake_show(name, rg, **_kw):
        return [
            {"revisionName": "a", "weight": 50},
            {"revisionName": "b", "weight": 30},
        ], result_factory(stdout="[]")

    monkeypatch.setattr(workload_azure, "containerapp_ingress_traffic_show", fake_show)

    result = verify.check_traffic_target(_context())

    assert result.status == Status.WARN


def test_check_metric_alert_pass(monkeypatch: pytest.MonkeyPatch, result_factory) -> None:
    def fake_show(name, rg, **_kw):
        return {
            "enabled": True,
            "criteria": {"allOf": [{"metricName": "Requests"}]},
        }, result_factory(stdout="{}")

    monkeypatch.setattr(workload_azure, "monitor_metric_alert_show", fake_show)

    result = verify.check_metric_alert(_context())

    assert result.status == Status.PASS


def test_check_metric_alert_fails_when_disabled(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    def fake_show(name, rg, **_kw):
        return {
            "enabled": False,
            "criteria": {"allOf": [{"metricName": "Requests"}]},
        }, result_factory(stdout="{}")

    monkeypatch.setattr(workload_azure, "monitor_metric_alert_show", fake_show)

    result = verify.check_metric_alert(_context())

    assert result.status == Status.FAIL


def test_check_log_analytics_telemetry_retries_then_passes(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    calls = {"n": 0}

    def fake_query(workspace_id, query, **_kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return [], result_factory(stdout="[]")
        return [{"Count": 5}], result_factory(stdout="[]")

    monkeypatch.setattr(workload_azure, "log_analytics_query", fake_query)

    result = verify.check_log_analytics_telemetry(_context(), attempts=5, delay_seconds=0.0)

    assert result.status == Status.PASS
    assert calls["n"] == 3


def test_check_log_analytics_telemetry_warns_when_never_found(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    def fake_query(workspace_id, query, **_kw):
        return [], result_factory(stdout="[]")

    monkeypatch.setattr(workload_azure, "log_analytics_query", fake_query)

    result = verify.check_log_analytics_telemetry(_context(), attempts=2, delay_seconds=0.0)

    assert result.status == Status.WARN


def test_check_app_insights_telemetry_pass(monkeypatch: pytest.MonkeyPatch, result_factory) -> None:
    def fake_query(app_id, query, **_kw):
        return [{"Count": 7}], result_factory(stdout="[]")

    monkeypatch.setattr(workload_azure, "app_insights_query", fake_query)

    result = verify.check_app_insights_telemetry(_context(), attempts=1, delay_seconds=0.0)

    assert result.status == Status.PASS


def test_check_agent_provisioning_pass(monkeypatch: pytest.MonkeyPatch, result_factory) -> None:
    monkeypatch.setattr(
        verify.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            {"properties": {"provisioningState": "Succeeded"}},
            result_factory(stdout="{}"),
        ),
    )

    result, data = verify.check_agent_provisioning(_agent_context())

    assert result.status == Status.PASS
    assert data is not None


def test_check_agent_provisioning_fails_when_failed(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            {"properties": {"provisioningState": "Failed"}},
            result_factory(stdout="{}"),
        ),
    )

    result, _data = verify.check_agent_provisioning(_agent_context())

    assert result.status == Status.FAIL


def test_check_agent_provisioning_warns_when_still_converging(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            {"properties": {"provisioningState": "Provisioning"}},
            result_factory(stdout="{}"),
        ),
    )

    result, _data = verify.check_agent_provisioning(_agent_context())

    assert result.status == Status.WARN


def test_check_agent_provisioning_fails_when_unreachable(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (None, result_factory(returncode=1, stderr="not found")),
    )

    result, data = verify.check_agent_provisioning(_agent_context())

    assert result.status == Status.FAIL
    assert data is None


def test_check_agent_identities_pass() -> None:
    agent_context = _agent_context()
    data = {
        "identity": {
            "type": "SystemAssigned, UserAssigned",
            "principalId": "system-principal",
            "userAssignedIdentities": {agent_context.uami_id: {}},
        }
    }

    result = verify.check_agent_identities(agent_context, data)

    assert result.status == Status.PASS


def test_check_agent_identities_fails_when_uami_missing() -> None:
    agent_context = _agent_context()
    data = {
        "identity": {
            "type": "SystemAssigned, UserAssigned",
            "principalId": "system-principal",
            "userAssignedIdentities": {},
        }
    }

    result = verify.check_agent_identities(agent_context, data)

    assert result.status == Status.FAIL


def test_check_agent_configuration_pass(tmp_path) -> None:
    from conftest import make_config

    config = make_config(tmp_path)
    data = {
        "properties": {
            "defaultModel": {"provider": "Anthropic", "name": "Automatic"},
            "actionConfiguration": {"accessLevel": "High", "mode": "Review"},
            "monthlyAgentUnitLimit": 3000,
            "upgradeChannel": "Preview",
            "experimentalSettings": {
                "EnableWorkspaceTools": True,
                "EnableHttpTriggers": True,
                "EnableV2AgentLoop": True,
            },
        }
    }

    result = verify.check_agent_configuration(config, data)

    assert result.status == Status.PASS


def test_check_agent_configuration_fails_on_mismatch(tmp_path) -> None:
    from conftest import make_config

    config = make_config(tmp_path)
    data = {
        "properties": {
            "defaultModel": {"provider": "Anthropic", "name": "Automatic"},
            "actionConfiguration": {"accessLevel": "Low", "mode": "Automatic"},
            "monthlyAgentUnitLimit": 3000,
            "upgradeChannel": "Preview",
            "experimentalSettings": {
                "EnableWorkspaceTools": True,
                "EnableHttpTriggers": True,
                "EnableV2AgentLoop": True,
            },
        }
    }

    result = verify.check_agent_configuration(config, data)

    assert result.status == Status.FAIL
    assert "accessLevel" in result.detail
    assert "mode" in result.detail


def test_check_agent_configuration_fails_when_experimental_flag_missing(tmp_path) -> None:
    from conftest import make_config

    config = make_config(tmp_path)
    data = {
        "properties": {
            "defaultModel": {"provider": "Anthropic", "name": "Automatic"},
            "actionConfiguration": {"accessLevel": "High", "mode": "Review"},
            "monthlyAgentUnitLimit": 3000,
            "upgradeChannel": "Preview",
            "experimentalSettings": {"EnableWorkspaceTools": True, "EnableHttpTriggers": True},
        }
    }

    result = verify.check_agent_configuration(config, data)

    assert result.status == Status.FAIL
    assert "EnableV2AgentLoop" in result.detail


def test_check_agent_workload_rbac_pass_narrow(
    monkeypatch: pytest.MonkeyPatch, result_factory, tmp_path
) -> None:
    from conftest import make_config

    def fake_role_assignments(object_id, scope, **_kw):
        if scope.endswith("/containerApps/ca-pulsemart-demo"):
            return ["Container Apps Contributor"], result_factory(stdout="[]")
        return ["Reader", "Log Analytics Reader"], result_factory(stdout="[]")

    monkeypatch.setattr(verify.azure_cli, "role_assignments", fake_role_assignments)

    result = verify.check_agent_workload_rbac(make_config(tmp_path), _agent_context(), _context())

    assert result.status == Status.PASS


def test_check_agent_workload_rbac_fails_when_role_missing(
    monkeypatch: pytest.MonkeyPatch, result_factory, tmp_path
) -> None:
    from conftest import make_config

    def fake_role_assignments(object_id, scope, **_kw):
        return ["Reader"], result_factory(stdout="[]")

    monkeypatch.setattr(verify.azure_cli, "role_assignments", fake_role_assignments)

    result = verify.check_agent_workload_rbac(make_config(tmp_path), _agent_context(), _context())

    assert result.status == Status.FAIL


def test_check_agent_workload_rbac_pass_broad(
    monkeypatch: pytest.MonkeyPatch, result_factory, tmp_path
) -> None:
    from conftest import make_config

    from labctl.config import AgentConfig

    def fake_role_assignments(object_id, scope, **_kw):
        return ["Reader", "Log Analytics Reader", "Contributor"], result_factory(stdout="[]")

    monkeypatch.setattr(verify.azure_cli, "role_assignments", fake_role_assignments)
    config = make_config(
        tmp_path,
        agent=AgentConfig(
            name="sre-agent-demo", monthly_aau_allocation=3000, workload_access_level="broad"
        ),
    )

    result = verify.check_agent_workload_rbac(config, _agent_context(), _context())

    assert result.status == Status.PASS


def test_check_agent_alert_lifecycle_rbac_pass_custom_role(
    monkeypatch: pytest.MonkeyPatch, result_factory, tmp_path
) -> None:
    from conftest import make_config

    config = make_config(tmp_path)
    expected_role = "Azure SRE Agent Alert Lifecycle - sre-agent-demo - local"

    def fake_role_assignments(object_id: str, scope: str, **_kw: object):
        if scope.endswith("/resourceGroups/rg-agent"):
            return (["Monitoring Reader"], result_factory(stdout="[]"))
        if object_id == "uami-principal":
            return ([expected_role], result_factory(stdout="[]"))
        return ([], result_factory(stdout="[]"))

    monkeypatch.setattr(verify.azure_cli, "role_assignments", fake_role_assignments)
    monkeypatch.setattr(
        verify.azure_cli,
        "role_definition_by_name",
        lambda name, **_kw: (
            {
                "roleName": name,
                "permissions": [
                    {
                        "actions": [
                            "Microsoft.AlertsManagement/alerts/read",
                            "Microsoft.AlertsManagement/alerts/changestate/action",
                        ]
                    }
                ],
            },
            result_factory(stdout="[]"),
        ),
    )

    result = verify.check_agent_alert_lifecycle_rbac(config, _agent_context())

    assert result.status == Status.PASS
    assert "exactly alert read/change-state actions" in result.detail


def test_check_agent_alert_lifecycle_rbac_fails_on_monitoring_contributor(
    monkeypatch: pytest.MonkeyPatch, result_factory, tmp_path
) -> None:
    from conftest import make_config

    config = make_config(tmp_path)
    expected_role = "Azure SRE Agent Alert Lifecycle - sre-agent-demo - local"

    def fake_role_assignments(object_id: str, scope: str, **_kw: object):
        if scope.endswith("/resourceGroups/rg-agent"):
            return (["Monitoring Reader"], result_factory(stdout="[]"))
        if object_id == "uami-principal":
            return ([expected_role, "Monitoring Contributor"], result_factory(stdout="[]"))
        return (["Monitoring Contributor"], result_factory(stdout="[]"))

    monkeypatch.setattr(verify.azure_cli, "role_assignments", fake_role_assignments)
    monkeypatch.setattr(
        verify.azure_cli,
        "role_definition_by_name",
        lambda name, **_kw: (
            {
                "roleName": name,
                "permissions": [
                    {
                        "actions": [
                            "Microsoft.AlertsManagement/alerts/read",
                            "Microsoft.AlertsManagement/alerts/changestate/action",
                        ]
                    }
                ],
            },
            result_factory(stdout="[]"),
        ),
    )

    result = verify.check_agent_alert_lifecycle_rbac(config, _agent_context())

    assert result.status == Status.FAIL
    assert "forbidden Monitoring Contributor" in result.detail


def test_check_agent_alert_lifecycle_rbac_fails_on_broader_custom_role_actions(
    monkeypatch: pytest.MonkeyPatch, result_factory, tmp_path
) -> None:
    from conftest import make_config

    config = make_config(tmp_path)
    expected_role = "Azure SRE Agent Alert Lifecycle - sre-agent-demo - local"

    def fake_role_assignments(object_id: str, scope: str, **_kw: object):
        if scope.endswith("/resourceGroups/rg-agent"):
            return (["Monitoring Reader"], result_factory(stdout="[]"))
        if object_id == "uami-principal":
            return ([expected_role], result_factory(stdout="[]"))
        return ([], result_factory(stdout="[]"))

    monkeypatch.setattr(verify.azure_cli, "role_assignments", fake_role_assignments)
    monkeypatch.setattr(
        verify.azure_cli,
        "role_definition_by_name",
        lambda name, **_kw: (
            {
                "roleName": name,
                "permissions": [
                    {
                        "actions": [
                            "Microsoft.AlertsManagement/alerts/read",
                            "Microsoft.AlertsManagement/alerts/changestate/action",
                            "Microsoft.Insights/DiagnosticSettings/delete",
                        ]
                    }
                ],
            },
            result_factory(stdout="[]"),
        ),
    )

    result = verify.check_agent_alert_lifecycle_rbac(config, _agent_context())

    assert result.status == Status.FAIL
    assert "DiagnosticSettings" in result.detail


def test_check_agent_admin_rbac_pass(monkeypatch: pytest.MonkeyPatch, result_factory) -> None:
    # UAMI must NOT hold "SRE Agent Administrator" (self-approval risk, see
    # PLAN.md Milestone 5); the deployer must hold it.
    def fake_role_assignments(object_id: str, scope: str, **_kw: object):
        if object_id == "uami-principal":
            return ([], result_factory())
        return (["SRE Agent Administrator"], result_factory(stdout="[]"))

    monkeypatch.setattr(verify.azure_cli, "role_assignments", fake_role_assignments)
    monkeypatch.setattr(
        verify.azure_cli, "signed_in_object_id", lambda **_kw: ("deployer-oid", result_factory())
    )

    result = verify.check_agent_admin_rbac(_agent_context())

    assert result.status == Status.PASS


def test_check_agent_admin_rbac_fails_when_uami_has_role(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    # UAMI holding this role is a self-approval risk (PLAN.md Milestone 5)
    # and must FAIL even though the deployer also correctly holds it.
    monkeypatch.setattr(
        verify.azure_cli,
        "role_assignments",
        lambda object_id, scope, **_kw: (["SRE Agent Administrator"], result_factory(stdout="[]")),
    )
    monkeypatch.setattr(
        verify.azure_cli, "signed_in_object_id", lambda **_kw: ("deployer-oid", result_factory())
    )

    result = verify.check_agent_admin_rbac(_agent_context())

    assert result.status == Status.FAIL
    assert "self-approval" in result.detail


def test_check_agent_admin_rbac_fails_when_deployer_missing_role(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.azure_cli, "role_assignments", lambda object_id, scope, **_kw: ([], result_factory())
    )
    monkeypatch.setattr(
        verify.azure_cli, "signed_in_object_id", lambda **_kw: ("deployer-oid", result_factory())
    )

    result = verify.check_agent_admin_rbac(_agent_context())

    assert result.status == Status.FAIL


def test_check_agent_admin_rbac_passes_when_deployer_unresolvable(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.azure_cli,
        "role_assignments",
        lambda object_id, scope, **_kw: ([], result_factory()),
    )
    monkeypatch.setattr(
        verify.azure_cli,
        "signed_in_object_id",
        lambda **_kw: (None, result_factory(returncode=1, stderr="not a user principal")),
    )

    result = verify.check_agent_admin_rbac(_agent_context())

    assert result.status == Status.PASS
    assert "lookup unavailable" in result.detail


def test_check_agent_connectors_pass(monkeypatch: pytest.MonkeyPatch, result_factory) -> None:
    monkeypatch.setattr(
        verify.agent_azure,
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

    result = verify.check_agent_connectors(_agent_context())

    assert result.status == Status.PASS


def test_check_agent_connectors_warns_when_still_converging(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.agent_azure,
        "connector_list",
        lambda agent_id, **_kw: (
            [
                {"name": "app-insights", "properties": {"provisioningState": "Provisioning"}},
                {"name": "log-analytics", "properties": {"provisioningState": "Succeeded"}},
                {"name": "azure-monitor", "properties": {"provisioningState": "Succeeded"}},
            ],
            result_factory(stdout="[]"),
        ),
    )

    result = verify.check_agent_connectors(_agent_context())

    assert result.status == Status.WARN


def test_check_agent_connectors_fails_when_a_connector_is_missing(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.agent_azure,
        "connector_list",
        lambda agent_id, **_kw: (
            [
                {"name": "log-analytics", "properties": {"provisioningState": "Succeeded"}},
                {"name": "azure-monitor", "properties": {"provisioningState": "Succeeded"}},
            ],
            result_factory(stdout="[]"),
        ),
    )

    result = verify.check_agent_connectors(_agent_context())

    assert result.status == Status.FAIL
    assert "missing" in result.detail


def test_check_agent_connectors_fails_when_a_connector_failed(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.agent_azure,
        "connector_list",
        lambda agent_id, **_kw: (
            [
                {"name": "app-insights", "properties": {"provisioningState": "Failed"}},
                {"name": "log-analytics", "properties": {"provisioningState": "Succeeded"}},
                {"name": "azure-monitor", "properties": {"provisioningState": "Succeeded"}},
            ],
            result_factory(stdout="[]"),
        ),
    )

    result = verify.check_agent_connectors(_agent_context())

    assert result.status == Status.FAIL


def test_check_agent_not_deployed_is_warn_not_fail() -> None:
    result = verify.check_agent_not_deployed()

    assert result.status == Status.WARN


def test_check_agent_incident_platform_pass_when_types_match() -> None:
    expected = agent_content.IncidentPlatformContent(
        name="azure-monitor", platform_type="AzMonitor", display_name="", description=""
    )
    agent_data = {"properties": {"incidentManagementConfiguration": {"type": "AzMonitor"}}}

    result = verify.check_agent_incident_platform(agent_data, expected)

    assert result.status == Status.PASS


def test_check_agent_incident_platform_fails_when_types_differ() -> None:
    expected = agent_content.IncidentPlatformContent(
        name="azure-monitor", platform_type="AzMonitor", display_name="", description=""
    )

    result = verify.check_agent_incident_platform({"properties": {}}, expected)

    assert result.status == Status.FAIL


def test_check_agent_incident_platform_warns_when_no_expected_content() -> None:
    result = verify.check_agent_incident_platform({"properties": {}}, None)

    assert result.status == Status.WARN


def test_get_data_plane_token_for_verify_fails_without_a_token(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_data_plane_token",
        lambda **_kw: (None, result_factory(returncode=1, stderr="AADSTS500011")),
    )

    token, result = verify.get_data_plane_token_for_verify(_agent_context())

    assert token is None
    assert result.status == Status.FAIL


def test_check_agent_skills_pass_when_all_expected_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_extended_items",
        lambda endpoint, token, *, kind: (
            [{"name": "triage-checkout-failures"}],
            verify.agent_dataplane.DataPlaneResult(True, 200, f"GET {kind}"),
        ),
    )
    expected = (
        agent_content.SkillContent(
            name="triage-checkout-failures", description="", tools=(), skill_content=""
        ),
    )

    result = verify.check_agent_skills("https://agent.example", "token", expected)

    assert result.status == Status.PASS


def test_check_agent_skills_fails_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_extended_items",
        lambda endpoint, token, *, kind: (
            [],
            verify.agent_dataplane.DataPlaneResult(True, 200, f"GET {kind}"),
        ),
    )
    expected = (
        agent_content.SkillContent(
            name="triage-checkout-failures", description="", tools=(), skill_content=""
        ),
    )

    result = verify.check_agent_skills("https://agent.example", "token", expected)

    assert result.status == Status.FAIL
    assert "triage-checkout-failures" in result.detail


def test_check_agent_github_repo_pass_when_url_and_domain_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_repos",
        lambda endpoint, token: (
            [
                {
                    "name": "azure-sre-agent",
                    "properties": {"url": "https://github.com/tkubica12/azure-sre-agent"},
                }
            ],
            verify.agent_dataplane.DataPlaneResult(True, 200, "GET repos"),
        ),
    )
    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_github_domains",
        lambda endpoint, token: (
            [{"name": "github.com", "authType": "Pat"}],
            verify.agent_dataplane.DataPlaneResult(True, 200, "GET github/domains"),
        ),
    )

    result = verify.check_agent_github_repo(
        "https://agent.example", "token", "tkubica12/azure-sre-agent"
    )

    assert result.status == Status.PASS


def test_check_agent_github_repo_fails_when_repo_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    empty_result = verify.agent_dataplane.DataPlaneResult(True, 200, "GET repos")
    monkeypatch.setattr(
        verify.agent_dataplane, "get_repos", lambda endpoint, token: ([], empty_result)
    )

    result = verify.check_agent_github_repo(
        "https://agent.example", "token", "tkubica12/azure-sre-agent"
    )

    assert result.status == Status.FAIL


def _subagent(name: str, tools: tuple[str, ...]) -> agent_content.SubagentContent:
    return agent_content.SubagentContent(
        name=name,
        instructions="",
        handoff_description="",
        handoffs=(),
        tools=tools,
        agent_type="Autonomous",
        temperature=0.2,
        enable_skills=True,
        allowed_skills=(),
    )


def test_check_agent_subagents_pass_when_tool_scoping_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_extended_items",
        lambda endpoint, token, *, kind: (
            [
                {
                    "name": "rollback-advisor",
                    "properties": {"tools": ["RunAzCliReadCommands", "RunAzCliWriteCommands"]},
                },
                {
                    "name": "incident-investigator",
                    "properties": {"tools": ["RunAzCliReadCommands"]},
                },
            ],
            verify.agent_dataplane.DataPlaneResult(True, 200, f"GET {kind}"),
        ),
    )
    expected = (
        _subagent("rollback-advisor", ("RunAzCliReadCommands", "RunAzCliWriteCommands")),
        _subagent("incident-investigator", ("RunAzCliReadCommands",)),
    )

    result = verify.check_agent_subagents("https://agent.example", "token", expected)

    assert result.status == Status.PASS
    assert "rollback-advisor" in result.detail


def test_check_agent_subagents_fails_when_write_tool_scope_drifts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `incident-investigator` were ever granted `RunAzCliWriteCommands`
    live (drift from `agent/`), tool-scoping's guarantee would be silently
    broken; this must fail loudly rather than only checking names exist."""

    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_extended_items",
        lambda endpoint, token, *, kind: (
            [
                {
                    "name": "rollback-advisor",
                    "properties": {"tools": ["RunAzCliReadCommands", "RunAzCliWriteCommands"]},
                },
                {
                    "name": "incident-investigator",
                    "properties": {"tools": ["RunAzCliReadCommands", "RunAzCliWriteCommands"]},
                },
            ],
            verify.agent_dataplane.DataPlaneResult(True, 200, f"GET {kind}"),
        ),
    )
    expected = (
        _subagent("rollback-advisor", ("RunAzCliReadCommands", "RunAzCliWriteCommands")),
        _subagent("incident-investigator", ("RunAzCliReadCommands",)),
    )

    result = verify.check_agent_subagents("https://agent.example", "token", expected)

    assert result.status == Status.FAIL
    assert "incident-investigator" in result.detail


def test_check_agent_response_plans_pass_when_agent_mode_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_incident_filters",
        lambda endpoint, token: (
            [{"id": "containerapp-5xx", "agentMode": "Autonomous"}],
            verify.agent_dataplane.DataPlaneResult(True, 200, "GET incidentPlayground/filters"),
        ),
    )
    expected = (
        agent_content.IncidentFilterContent(
            name="containerapp-5xx",
            incident_platform="AzMonitor",
            handling_agent="incident-investigator",
            is_enabled=True,
            priorities=("Sev2",),
            agent_mode="Autonomous",
            deep_investigation_enabled=False,
            max_automated_investigation_attempts=3,
            title_contains="checkout",
        ),
    )

    result = verify.check_agent_response_plans("https://agent.example", "token", expected)

    assert result.status == Status.PASS
    assert "Autonomous" in result.detail


def test_check_agent_response_plans_fails_when_agent_mode_drifts_from_autonomous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live `agentMode` of `Review` must fail: it would (falsely) claim a
    working approval gate that live testing (PLAN.md Milestone 5) proved
    does not engage in this preview build (see SPEC.md section 5 Scene 5)."""

    monkeypatch.setattr(
        verify.agent_dataplane,
        "get_incident_filters",
        lambda endpoint, token: (
            [{"id": "containerapp-5xx", "agentMode": "Review"}],
            verify.agent_dataplane.DataPlaneResult(True, 200, "GET incidentPlayground/filters"),
        ),
    )
    expected = (
        agent_content.IncidentFilterContent(
            name="containerapp-5xx",
            incident_platform="AzMonitor",
            handling_agent="incident-investigator",
            is_enabled=True,
            priorities=("Sev2",),
            agent_mode="Autonomous",
            deep_investigation_enabled=False,
            max_automated_investigation_attempts=3,
            title_contains="checkout",
        ),
    )

    result = verify.check_agent_response_plans("https://agent.example", "token", expected)

    assert result.status == Status.FAIL
    assert "Review" in result.detail
    assert "Autonomous" in result.detail


def test_check_agent_data_plane_content_warns_when_agent_dir_missing(tmp_path) -> None:
    from conftest import make_config

    results = verify.check_agent_data_plane_content(
        make_config(tmp_path), _agent_context(), {"properties": {}}
    )

    assert len(results) == 1
    assert results[0].status == Status.WARN
    assert "content directory not found" in results[0].detail


def test_summarize_exit_code_nonzero_only_on_fail() -> None:
    from labctl.verify import CheckResult

    _table, exit_code_with_fail = summarize(
        [CheckResult("a", Status.PASS, ""), CheckResult("b", Status.FAIL, "")]
    )
    _table, exit_code_without_fail = summarize(
        [CheckResult("a", Status.PASS, ""), CheckResult("b", Status.WARN, "")]
    )

    assert exit_code_with_fail == 1
    assert exit_code_without_fail == 0


def test_run_verify_reports_error_when_not_deployed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from conftest import make_config

    monkeypatch.setattr(
        verify.azure_cli, "ensure_subscription_context", lambda config, **_kw: (object(), None)
    )
    monkeypatch.setattr(verify.ctx, "load_workload_context", lambda config, **_kw: (None, None))

    messages: list[str] = []
    exit_code = verify.run_verify(make_config(tmp_path), echo=messages.append)

    assert exit_code == 1
    assert any("labctl deploy" in m for m in messages)


def test_run_verify_fails_fast_on_subscription_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from conftest import make_config

    monkeypatch.setattr(
        verify.azure_cli,
        "ensure_subscription_context",
        lambda config, **_kw: (None, "subscription mismatch"),
    )
    messages: list[str] = []

    exit_code = verify.run_verify(make_config(tmp_path), echo=messages.append)

    assert exit_code == 2
    assert any("subscription mismatch" in m for m in messages)


def test_run_verify_reports_agent_not_deployed_as_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from conftest import make_config

    monkeypatch.setattr(
        verify.azure_cli, "ensure_subscription_context", lambda config, **_kw: (object(), None)
    )
    monkeypatch.setattr(
        verify.ctx, "load_workload_context", lambda config, **_kw: (_context(), None)
    )
    monkeypatch.setattr(verify.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(
        verify, "http_get", lambda url, **_kw: HttpResult(ok=True, status_code=200, body="{}")
    )
    monkeypatch.setattr(
        verify, "http_post", lambda url, **_kw: HttpResult(ok=True, status_code=200, body="{}")
    )
    monkeypatch.setattr(
        workload_azure,
        "containerapp_show",
        lambda name, rg, **_kw: (
            {"properties": {"configuration": {"activeRevisionsMode": "Multiple"}}},
            None,
        ),
    )
    monkeypatch.setattr(
        workload_azure,
        "containerapp_ingress_traffic_show",
        lambda name, rg, **_kw: ([{"revisionName": "a", "weight": 100}], None),
    )
    monkeypatch.setattr(
        workload_azure,
        "monitor_metric_alert_show",
        lambda name, rg, **_kw: (
            {"enabled": True, "criteria": {"allOf": [{"metricName": "Requests"}]}},
            None,
        ),
    )
    monkeypatch.setattr(
        workload_azure, "log_analytics_query", lambda *a, **k: ([{"Count": 1}], None)
    )
    monkeypatch.setattr(
        workload_azure, "app_insights_query", lambda *a, **k: ([{"Count": 1}], None)
    )

    messages: list[str] = []
    exit_code = verify.run_verify(make_config(tmp_path), echo=messages.append)

    assert exit_code == 0
    assert any("Azure SRE Agent Terraform outputs were not found" in m for m in messages)
