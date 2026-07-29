from __future__ import annotations

import pytest
from conftest import make_config, make_result

import labctl.destroy as destroy_mod
from labctl.azure_cli import Account, ResourceSummary
from labctl.context import ResourceGroupIds
from labctl.state import DEPLOYMENT_STATE_FILENAME, DeploymentState, save_deployment_state

ACCOUNT = Account(
    subscription_id="sub-1",
    subscription_name="Test Subscription",
    tenant_id="tenant-1",
    user_name="me@example.com",
    user_type="user",
)

_EXPECTED_TAGS = {
    "repository": "azure-sre-agent",
    "environment": "demo",
    "owner": "me",
    "deployment_id": "local",
}

RG_JSON_MATCHING_OWNER = {
    "id": "/subscriptions/sub-1/resourceGroups/rg-agent",
    "tags": _EXPECTED_TAGS,
}
RG_JSON_MISMATCHED_OWNER = {
    "id": "/subscriptions/sub-1/resourceGroups/rg-agent",
    "tags": {**_EXPECTED_TAGS, "owner": "someone-else"},
}


def _not_found_result() -> object:
    return make_result(returncode=1, stderr="ResourceGroupNotFound: could not be found.")


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    """Baseline: logged in as the pinned subscription, neither resource
    group exists yet (so ownership checks pass through as "nothing to
    destroy"), and Terraform outputs are unavailable (so the resource-group
    ID check is skipped, not failed)."""

    monkeypatch.setattr(
        destroy_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(
        destroy_mod, "resource_group_show", lambda name, **_kw: (None, _not_found_result())
    )
    monkeypatch.setattr(destroy_mod, "resource_list", lambda name, **_kw: ([], make_result()))
    monkeypatch.setattr(
        destroy_mod.ctx, "load_resource_group_ids", lambda config, **_kw: (None, None)
    )
    monkeypatch.setattr(destroy_mod.terraform_cli, "init_backend", lambda cwd: make_result())


def _patch_terraform_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(destroy_mod.terraform_cli, "init_backend", lambda cwd: make_result())
    monkeypatch.setattr(
        destroy_mod.terraform_cli,
        "plan",
        lambda cwd, **kw: make_result(stdout="Plan: 0 to add, 0 to change, 12 to destroy."),
    )
    monkeypatch.setattr(destroy_mod.terraform_cli, "apply", lambda cwd, **kw: make_result())
    monkeypatch.setattr(destroy_mod.terraform_cli, "state_list", lambda cwd: make_result(stdout=""))
    monkeypatch.setattr(destroy_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))


def test_destroy_fails_fast_on_subscription_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        destroy_mod,
        "ensure_subscription_context",
        lambda config, **_kw: (None, "subscription mismatch"),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 2
    assert any("subscription mismatch" in m for m in messages)


