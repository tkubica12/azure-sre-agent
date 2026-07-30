from __future__ import annotations

import labctl.workload_azure as workload_azure

KQL_LIST_JSON = """
[
  {"Count": 42, "Level": "Error"}
]
"""

KQL_TABLE_JSON = """
{
  "tables": [
    {
      "name": "PrimaryResult",
      "columns": [{"name": "Count"}, {"name": "Level"}],
      "rows": [[42, "Error"]]
    }
  ]
}
"""


def _capturing_runner(captured: list[list[str]], result_factory, *, stdout: str = "{}"):
    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(stdout=stdout, returncode=0)

    return runner


def test_acr_build_passes_registry_platform_tags_and_source(result_factory) -> None:
    captured: list[list[str]] = []
    runner = _capturing_runner(captured, result_factory)

    workload_azure.acr_build(
        "crpulsemartdemo123456",
        ["pulsemart:abc123-def456", "pulsemart:latest"],
        "/repo/app",
        runner=runner,
    )

    args = captured[0]
    assert args[:4] == ["acr", "build", "--registry", "crpulsemartdemo123456"]
    assert "--platform" in args and "linux" in args
    assert "--no-logs" in args
    assert args.count("--image") == 2
    assert "pulsemart:abc123-def456" in args
    assert "pulsemart:latest" in args
    assert args[-1] == "/repo/app"


def test_acr_repository_show_tags_returns_empty_list_on_failure(result_factory) -> None:
    def runner(args, **_kwargs):
        return result_factory(stdout="", stderr="repository not found", returncode=1)

    tags, result = workload_azure.acr_repository_show_tags("myregistry", "pulsemart", runner=runner)

    assert tags == []
    assert not result.ok


def test_acr_repository_show_tags_parses_json_list(result_factory) -> None:
    def runner(args, **_kwargs):
        return result_factory(stdout='["abc123-def456", "latest"]', returncode=0)

    tags, _result = workload_azure.acr_repository_show_tags(
        "myregistry", "pulsemart", runner=runner
    )

    assert tags == ["abc123-def456", "latest"]


def test_containerapp_update_image_uses_replace_env_vars(result_factory) -> None:
    captured: list[list[str]] = []
    runner = _capturing_runner(captured, result_factory)

    workload_azure.containerapp_update_image(
        "ca-pulsemart-demo",
        "rg-workload",
        image="myregistry.azurecr.io/pulsemart:abc123-def456",
        revision_suffix="baseline-abc123-def456",
        env_vars={"PAYMENT_GATEWAY_PROFILE": "standard", "PULSEMART_RELEASE": "abc123-def456"},
        runner=runner,
    )

    args = captured[0]
    assert "--image" in args
    assert "myregistry.azurecr.io/pulsemart:abc123-def456" in args
    assert "--revision-suffix" in args
    assert "baseline-abc123-def456" in args
    assert "--replace-env-vars" in args
    assert "PAYMENT_GATEWAY_PROFILE=standard" in args
    assert "PULSEMART_RELEASE=abc123-def456" in args


def test_containerapp_ingress_traffic_set_formats_revision_weights(result_factory) -> None:
    captured: list[list[str]] = []
    runner = _capturing_runner(captured, result_factory)

    workload_azure.containerapp_ingress_traffic_set(
        "ca-pulsemart-demo", "rg-workload", {"ca-pulsemart-demo--baseline-x": 100}, runner=runner
    )

    args = captured[0]
    assert "--revision-weight" in args
    assert "ca-pulsemart-demo--baseline-x=100" in args


def test_containerapp_ingress_update_sets_target_port_and_transport(result_factory) -> None:
    captured: list[list[str]] = []
    runner = _capturing_runner(captured, result_factory)

    workload_azure.containerapp_ingress_update(
        "ca-pulsemart-demo", "rg-workload", target_port=8000, runner=runner
    )

    args = captured[0]
    assert "--target-port" in args
    assert "8000" in args
    assert "--transport" in args
    assert "auto" in args


