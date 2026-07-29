from __future__ import annotations

import labctl.agent_azure as agent_azure

AGENT_ID = (
    "/subscriptions/sub-1/resourceGroups/rg-agent/providers/Microsoft.App/agents/sre-agent-demo"
)


def _capturing_runner(captured: list[list[str]], result_factory, *, stdout: str = "{}"):
    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(stdout=stdout, returncode=0)

    return runner


def test_agent_show_builds_the_expected_rest_url(result_factory) -> None:
    captured: list[list[str]] = []
    runner = _capturing_runner(
        captured, result_factory, stdout='{"properties": {"provisioningState": "Succeeded"}}'
    )

    data, result = agent_azure.agent_show(AGENT_ID, runner=runner)

    assert result.ok
    assert data == {"properties": {"provisioningState": "Succeeded"}}
    url = captured[0][captured[0].index("--url") + 1]
    assert url == f"{AGENT_ID}?api-version={agent_azure.AGENT_API_VERSION}"


def test_connector_show_builds_the_expected_rest_url(result_factory) -> None:
    captured: list[list[str]] = []
    runner = _capturing_runner(captured, result_factory, stdout="{}")

    agent_azure.connector_show(AGENT_ID, "app-insights", runner=runner)

    url = captured[0][captured[0].index("--url") + 1]
    assert url == f"{AGENT_ID}/connectors/app-insights?api-version={agent_azure.AGENT_API_VERSION}"


def test_set_incident_platform_patches_with_the_expected_body(result_factory) -> None:
    captured: list[list[str]] = []
    runner = _capturing_runner(captured, result_factory, stdout='{"properties": {}}')

    data, result = agent_azure.set_incident_platform(
        AGENT_ID, platform_type="AzMonitor", runner=runner
    )

    assert result.ok
    assert data == {"properties": {}}
    args = captured[0]
    assert args[args.index("--method") + 1] == "patch"
    expected_url = f"{AGENT_ID}?api-version={agent_azure.AGENT_API_VERSION}"
    assert args[args.index("--url") + 1] == expected_url
    import json

    body = json.loads(args[args.index("--body") + 1])
    assert body == {
        "properties": {
            "incidentManagementConfiguration": {"type": "AzMonitor", "connectionName": "azmonitor"}
        }
    }


def test_incident_platform_type_extracts_the_configured_type() -> None:
    resource = {"properties": {"incidentManagementConfiguration": {"type": "AzMonitor"}}}

    assert agent_azure.incident_platform_type(resource) == "AzMonitor"


def test_incident_platform_type_returns_none_when_unset() -> None:
    assert agent_azure.incident_platform_type({"properties": {}}) is None
    assert agent_azure.incident_platform_type(None) is None


def test_connector_list_extracts_value_array(result_factory) -> None:
    def runner(args, **_kw):
        return result_factory(
            stdout='{"value": [{"name": "app-insights", "properties": {"provisioningState": '
            '"Succeeded"}}]}'
        )

    data, result = agent_azure.connector_list(AGENT_ID, runner=runner)

    assert result.ok
    assert data == [{"name": "app-insights", "properties": {"provisioningState": "Succeeded"}}]


def test_connector_list_returns_none_on_unparseable_response(result_factory) -> None:
    def runner(args, **_kw):
        return result_factory(stdout="not-json")

    data, _result = agent_azure.connector_list(AGENT_ID, runner=runner)

    assert data is None


def test_provisioning_state_extracts_field() -> None:
    assert agent_azure.provisioning_state({"properties": {"provisioningState": "Succeeded"}}) == (
        "Succeeded"
    )


def test_provisioning_state_returns_unknown_when_missing() -> None:
    assert agent_azure.provisioning_state(None) == "Unknown"
    assert agent_azure.provisioning_state({}) == "Unknown"
    assert agent_azure.provisioning_state({"properties": "not-a-dict"}) == "Unknown"


def test_poll_until_terminal_returns_immediately_on_terminal_state(result_factory) -> None:
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return {"properties": {"provisioningState": "Succeeded"}}, result_factory(stdout="{}")

    sleeps: list[float] = []
    state, data, _result = agent_azure.poll_until_terminal(
        probe, deadline_seconds=100.0, interval_seconds=1.0, sleep=sleeps.append
    )

    assert state == "Succeeded"
    assert data == {"properties": {"provisioningState": "Succeeded"}}
    assert calls["n"] == 1
    assert not sleeps


def test_poll_until_terminal_retries_until_terminal(result_factory) -> None:
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        state = "Succeeded" if calls["n"] >= 3 else "Provisioning"
        return {"properties": {"provisioningState": state}}, result_factory(stdout="{}")

    sleeps: list[float] = []
    state, _data, _result = agent_azure.poll_until_terminal(
        probe, deadline_seconds=100.0, interval_seconds=2.0, sleep=sleeps.append
    )

    assert state == "Succeeded"
    assert calls["n"] == 3
    assert sleeps == [2.0, 2.0]


def test_poll_until_terminal_stops_at_deadline_without_terminal_state(result_factory) -> None:
    clock_values = iter([0.0, 0.0, 5.0, 11.0])

    def probe():
        return {"properties": {"provisioningState": "Provisioning"}}, result_factory(stdout="{}")

    state, _data, _result = agent_azure.poll_until_terminal(
        probe,
        deadline_seconds=10.0,
        interval_seconds=5.0,
        sleep=lambda _s: None,
        clock=lambda: next(clock_values),
    )

    assert state == "Provisioning"


def test_wait_for_agent_provisioned_delegates_to_agent_show(result_factory) -> None:
    def runner(args, **_kw):
        return result_factory(stdout='{"properties": {"provisioningState": "Succeeded"}}')

    state, data, _result = agent_azure.wait_for_agent_provisioned(
        AGENT_ID, deadline_seconds=5.0, interval_seconds=1.0, runner=runner, sleep=lambda _s: None
    )

    assert state == "Succeeded"
    assert data == {"properties": {"provisioningState": "Succeeded"}}


def test_wait_for_connector_provisioned_delegates_to_connector_show(result_factory) -> None:
    def runner(args, **_kw):
        return result_factory(stdout='{"properties": {"provisioningState": "Failed"}}')

    state, _data, _result = agent_azure.wait_for_connector_provisioned(
        AGENT_ID,
        "azure-monitor",
        deadline_seconds=5.0,
        interval_seconds=1.0,
        runner=runner,
        sleep=lambda _s: None,
    )

    assert state == "Failed"
