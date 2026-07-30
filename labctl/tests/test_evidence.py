from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_config, make_result

import labctl.evidence as evidence_mod
from labctl.azure_cli import Account
from labctl.context import AgentContext, WorkloadContext

ACCOUNT = Account(
    subscription_id="sub-1",
    subscription_name="Test Subscription",
    tenant_id="tenant-1",
    user_name="me@example.com",
    user_type="user",
)

CONNECTION_STRING = (
    "InstrumentationKey=00000000-0000-0000-0000-00000000aaaa;"
    "IngestionEndpoint=https://swedencentral-0.in.applicationinsights.azure.com/;"
    "ApplicationId=00000000-0000-0000-0000-00000000bbbb"
)


def _workload_context() -> WorkloadContext:
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
        container_app_id="/subscriptions/x/ca",
        container_app_fqdn="ca-pulsemart-demo.example.azurecontainerapps.io",
        action_group_id="/subscriptions/x/ag",
        metric_alert_id="/subscriptions/x/alert",
        metric_alert_name="alert-pulsemart-containerapp-5xx",
    )


def _agent_context() -> AgentContext:
    return AgentContext(
        agent_id="/subscriptions/x/resourceGroups/rg-agent/providers/Microsoft.App/agents/sre-agent-demo",
        agent_name="sre-agent-demo",
        agent_resource_group="rg-agent",
        portal_url="https://sre.azure.com/#/agent/x/rg-agent/sre-agent-demo",
        data_plane_endpoint="https://sre-agent-demo.swedencentral.azuresre.ai",
        uami_id="/subscriptions/x/resourceGroups/rg-agent/.../uami",
        uami_principal_id="uami-principal",
        uami_client_id="uami-client",
        system_identity_principal_id="system-principal",
        agent_app_insights_id="/subscriptions/x/appi-agent",
        agent_app_insights_app_id="appi-agent-guid",
        agent_log_analytics_id="/subscriptions/x/law-agent",
        agent_log_analytics_workspace_id="law-agent-guid",
        connector_names=("app-insights", "log-analytics", "azure-monitor"),
    )


def test_redact_recursive_redacts_nested_string_leaves() -> None:
    data = {
        "revisions": [
            {"name": "r1", "template": {"env": [{"name": "X", "value": CONNECTION_STRING}]}}
        ],
        "plain": "no secret here",
    }

    redacted = evidence_mod._redact_recursive(data)

    serialized = json.dumps(redacted)
    assert "InstrumentationKey=" not in serialized
    assert "00000000-0000-0000-0000-00000000aaaa" not in serialized
    assert "plain" in redacted and redacted["plain"] == "no secret here"


def test_write_json_never_writes_a_connection_string_to_disk(tmp_path: Path) -> None:
    target = tmp_path / "out.json"

    evidence_mod._write_json(target, {"secret": CONNECTION_STRING})

    written = target.read_text(encoding="utf-8")
    assert "InstrumentationKey=" not in written
    assert "***REDACTED***" in written


def _patch_common(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        evidence_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(
        evidence_mod.ctx, "load_workload_context", lambda config, **_kw: (_workload_context(), None)
    )
    monkeypatch.setattr(
        evidence_mod.ctx, "load_agent_context", lambda config, **_kw: (_agent_context(), None)
    )
    monkeypatch.setattr(
        evidence_mod.workload_azure,
        "containerapp_revision_list",
        lambda *a, **k: ([{"name": "r1"}], make_result()),
    )
    monkeypatch.setattr(
        evidence_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": "r1", "weight": 100}], make_result()),
    )
    monkeypatch.setattr(
        evidence_mod.workload_azure,
        "monitor_metric_alert_show",
        lambda *a, **k: ({}, make_result()),
    )
    monkeypatch.setattr(
        evidence_mod.workload_azure, "list_fired_alerts", lambda *a, **k: ([], make_result())
    )
    monkeypatch.setattr(
        evidence_mod.workload_azure, "app_insights_query", lambda *a, **k: ([], make_result())
    )
    monkeypatch.setattr(
        evidence_mod.workload_azure, "log_analytics_query", lambda *a, **k: ([], make_result())
    )
    monkeypatch.setattr(evidence_mod, "list_scenario_slugs", lambda config: [])
    monkeypatch.setattr(
        evidence_mod.agent_dataplane, "get_data_plane_token", lambda **_kw: (None, make_result())
    )


def test_run_evidence_collect_writes_a_manifest_and_reports_the_output_dir(
    monkeypatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)

    result = evidence_mod.run_evidence_collect(make_config(tmp_path), echo=lambda _m: None)

    assert result.exit_code == 0
    assert result.output_dir is not None
    assert (result.output_dir / "manifest.json").is_file()
    assert (result.output_dir / "container-app-revisions.json").is_file()


def test_run_evidence_collect_requires_workload_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        evidence_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(
        evidence_mod.ctx, "load_workload_context", lambda config, **_kw: (None, None)
    )
    monkeypatch.setattr(evidence_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))

    result = evidence_mod.run_evidence_collect(make_config(tmp_path), echo=lambda _m: None)

    assert result.exit_code == 1


def test_run_evidence_collect_skips_invalid_thread_id(monkeypatch, tmp_path) -> None:
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(evidence_mod, "list_scenario_slugs", lambda config: ["bad-deployment"])
    monkeypatch.setattr(
        evidence_mod,
        "load_scenario_definition",
        lambda config, slug: type(
            "Scenario",
            (),
            {"incident": type("Incident", (), {"title_contains": "Checkout failures"})()},
        )(),
    )
    monkeypatch.setattr(
        evidence_mod.agent_dataplane,
        "get_data_plane_token",
        lambda **_kw: ("token", make_result(stdout="token")),
    )
    monkeypatch.setattr(
        evidence_mod.agent_dataplane,
        "list_threads",
        lambda *a, **k: (
            [{"id": "..\\escape", "title": "Checkout failures detected"}],
            make_result(stdout="[]"),
        ),
    )
    get_messages_calls: list[object] = []
    monkeypatch.setattr(
        evidence_mod.agent_dataplane,
        "get_thread_messages",
        lambda *a, **k: get_messages_calls.append(a) or ([], make_result(stdout="[]")),
    )
    messages: list[str] = []

    result = evidence_mod.run_evidence_collect(make_config(tmp_path), echo=messages.append)

    assert result.exit_code == 0
    assert result.output_dir is not None
    assert not get_messages_calls
    assert not list(result.output_dir.glob("agent-thread-*messages.json"))
    assert any("invalid id" in m for m in messages)
