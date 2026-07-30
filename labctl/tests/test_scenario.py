from __future__ import annotations

import pytest
from conftest import make_config, make_result

import labctl.scenario as scenario_mod
from labctl.azure_cli import Account
from labctl.context import WorkloadContext
from labctl.http_client import HttpResult
from labctl.load import LoadResult
from labctl.scenario_definition import (
    AlertDefinition,
    FaultDefinition,
    IncidentDefinition,
    LoadDefinition,
    ScenarioDefinition,
)
from labctl.state import (
    DeploymentState,
    ScenarioState,
    load_scenario_state,
    save_deployment_state,
    save_scenario_state,
)

ACCOUNT = Account(
    subscription_id="sub-1",
    subscription_name="Test Subscription",
    tenant_id="tenant-1",
    user_name="me@example.com",
    user_type="user",
)

BASELINE = "ca-pulsemart-demo--baseline-abc123"
FAULT_REVISION = "ca-pulsemart-demo--fault-x"


def _http(status: int) -> object:
    return lambda url, **_kw: HttpResult(ok=True, status_code=status, body="{}")


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


def _scenario() -> ScenarioDefinition:
    return ScenarioDefinition(
        slug="bad-deployment",
        title="Bad deployment",
        summary="x",
        estimated_duration_minutes=15,
        fault=FaultDefinition(
            env={"PAYMENT_GATEWAY_PROFILE": "legacy-acquirer"}, revision_suffix_prefix="fault"
        ),
        alert=AlertDefinition(
            name="alert-pulsemart-containerapp-5xx",
            expected_time_to_fire_minutes=(1, 6),
            max_wait_seconds=1.0,
            poll_interval_seconds=0.01,
        ),
        load=LoadDefinition(
            request_count=4, concurrency=2, request_timeout_seconds=1.0, min_failures_required=2
        ),
        incident=IncidentDefinition(
            response_plan="containerapp-5xx",
            handling_subagent="incident-investigator",
            title_contains="checkout",
            severity="Sev2",
        ),
        checks={},
    )


def _deployment_state() -> DeploymentState:
    return DeploymentState(
        image_tag="abc123-def456",
        image_ref="crpulsemartdemo.azurecr.io/pulsemart:abc123-def456",
        baseline_revision_suffix="baseline-abc123",
        baseline_revision_name=BASELINE,
        deployed_at="2026-01-01T00:00:00+00:00",
        git_commit="abc123def456",
    )


def _activity_log_events() -> list[dict[str, object]]:
    return [
        {
            "eventTimestamp": "2026-01-01T00:05:00Z",
            "operationName": {"value": "Microsoft.App/containerApps/write"},
            "status": {"value": "Accepted"},
        }
    ]


def _successful_canary(count: int = 6) -> LoadResult:
    return LoadResult(
        total=count, succeeded=count, failed=0, transport_errors=0, duration_seconds=0.2
    )


