from __future__ import annotations

import pytest
from conftest import make_config, make_result

import labctl.deploy as deploy_mod
from labctl.azure_cli import Account
from labctl.context import AgentContext, WorkloadContext
from labctl.http_client import HttpResult
from labctl.provision import ProvisionResult

ACCOUNT = Account(
    subscription_id="sub-1",
    subscription_name="Test Subscription",
    tenant_id="tenant-1",
    user_name="me@example.com",
    user_type="user",
)


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
        container_app_id="/subscriptions/x/ca",
        container_app_fqdn="ca-pulsemart-demo.example.azurecontainerapps.io",
        action_group_id="/subscriptions/x/ag",
        metric_alert_id="/subscriptions/x/alert",
        metric_alert_name="alert-pulsemart-checkout-5xx",
    )


def _agent_context() -> AgentContext:
    return AgentContext(
        agent_id="/subscriptions/x/resourceGroups/rg-agent/providers/Microsoft.App/agents/sre-agent-demo",
        agent_name="sre-agent-demo",
        agent_resource_group="rg-agent",
        portal_url="https://sre.azure.com/#/agent/x/rg-agent/sre-agent-demo",
        data_plane_endpoint="https://sre-agent-demo.swedencentral.azuresre.ai",
        uami_id="/subscriptions/x/resourceGroups/rg-agent/.../sre-agent-demo-uami",
        uami_principal_id="uami-principal",
        uami_client_id="uami-client",
        system_identity_principal_id="system-principal",
        agent_app_insights_id="/subscriptions/x/appi-agent",
        agent_app_insights_app_id="appi-agent-guid",
        agent_log_analytics_id="/subscriptions/x/law-agent",
        agent_log_analytics_workspace_id="law-agent-guid",
        connector_names=("app-insights", "log-analytics", "azure-monitor"),
    )


def _patch_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path, *, existing_tags=None, revision_exists=False
):
    monkeypatch.setattr(
        deploy_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(deploy_mod.terraform_cli, "init_backend", lambda cwd: make_result())
    monkeypatch.setattr(deploy_mod.terraform_cli, "plan", lambda cwd, **kw: make_result())
    monkeypatch.setattr(
        deploy_mod.terraform_cli, "show_plan_json", lambda cwd, **kw: make_result(stdout="{}")
    )
    monkeypatch.setattr(deploy_mod.terraform_cli, "apply", lambda cwd, **kw: make_result())
    monkeypatch.setattr(
        deploy_mod.ctx, "load_workload_context", lambda config, **_kw: (_context(), None)
    )
    monkeypatch.setattr(
        deploy_mod.ctx, "load_agent_context", lambda config, **_kw: (_agent_context(), None)
    )
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            {"properties": {"incidentManagementConfiguration": {"type": "AzMonitor"}}},
            make_result(),
        ),
    )
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "set_incident_platform",
        lambda agent_id, **_kw: ({}, make_result()),
    )
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "wait_for_agent_provisioned",
        lambda agent_id, **_kw: ("Succeeded", {}, make_result()),
    )
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "wait_for_connector_provisioned",
        lambda agent_id, name, **_kw: ("Succeeded", {}, make_result()),
    )
    monkeypatch.setattr(
        deploy_mod.image_mod, "compute_image_tag", lambda repo_root, app_dir: "abc123-def456"
    )
    monkeypatch.setattr(deploy_mod.image_mod, "git_commit_short", lambda repo_root: "abc123def456")
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "acr_repository_show_tags",
        lambda *a, **k: (existing_tags or [], make_result()),
    )
    monkeypatch.setattr(
        deploy_mod.workload_azure, "containerapp_revision_list", lambda *a, **k: ([], make_result())
    )
    if revision_exists:
        monkeypatch.setattr(
            deploy_mod.workload_azure,
            "containerapp_revision_list",
            lambda *a, **k: (
                [{"name": "ca-pulsemart-demo--baseline-abc123-def456"}],
                make_result(),
            ),
        )
    monkeypatch.setattr(deploy_mod.workload_azure, "acr_build", lambda *a, **k: make_result())
    monkeypatch.setattr(
        deploy_mod.workload_azure, "containerapp_update_image", lambda *a, **k: make_result()
    )
    monkeypatch.setattr(
        deploy_mod.workload_azure, "containerapp_ingress_update", lambda *a, **k: make_result()
    )
    monkeypatch.setattr(
        deploy_mod.workload_azure, "containerapp_ingress_traffic_set", lambda *a, **k: make_result()
    )
    monkeypatch.setattr(
        deploy_mod, "http_get", lambda url, **_kw: HttpResult(ok=True, status_code=200, body="{}")
    )
    monkeypatch.setattr(
        deploy_mod, "http_post", lambda url, **_kw: HttpResult(ok=True, status_code=200, body="{}")
    )
    monkeypatch.setattr(deploy_mod, "run_verify", lambda config, **_kw: 0)
    monkeypatch.setattr(deploy_mod, "run_provision", lambda config, **_kw: ProvisionResult(0))

    # Make compute_image_tag not touch the real filesystem.
    (tmp_path / "app").mkdir(exist_ok=True)