def test_destroy_refuses_on_placeholder_deployment_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from labctl.config import TagsConfig

    _patch_common(monkeypatch)
    config = make_config(
        tmp_path,
        tags=TagsConfig(
            repository="azure-sre-agent",
            environment="demo",
            owner="me",
            deployment_id="change-me",
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(config, yes=True, echo=messages.append)

    assert result.exit_code == 2
    assert any("placeholder" in m for m in messages)


def test_destroy_refuses_on_placeholder_owner(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from labctl.config import TagsConfig

    _patch_common(monkeypatch)
    config = make_config(
        tmp_path,
        tags=TagsConfig(
            repository="azure-sre-agent",
            environment="demo",
            owner="change-me",
            deployment_id="local",
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(config, yes=True, echo=messages.append)

    assert result.exit_code == 2
    assert any("tags.owner" in m and "placeholder" in m for m in messages)


def test_destroy_refuses_on_ownership_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        destroy_mod,
        "resource_group_show",
        lambda name, **_kw: (RG_JSON_MISMATCHED_OWNER, make_result()),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 2
    assert any("tag mismatch" in m for m in messages)


def test_destroy_refuses_when_resource_group_id_does_not_match_terraform_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        destroy_mod,
        "resource_group_show",
        lambda name, **_kw: (RG_JSON_MATCHING_OWNER, make_result()),
    )
    monkeypatch.setattr(
        destroy_mod.ctx,
        "load_resource_group_ids",
        lambda config, **_kw: (
            ResourceGroupIds(
                agent_resource_group_id="/subscriptions/sub-1/resourceGroups/rg-agent-DIFFERENT",
                workload_resource_group_id="/subscriptions/sub-1/resourceGroups/rg-workload-DIFFERENT",
            ),
            None,
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 2
    assert any("does not match Terraform state" in m for m in messages)


def test_destroy_refuses_when_existing_terraform_state_outputs_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch)
    config = make_config(tmp_path)
    config.terraform_state_path().mkdir(parents=True)
    (config.terraform_state_path() / "demo.tfstate").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        destroy_mod.ctx,
        "load_resource_group_ids",
        lambda config, **_kw: (None, make_result(returncode=1, stderr="output failed")),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(config, yes=True, echo=messages.append)

    assert result.exit_code == 2
    assert any("existing Terraform state outputs" in m for m in messages)


def test_destroy_refuses_on_unrecognized_child_resource(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        destroy_mod,
        "resource_group_show",
        lambda name, **_kw: (RG_JSON_MATCHING_OWNER, make_result()),
    )
    monkeypatch.setattr(
        destroy_mod,
        "resource_list",
        lambda name, **_kw: (
            [
                ResourceSummary(
                    id=(
                        "/subscriptions/sub-1/resourceGroups/rg-agent/providers/"
                        "Microsoft.Storage/storageAccounts/someoneelse"
                    ),
                    type="Microsoft.Storage/storageAccounts",
                    tags={},
                )
            ],
            make_result(),
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 2
    assert any("UNRECOGNIZED" in m for m in messages)


def test_destroy_allow_unrecognized_resources_override_proceeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    monkeypatch.setattr(
        destroy_mod,
        "resource_group_show",
        lambda name, **_kw: (RG_JSON_MATCHING_OWNER, make_result()),
    )
    monkeypatch.setattr(
        destroy_mod,
        "resource_list",
        lambda name, **_kw: (
            (
                [
                    ResourceSummary(
                        id="/subscriptions/sub-1/resourceGroups/rg-agent/providers/x/y",
                        type="x/y",
                        tags={},
                    )
                ]
                if name == "rg-agent"
                else []
            ),
            make_result(),
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(
        make_config(tmp_path),
        yes=True,
        plan_only=True,
        allow_unrecognized_resources=True,
        confirm_unrecognized_resource_group=lambda name: name == "rg-agent",
        echo=messages.append,
    )

    assert result.exit_code == 0
    assert any("explicit operator override" in m for m in messages)


def test_destroy_allow_unrecognized_resources_requires_typed_resource_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    monkeypatch.setattr(
        destroy_mod,
        "resource_group_show",
        lambda name, **_kw: (RG_JSON_MATCHING_OWNER, make_result()),
    )
    monkeypatch.setattr(
        destroy_mod,
        "resource_list",
        lambda name, **_kw: (
            (
                [
                    ResourceSummary(
                        id="/subscriptions/sub-1/resourceGroups/rg-agent/providers/x/y",
                        type="x/y",
                        tags={},
                    )
                ]
                if name == "rg-agent"
                else []
            ),
            make_result(),
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(
        make_config(tmp_path),
        yes=True,
        plan_only=True,
        allow_unrecognized_resources=True,
        confirm_unrecognized_resource_group=lambda name: False,
        echo=messages.append,
    )

    assert result.exit_code == 2
    assert any("requires typing" in m for m in messages)


def test_destroy_recognizes_child_resources_of_owned_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A resource with no tags of its own (e.g. an Azure SRE Agent connector)
    is still recognized as owned when it is a child of a resource that IS
    tagged correctly (see B3)."""

    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    agent_id = (
        "/subscriptions/sub-1/resourceGroups/rg-agent/providers/Microsoft.App/agents/sre-agent-demo"
    )
    monkeypatch.setattr(
        destroy_mod,
        "resource_group_show",
        lambda name, **_kw: (RG_JSON_MATCHING_OWNER, make_result()),
    )
    monkeypatch.setattr(
        destroy_mod,
        "resource_list",
        lambda name, **_kw: (
            [
                ResourceSummary(id=agent_id, type="Microsoft.App/agents", tags=_EXPECTED_TAGS),
                ResourceSummary(
                    id=f"{agent_id}/connectors/app-insights",
                    type="Microsoft.App/agents/connectors",
                    tags={},
                ),
            ],
            make_result(),
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(
        make_config(tmp_path), yes=True, plan_only=True, echo=messages.append
    )

    assert result.exit_code == 0
    assert not any("UNRECOGNIZED" in m for m in messages)


def test_destroy_recognizes_app_insights_failure_anomalies_smart_detector(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Azure automatically creates one untagged "Failure Anomalies" Smart
    Detector alert rule per Application Insights component (live-observed
    2026-07-29 in both owned resource groups); it must be recognized as a
    platform companion resource, not block a routine destroy (see B3)."""

    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    rg_id = "/subscriptions/sub-1/resourceGroups/rg-agent"
    appi_id = f"{rg_id}/providers/microsoft.insights/components/appi-sre-agent-demo"
    monkeypatch.setattr(
        destroy_mod,
        "resource_group_show",
        lambda name, **_kw: (RG_JSON_MATCHING_OWNER, make_result()),
    )
    monkeypatch.setattr(
        destroy_mod,
        "resource_list",
        lambda name, **_kw: (
            [
                ResourceSummary(
                    id=appi_id, type="microsoft.insights/components", tags=_EXPECTED_TAGS
                ),
                ResourceSummary(
                    id=f"{rg_id}/providers/microsoft.alertsmanagement/smartDetectorAlertRules/"
                    "Failure Anomalies - appi-sre-agent-demo",
                    type="microsoft.alertsmanagement/smartDetectorAlertRules",
                    tags={},
                ),
            ],
            make_result(),
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(
        make_config(tmp_path), yes=True, plan_only=True, echo=messages.append
    )

    assert result.exit_code == 0
    assert not any("UNRECOGNIZED" in m for m in messages)


def test_destroy_refuses_unrelated_smart_detector_alert_for_unowned_app_insights(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A Smart Detector alert naming an Application Insights component this
    deployment does NOT own must still block the destroy (see B3): the
    platform-companion recognition is name-scoped, not a blanket
    type-based allowlist."""

    _patch_common(monkeypatch)
    rg_id = "/subscriptions/sub-1/resourceGroups/rg-agent"
    monkeypatch.setattr(
        destroy_mod,
        "resource_group_show",
        lambda name, **_kw: (RG_JSON_MATCHING_OWNER, make_result()),
    )
    monkeypatch.setattr(
        destroy_mod,
        "resource_list",
        lambda name, **_kw: (
            [
                ResourceSummary(
                    id=f"{rg_id}/providers/microsoft.alertsmanagement/smartDetectorAlertRules/"
                    "Failure Anomalies - someone-elses-app-insights",
                    type="microsoft.alertsmanagement/smartDetectorAlertRules",
                    tags={},
                ),
            ],
            make_result(),
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 2
    assert any("UNRECOGNIZED" in m for m in messages)


def test_destroy_requires_yes_to_apply(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    apply_calls: list[object] = []
    monkeypatch.setattr(
        destroy_mod.terraform_cli,
        "apply",
        lambda cwd, **kw: apply_calls.append(kw) or make_result(),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(make_config(tmp_path), yes=False, echo=messages.append)

    assert result.exit_code == 2
    assert not apply_calls
    assert any("--yes" in m for m in messages)


def test_destroy_plan_only_never_destroys(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    apply_calls: list[object] = []
    monkeypatch.setattr(
        destroy_mod.terraform_cli,
        "apply",
        lambda cwd, **kw: apply_calls.append(kw) or make_result(),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(
        make_config(tmp_path), yes=True, plan_only=True, echo=messages.append
    )

    assert result.exit_code == 0
    assert not apply_calls


def test_destroy_applies_the_reviewed_saved_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    config = make_config(tmp_path)
    apply_kwargs: list[dict[str, object]] = []
    monkeypatch.setattr(
        destroy_mod.terraform_cli,
        "apply",
        lambda cwd, **kw: apply_kwargs.append(kw) or make_result(),
    )

    result = destroy_mod.run_destroy(config, yes=True, echo=lambda _m: None)

    assert result.exit_code == 0
    assert apply_kwargs == [{"plan_file": config.terraform_state_path() / "destroy-demo.tfplan"}]


def test_destroy_succeeds_and_cleans_up_local_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    config = make_config(tmp_path)
    save_deployment_state(config, DeploymentState(image_tag="abc123-def456"))
    assert (tmp_path / ".state" / DEPLOYMENT_STATE_FILENAME).is_file()
    messages: list[str] = []

    result = destroy_mod.run_destroy(config, yes=True, echo=messages.append)

    assert result.exit_code == 0
    assert any("confirmed removed" in m for m in messages)
    assert not (tmp_path / ".state" / DEPLOYMENT_STATE_FILENAME).is_file()


def test_destroy_reports_failure_and_remaining_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(destroy_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(destroy_mod.terraform_cli, "init_backend", lambda cwd: make_result())
    monkeypatch.setattr(
        destroy_mod.terraform_cli,
        "plan",
        lambda cwd, **kw: make_result(stdout="Plan: 12 to destroy."),
    )
    monkeypatch.setattr(
        destroy_mod.terraform_cli,
        "apply",
        lambda cwd, **kw: make_result(returncode=1, stderr="deletion conflict"),
    )
    monkeypatch.setattr(
        destroy_mod.terraform_cli,
        "state_list",
        lambda cwd: make_result(stdout="module.container_app.azurerm_container_app.this"),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 1
    assert any("still present in terraform state" in m.lower() for m in messages)


def test_destroy_warns_about_agent_cost_when_agent_is_deployed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from labctl.context import AgentContext

    _patch_common(monkeypatch)
    _patch_terraform_success(monkeypatch)
    monkeypatch.setattr(
        destroy_mod.ctx,
        "load_agent_context",
        lambda config, **_kw: (
            AgentContext(
                agent_id="/subscriptions/x/resourceGroups/rg-agent/.../sre-agent-demo",
                agent_name="sre-agent-demo",
                agent_resource_group="rg-agent",
                portal_url="https://sre.azure.com/#/agent/x/rg-agent/sre-agent-demo",
                data_plane_endpoint="https://sre-agent-demo.swedencentral.azuresre.ai",
                uami_id="/subscriptions/x/.../sre-agent-demo-uami",
                uami_principal_id="uami-principal",
                uami_client_id="uami-client",
                system_identity_principal_id="system-principal",
                agent_app_insights_id="/subscriptions/x/appi-agent",
                agent_app_insights_app_id="appi-agent-guid",
                agent_log_analytics_id="/subscriptions/x/law-agent",
                agent_log_analytics_workspace_id="law-agent-guid",
                connector_names=("app-insights", "log-analytics", "azure-monitor"),
            ),
            None,
        ),
    )
    messages: list[str] = []

    result = destroy_mod.run_destroy(make_config(tmp_path), yes=True, echo=messages.append)

    assert result.exit_code == 0
    assert any("always-on Azure Agent Unit cost" in m for m in messages)