def _patch_common(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        scenario_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(scenario_mod, "load_scenario_definition", lambda config, slug: _scenario())
    monkeypatch.setattr(
        scenario_mod.ctx,
        "load_workload_context",
        lambda config, **_kw: (_workload_context(), None),
    )
    save_deployment_state(make_config(tmp_path), _deployment_state())


def _deterministic_fault_revision_name() -> str:
    scenario = _scenario()
    deployment = _deployment_state()
    suffix = scenario_mod._fault_revision_suffix(
        "ca-pulsemart-demo", scenario.fault.revision_suffix_prefix, deployment.image_tag, 1700000000
    )
    return f"ca-pulsemart-demo--{suffix}"


def test_fault_revision_suffix_fits_the_real_combined_54_char_limit() -> None:
    """Live-verified 2026-07-29 against `ca-pulsemart-demo`: Azure rejects a
    revision name (container app name + '--' + suffix) over 54 characters
    combined with `ContainerAppInvalidRevisionName`, which is shorter than
    the revision-suffix argument's own documented 63-character limit."""

    suffix = scenario_mod._fault_revision_suffix(
        "ca-pulsemart-demo", "fault", "2d34d4f36555-0fbf79629033", 1785319874
    )
    full_name = f"ca-pulsemart-demo--{suffix}"

    assert len(full_name) <= 54
    # A short suffix that would fit alongside the image tag stays as-is.
    short = scenario_mod._fault_revision_suffix("ca-pulsemart-demo", "fault", "abc", 123)
    assert short == "fault-abc-123"


def test_run_demo_prepare_shifts_traffic_back_to_baseline(monkeypatch, tmp_path) -> None:
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": FAULT_REVISION, "weight": 100}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_revision_list",
        lambda *a, **k: ([{"name": BASELINE}], make_result()),
    )
    traffic_calls: list[dict] = []
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_set",
        lambda name, rg, weights, **k: traffic_calls.append(weights) or make_result(),
    )
    monkeypatch.setattr(scenario_mod, "http_get", _http(200))
    monkeypatch.setattr(scenario_mod, "http_post", _http(200))

    result = scenario_mod.run_demo_prepare(
        make_config(tmp_path), "bad-deployment", echo=lambda _m: None
    )

    assert result.exit_code == 0
    assert traffic_calls == [{BASELINE: 100}]


def test_run_demo_prepare_is_a_noop_when_baseline_already_at_100(monkeypatch, tmp_path) -> None:
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": BASELINE, "weight": 100}], make_result()),
    )
    traffic_calls: list[dict] = []
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_set",
        lambda name, rg, weights, **k: traffic_calls.append(weights) or make_result(),
    )
    monkeypatch.setattr(scenario_mod, "http_get", _http(200))
    monkeypatch.setattr(scenario_mod, "http_post", _http(200))

    result = scenario_mod.run_demo_prepare(
        make_config(tmp_path), "bad-deployment", echo=lambda _m: None
    )

    assert result.exit_code == 0
    assert traffic_calls == []


def test_run_demo_trigger_creates_a_new_revision_and_shifts_traffic(monkeypatch, tmp_path) -> None:
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(scenario_mod.time, "time", lambda: 1700000000.0)
    fault_revision_name = _deterministic_fault_revision_name()

    update_calls: list[dict] = []
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_update_image",
        lambda name, rg, **k: update_calls.append(k) or make_result(),
    )

    # Before the update: only the baseline exists. After: the new fault
    # revision is Provisioned too (mirrors what `az containerapp update`
    # actually does live).
    calls_counter = {"n": 0}

    def revision_list(*a, **k):
        calls_counter["n"] += 1
        baseline_entry = {"name": BASELINE, "properties": {"provisioningState": "Provisioned"}}
        if calls_counter["n"] == 1:
            return [baseline_entry], make_result()
        fault_entry = {
            "name": fault_revision_name,
            "properties": {"provisioningState": "Provisioned"},
        }
        return [baseline_entry, fault_entry], make_result()

    monkeypatch.setattr(scenario_mod.workload_azure, "containerapp_revision_list", revision_list)

    traffic_calls: list[dict] = []
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_set",
        lambda name, rg, weights, **k: traffic_calls.append(weights) or make_result(),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure, "list_fired_alerts", lambda sub, **k: ([], make_result())
    )
    monkeypatch.setattr(scenario_mod, "http_post", _http(500))
    monkeypatch.setattr(
        scenario_mod,
        "generate_checkout_load",
        lambda url, **k: LoadResult(
            total=4, succeeded=0, failed=4, transport_errors=0, duration_seconds=0.1
        ),
    )

    result = scenario_mod.run_demo_trigger(
        make_config(tmp_path), "bad-deployment", echo=lambda _m: None, sleep=lambda _s: None
    )

    assert result.exit_code == 0
    assert len(update_calls) == 1
    assert traffic_calls, "traffic should have been shifted to the new fault revision"
    assert traffic_calls[-1] == {fault_revision_name: 100}
    state = load_scenario_state(make_config(tmp_path), "bad-deployment")
    assert state.fault_active is True
    assert state.fault_revision_name == fault_revision_name