def test_deploy_fails_fast_when_not_logged_in(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        deploy_mod,
        "ensure_subscription_context",
        lambda config, **_kw: (None, "not logged in"),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 2


def test_deploy_plan_only_never_applies(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        deploy_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(deploy_mod.terraform_cli, "init_backend", lambda cwd: make_result())
    monkeypatch.setattr(deploy_mod.terraform_cli, "plan", lambda cwd, **kw: make_result())
    monkeypatch.setattr(
        deploy_mod.terraform_cli, "show_plan_json", lambda cwd, **kw: make_result(stdout="{}")
    )
    apply_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.terraform_cli, "apply", lambda cwd, **kw: apply_calls.append(1) or make_result()
    )

    result = deploy_mod.run_deploy(
        make_config(tmp_path), yes=True, plan_only=True, echo=lambda _m: None
    )

    assert result.exit_code == 0
    assert not apply_calls


def test_deploy_requires_yes_to_apply(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        deploy_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(deploy_mod.terraform_cli, "init_backend", lambda cwd: make_result())
    monkeypatch.setattr(deploy_mod.terraform_cli, "plan", lambda cwd, **kw: make_result())
    monkeypatch.setattr(
        deploy_mod.terraform_cli, "show_plan_json", lambda cwd, **kw: make_result(stdout="{}")
    )
    apply_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.terraform_cli, "apply", lambda cwd, **kw: apply_calls.append(1) or make_result()
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=False, echo=lambda _m: None)

    assert result.exit_code == 2
    assert not apply_calls


def test_deploy_terraform_apply_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        deploy_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(deploy_mod.terraform_cli, "init_backend", lambda cwd: make_result())
    monkeypatch.setattr(deploy_mod.terraform_cli, "plan", lambda cwd, **kw: make_result())
    monkeypatch.setattr(
        deploy_mod.terraform_cli, "show_plan_json", lambda cwd, **kw: make_result(stdout="{}")
    )
    monkeypatch.setattr(
        deploy_mod.terraform_cli,
        "apply",
        lambda cwd, **kw: make_result(returncode=1, stderr="quota exceeded"),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 1


def test_deploy_happy_path_builds_and_updates_and_verifies(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    build_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "acr_build",
        lambda *a, **k: build_calls.append(1) or make_result(),
    )
    update_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "containerapp_update_image",
        lambda *a, **k: update_calls.append(1) or make_result(),
    )
    verify_calls: list[object] = []
    monkeypatch.setattr(deploy_mod, "run_verify", lambda config, **_kw: verify_calls.append(1) or 0)

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 0
    assert build_calls == [1]
    assert update_calls == [1]
    assert verify_calls == [1]
    assert (tmp_path / ".state" / "deployment.json").is_file()


def test_deploy_skips_build_when_image_tag_already_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path, existing_tags=["abc123-def456"])
    build_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "acr_build",
        lambda *a, **k: build_calls.append(1) or make_result(),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 0
    assert not build_calls


def test_deploy_skips_update_when_revision_already_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path, revision_exists=True)
    update_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "containerapp_update_image",
        lambda *a, **k: update_calls.append(1) or make_result(),
    )
    traffic_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "containerapp_ingress_traffic_set",
        lambda *a, **k: traffic_calls.append(1) or make_result(),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 0
    assert not update_calls
    # Traffic is still (re-)pinned to the baseline revision even when the
    # revision itself already existed, so reruns stay idempotent end-to-end.
    assert traffic_calls == [1]