def test_log_analytics_query_parses_flat_list_response(result_factory) -> None:
    def runner(args, **_kwargs):
        assert "--workspace" in args
        assert "--analytics-query" in args
        return result_factory(stdout=KQL_LIST_JSON, returncode=0)

    rows, result = workload_azure.log_analytics_query(
        "workspace-guid", "SomeTable | count", runner=runner
    )

    assert result.ok
    assert rows == [{"Count": 42, "Level": "Error"}]


def test_log_analytics_query_also_parses_nested_tables_response(result_factory) -> None:
    def runner(args, **_kwargs):
        return result_factory(stdout=KQL_TABLE_JSON, returncode=0)

    rows, result = workload_azure.log_analytics_query(
        "workspace-guid", "SomeTable | count", runner=runner
    )

    assert result.ok
    assert rows == [{"Count": 42, "Level": "Error"}]


def test_app_insights_query_parses_flat_list_response(result_factory) -> None:
    def runner(args, **_kwargs):
        assert "--apps" in args
        return result_factory(stdout=KQL_LIST_JSON, returncode=0)

    rows, _result = workload_azure.app_insights_query("app-guid", "requests | count", runner=runner)

    assert rows == [{"Count": 42, "Level": "Error"}]


def test_monitor_metric_alert_show_returns_none_on_missing(result_factory) -> None:
    def runner(args, **_kwargs):
        return result_factory(stdout="", stderr="not found", returncode=1)

    data, result = workload_azure.monitor_metric_alert_show("alert-x", "rg-workload", runner=runner)

    assert data is None
    assert not result.ok


def test_list_fired_alerts_builds_the_alertsmanagement_url(result_factory) -> None:
    captured: list[list[str]] = []

    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(
            stdout='{"value": [{"properties": {"essentials": {"monitorCondition": "Fired"}}}]}'
        )

    items, result = workload_azure.list_fired_alerts(
        "sub-1",
        target_resource_id="/subscriptions/sub-1/resourceGroups/rg-workload/providers/"
        "Microsoft.App/containerApps/ca-pulsemart-demo",
        runner=runner,
    )

    assert result.ok
    assert items == [{"properties": {"essentials": {"monitorCondition": "Fired"}}}]
    url = captured[0][captured[0].index("--url") + 1]
    assert url.startswith(
        "/subscriptions/sub-1/providers/Microsoft.AlertsManagement/alerts?api-version="
    )
    assert "targetResource=" in url
    assert "ca-pulsemart-demo" in url


def test_list_fired_alerts_without_a_target_resource_omits_the_filter(result_factory) -> None:
    captured: list[list[str]] = []

    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(stdout='{"value": []}')

    items, result = workload_azure.list_fired_alerts("sub-1", runner=runner)

    assert result.ok
    assert items == []
    url = captured[0][captured[0].index("--url") + 1]
    assert "targetResource=" not in url


def test_list_fired_alerts_returns_none_on_malformed_response(result_factory) -> None:
    def runner(args, **_kwargs):
        return result_factory(stdout="not json")

    items, result = workload_azure.list_fired_alerts("sub-1", runner=runner)

    assert items is None
    assert result.ok


def test_activity_log_list_filters_by_resource_and_start_time(result_factory) -> None:
    captured: list[list[str]] = []

    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(
            stdout='[{"operationName": {"value": "Microsoft.App/containerApps/write"}}]'
        )

    items, result = workload_azure.activity_log_list(
        "/subscriptions/sub-1/resourceGroups/rg-workload/providers/"
        "Microsoft.App/containerApps/ca-pulsemart-demo",
        start_time="2026-01-01T00:00:00Z",
        runner=runner,
    )

    assert result.ok
    assert items == [{"operationName": {"value": "Microsoft.App/containerApps/write"}}]
    args = captured[0]
    assert "--resource-id" in args
    assert "--start-time" in args
    assert "--offset" not in args


def test_containerapp_revision_list_includes_all_flag_by_default(result_factory) -> None:
    captured: list[list[str]] = []
    runner = _capturing_runner(captured, result_factory, stdout="[]")

    workload_azure.containerapp_revision_list("ca-pulsemart-demo", "rg-workload", runner=runner)

    assert "--all" in captured[0]