def test_run_demo_trigger_reuses_the_existing_fault_revision_when_already_active(
    monkeypatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)
    config = make_config(tmp_path)
    save_scenario_state(
        config,
        ScenarioState(
            slug="bad-deployment",
            fault_active=True,
            fault_revision_name=FAULT_REVISION,
            baseline_revision_name=BASELINE,
            triggered_at="2026-01-01T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_revision_list",
        lambda *a, **k: (
            [
                {"name": BASELINE, "properties": {"provisioningState": "Provisioned"}},
                {"name": FAULT_REVISION, "properties": {"provisioningState": "Provisioned"}},
            ],
            make_result(),
        ),
    )
    update_calls: list[dict] = []
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_update_image",
        lambda *a, **k: update_calls.append(1) or make_result(),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_set",
        lambda *a, **k: make_result(),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure, "list_fired_alerts", lambda sub, **k: ([], make_result())
    )
    monkeypatch.setattr(scenario_mod, "http_post", _http(500))
    monkeypatch.setattr(
        scenario_mod,
        "generate_checkout_load",
        lambda url, **k: LoadResult(
            total=4, succeeded=0, failed=4, transport_errors=0, duration_seconds=0.1
        ),
    )

    result = scenario_mod.run_demo_trigger(
        config, "bad-deployment", echo=lambda _m: None, sleep=lambda _s: None
    )

    assert result.exit_code == 0
    assert not update_calls, "an already-active fault revision must be reused, not recreated"


def test_run_demo_trigger_fails_when_load_does_not_produce_enough_failures(
    monkeypatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(scenario_mod.time, "time", lambda: 1700000000.0)
    fault_revision_name = _deterministic_fault_revision_name()
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_revision_list",
        lambda *a, **k: (
            [
                {"name": BASELINE, "properties": {"provisioningState": "Provisioned"}},
                {"name": fault_revision_name, "properties": {"provisioningState": "Provisioned"}},
            ],
            make_result(),
        ),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure, "containerapp_update_image", lambda *a, **k: make_result()
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_set",
        lambda *a, **k: make_result(),
    )
    monkeypatch.setattr(scenario_mod, "http_post", _http(500))
    monkeypatch.setattr(
        scenario_mod,
        "generate_checkout_load",
        lambda url, **k: LoadResult(
            total=4, succeeded=4, failed=0, transport_errors=0, duration_seconds=0.1
        ),
    )

    result = scenario_mod.run_demo_trigger(
        make_config(tmp_path), "bad-deployment", echo=lambda _m: None, sleep=lambda _s: None
    )

    assert result.exit_code == 1


def test_run_demo_reset_shifts_traffic_back_and_clears_fault_state(monkeypatch, tmp_path) -> None:
    _patch_common(monkeypatch, tmp_path)
    config = make_config(tmp_path)
    save_scenario_state(
        config,
        ScenarioState(
            slug="bad-deployment",
            fault_active=True,
            fault_revision_name=FAULT_REVISION,
            baseline_revision_name=BASELINE,
            triggered_at="2026-01-01T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": FAULT_REVISION, "weight": 100}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_revision_list",
        lambda *a, **k: ([{"name": BASELINE}], make_result()),
    )
    traffic_calls: list[dict] = []
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_set",
        lambda name, rg, weights, **k: traffic_calls.append(weights) or make_result(),
    )
    monkeypatch.setattr(scenario_mod, "http_get", _http(200))
    monkeypatch.setattr(scenario_mod, "http_post", _http(200))

    result = scenario_mod.run_demo_reset(config, "bad-deployment", echo=lambda _m: None)

    assert result.exit_code == 0
    assert traffic_calls == [{BASELINE: 100}]
    state = load_scenario_state(config, "bad-deployment")
    assert state.fault_active is False