def test_deploy_acr_build_failure_stops_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "acr_build",
        lambda *a, **k: make_result(returncode=1, stderr="build failed"),
    )
    update_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "containerapp_update_image",
        lambda *a, **k: update_calls.append(1) or make_result(),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 1
    assert not update_calls


def test_deploy_skip_build_flag_bypasses_acr(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    build_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod.workload_azure,
        "acr_build",
        lambda *a, **k: build_calls.append(1) or make_result(),
    )

    result = deploy_mod.run_deploy(
        make_config(tmp_path), yes=True, skip_build=True, echo=lambda _m: None
    )

    assert result.exit_code == 0
    assert not build_calls


def test_deploy_reconciles_incident_platform_when_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """B1 fix: if `properties.incidentManagementConfiguration` is not
    already the desired value after `terraform apply` (e.g. an unrelated
    apply reset it), `labctl deploy` PATCHes it back itself."""

    _patch_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            {"properties": {"incidentManagementConfiguration": None}},
            make_result(),
        ),
    )
    patch_calls: list[str] = []
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "set_incident_platform",
        lambda agent_id, **_kw: patch_calls.append("patched") or ({}, make_result()),
    )
    messages: list[str] = []

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 0
    assert patch_calls == ["patched"]
    assert any("ARM PATCH incidentManagementConfiguration -> AzMonitor" in m for m in messages)


def test_deploy_fails_when_incident_platform_patch_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            {"properties": {"incidentManagementConfiguration": None}},
            make_result(),
        ),
    )
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "set_incident_platform",
        lambda agent_id, **_kw: (None, make_result(returncode=1, stderr="denied")),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 1


def test_deploy_tolerates_expected_connector_timeout_and_continues(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    apply_calls: list[int] = []

    def _apply_first_call_times_out(cwd, **kw):
        apply_calls.append(1)
        if len(apply_calls) == 1:
            return make_result(
                returncode=1,
                stderr='module.sre_agent.azapi_resource.connector["app-insights"]: '
                "context deadline exceeded",
            )
        # The reconciliation re-apply (M3 fix) succeeds once Azure has
        # finished provisioning the connector in the background.
        return make_result()

    monkeypatch.setattr(deploy_mod.terraform_cli, "apply", _apply_first_call_times_out)
    messages: list[str] = []

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 0
    assert any("documented, expected behavior" in m for m in messages)
    assert any("final plan is a no-op" in m for m in messages)
    assert len(apply_calls) == 2


def test_deploy_fails_on_apply_error_unrelated_to_connectors(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        deploy_mod.terraform_cli,
        "apply",
        lambda cwd, **kw: make_result(returncode=1, stderr="quota exceeded"),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 1


def test_deploy_fails_when_agent_provisioning_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "wait_for_agent_provisioned",
        lambda agent_id, **_kw: ("Failed", {}, make_result(returncode=1, stderr="agent failed")),
    )
    messages: list[str] = []

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 1
    assert any("provisioningState=Failed" in m for m in messages)


def test_deploy_fails_when_a_connector_never_reaches_terminal_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        deploy_mod.agent_azure,
        "wait_for_connector_provisioned",
        lambda agent_id, name, **_kw: ("Provisioning", {}, make_result()),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 1


def test_deploy_fails_when_agent_outputs_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(deploy_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 1


def test_deploy_calls_provision_after_the_image_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Milestone 5's first task: `labctl deploy` calls `labctl provision`
    (idempotent) after the Container App update, matching SPEC.md section
    11's documented sequence, instead of requiring a separate manual step."""

    _patch_happy_path(monkeypatch, tmp_path)
    provision_calls: list[object] = []
    monkeypatch.setattr(
        deploy_mod,
        "run_provision",
        lambda config, **_kw: provision_calls.append(1) or ProvisionResult(0),
    )

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=lambda _m: None)

    assert result.exit_code == 0
    assert provision_calls == [1]


def test_deploy_reports_failure_when_provision_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(deploy_mod, "run_provision", lambda config, **_kw: ProvisionResult(1))
    messages: list[str] = []

    result = deploy_mod.run_deploy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 1
    assert any("labctl provision` reported failures" in m for m in messages)