def test_run_demo_verify_reports_fault_phase_checks(monkeypatch, tmp_path) -> None:
    _patch_common(monkeypatch, tmp_path)
    config = make_config(tmp_path)
    monkeypatch.setattr(scenario_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": FAULT_REVISION, "weight": 100}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "list_fired_alerts",
        lambda sub, **k: (
            [{"properties": {"essentials": {"monitorCondition": "Fired"}}}],
            make_result(),
        ),
    )
    monkeypatch.setattr(scenario_mod, "http_post", _http(500))

    result = scenario_mod.run_demo_verify(config, "bad-deployment", echo=lambda _m: None)

    assert result.exit_code == 1


def test_run_demo_verify_reports_recovered_phase_checks(monkeypatch, tmp_path) -> None:
    _patch_common(monkeypatch, tmp_path)
    config = make_config(tmp_path)
    monkeypatch.setattr(scenario_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": BASELINE, "weight": 100}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "app_insights_query",
        lambda *a, **k: ([{"total": 6, "failed": 0}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "activity_log_list",
        lambda *a, **k: (_activity_log_events(), make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "list_fired_alerts",
        lambda *a, **k: (
            [
                {
                    "properties": {
                        "essentials": {
                            "alertRule": "alert-pulsemart-containerapp-5xx",
                            "monitorCondition": "Resolved",
                        }
                    }
                }
            ],
            make_result(),
        ),
    )
    monkeypatch.setattr(
        scenario_mod,
        "generate_checkout_load",
        lambda *a, **k: _successful_canary(),
    )

    result = scenario_mod.run_demo_verify(config, "bad-deployment", echo=lambda _m: None)

    assert result.exit_code == 0


def test_run_demo_verify_fails_when_recovery_telemetry_query_is_unavailable(
    monkeypatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)
    config = make_config(tmp_path)
    monkeypatch.setattr(scenario_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": BASELINE, "weight": 100}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "activity_log_list",
        lambda *a, **k: (_activity_log_events(), make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "app_insights_query",
        lambda *a, **k: (None, make_result(stderr="query failed", returncode=1)),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "list_fired_alerts",
        lambda *a, **k: ([], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod,
        "generate_checkout_load",
        lambda *a, **k: _successful_canary(),
    )

    result = scenario_mod.run_demo_verify(config, "bad-deployment", echo=lambda _m: None)

    assert result.exit_code == 1


def test_run_demo_verify_fails_when_recovery_telemetry_has_residual_alert_threshold_failures(
    monkeypatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)
    config = make_config(tmp_path)
    monkeypatch.setattr(scenario_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": BASELINE, "weight": 100}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "activity_log_list",
        lambda *a, **k: (_activity_log_events(), make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "app_insights_query",
        lambda *a, **k: ([{"total": 8, "failed": 3}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "list_fired_alerts",
        lambda *a, **k: ([], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod,
        "generate_checkout_load",
        lambda *a, **k: _successful_canary(),
    )

    result = scenario_mod.run_demo_verify(config, "bad-deployment", echo=lambda _m: None)

    assert result.exit_code == 1


def test_run_demo_verify_warns_when_alert_resolution_is_still_pending(
    monkeypatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)
    config = make_config(tmp_path)
    output: list[str] = []
    monkeypatch.setattr(scenario_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "containerapp_ingress_traffic_show",
        lambda *a, **k: ([{"revisionName": BASELINE, "weight": 100}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "activity_log_list",
        lambda *a, **k: (_activity_log_events(), make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "app_insights_query",
        lambda *a, **k: ([{"total": 6, "failed": 0}], make_result()),
    )
    monkeypatch.setattr(
        scenario_mod.workload_azure,
        "list_fired_alerts",
        lambda *a, **k: (
            [
                {
                    "properties": {
                        "essentials": {
                            "alertRule": "alert-pulsemart-containerapp-5xx",
                            "monitorCondition": "Fired",
                        }
                    }
                }
            ],
            make_result(),
        ),
    )
    monkeypatch.setattr(
        scenario_mod,
        "generate_checkout_load",
        lambda *a, **k: _successful_canary(),
    )

    result = scenario_mod.run_demo_verify(config, "bad-deployment", echo=output.append)

    assert result.exit_code == 0
    assert "1 warned" in output[-1]
