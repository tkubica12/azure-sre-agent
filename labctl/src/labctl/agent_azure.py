"""Azure CLI/ARM helpers specific to the Azure SRE Agent resource and its
connectors (``Microsoft.App/agents``, ``Microsoft.App/agents/connectors``).

Kept separate from :mod:`labctl.workload_azure` because these calls target a
still-preview ARM surface with its own API version (see SPEC.md section 9
and PLAN.md Milestone 3). Every function accepts an injectable ``runner``,
same convention as the rest of the codebase, so unit tests never shell out
to a real ``az``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from labctl import azure_cli
from labctl.azure_cli import AzRunner, rest_get, run_az
from labctl.procutil import CommandResult

# The API version confirmed against the published ARM schema and the
# official Terraform template's `azapi_resource` type strings (see
# infra/modules/sre_agent and
# https://github.com/Azure/azure-rest-api-specs/tree/main/specification/app/resource-manager/Microsoft.App/SreAgent).
# Re-verify before bumping.
AGENT_API_VERSION = "2025-05-01-preview"

#: Connector names this deployment manages (see infra/modules/sre_agent).
CONNECTOR_NAMES: tuple[str, ...] = ("app-insights", "log-analytics", "azure-monitor")

#: Terminal ARM provisioning states. Anything else ("Provisioning",
#: "Accepted", "Updating", ...) is still in progress.
TERMINAL_PROVISIONING_STATES = frozenset({"Succeeded", "Failed", "Canceled"})

#: Default bounded deadlines for polling (see SPEC.md section 11: "Agent
#: connectors are asynchronous and can take 10-30 minutes").
DEFAULT_AGENT_POLL_DEADLINE_SECONDS = 600.0
DEFAULT_AGENT_POLL_INTERVAL_SECONDS = 15.0
DEFAULT_CONNECTOR_POLL_DEADLINE_SECONDS = 1800.0
DEFAULT_CONNECTOR_POLL_INTERVAL_SECONDS = 20.0


def agent_show(
    agent_id: str, *, runner: AzRunner = run_az
) -> tuple[dict[str, Any] | None, CommandResult]:
    """GET the Azure SRE Agent resource itself (properties include
    provisioningState, runningState/powerState, model, accessLevel, and
    action mode)."""

    return rest_get(f"{agent_id}?api-version={AGENT_API_VERSION}", runner=runner)


def set_incident_platform(
    agent_id: str,
    *,
    platform_type: str = "AzMonitor",
    connection_name: str | None = None,
    runner: AzRunner = run_az,
) -> tuple[dict[str, Any] | None, CommandResult]:
    """PATCH the agent resource's ``properties.incidentManagementConfiguration``
    (see the official template's ``Apply-Extras.ps1`` section 1: "ARM PATCH
    on agent resource, not sub-resource PUT"). Live-verified 2026-07-29
    against this subscription/region with body
    ``{"properties": {"incidentManagementConfiguration": {"type":
    "AzMonitor", "connectionName": "azmonitor"}}}``. Idempotent: PATCH-ing
    the same value again is a no-op on the Azure side.
    """

    connection_name = connection_name or platform_type.lower()
    body = json.dumps(
        {
            "properties": {
                "incidentManagementConfiguration": {
                    "type": platform_type,
                    "connectionName": connection_name,
                }
            }
        }
    )
    return azure_cli.rest_call(
        "patch", f"{agent_id}?api-version={AGENT_API_VERSION}", body=body, runner=runner
    )


def incident_platform_type(resource: dict[str, Any] | None) -> str | None:
    """Extract `properties.incidentManagementConfiguration.type`, or
    ``None`` if unset or the resource could not be read."""

    if resource is None:
        return None
    properties = resource.get("properties")
    if not isinstance(properties, dict):
        return None
    config = properties.get("incidentManagementConfiguration")
    if not isinstance(config, dict):
        return None
    value = config.get("type")
    return str(value) if value else None


def connector_show(
    agent_id: str, connector_name: str, *, runner: AzRunner = run_az
) -> tuple[dict[str, Any] | None, CommandResult]:
    return rest_get(
        f"{agent_id}/connectors/{connector_name}?api-version={AGENT_API_VERSION}", runner=runner
    )


def connector_list(
    agent_id: str, *, runner: AzRunner = run_az
) -> tuple[list[dict[str, Any]] | None, CommandResult]:
    data, result = rest_get(f"{agent_id}/connectors?api-version={AGENT_API_VERSION}", runner=runner)
    if not isinstance(data, dict):
        return None, result
    value = data.get("value")
    return ([v for v in value if isinstance(v, dict)] if isinstance(value, list) else []), result


def provisioning_state(resource: dict[str, Any] | None) -> str:
    """Extract `properties.provisioningState`, or "Unknown" if the resource
    could not be read at all (e.g. the ARM call itself failed)."""

    if resource is None:
        return "Unknown"
    properties = resource.get("properties")
    if not isinstance(properties, dict):
        return "Unknown"
    return str(properties.get("provisioningState", "Unknown"))


def poll_until_terminal(
    probe: Callable[[], tuple[dict[str, Any] | None, CommandResult]],
    *,
    deadline_seconds: float,
    interval_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, dict[str, Any] | None, CommandResult]:
    """Call ``probe`` repeatedly until its resource's provisioningState is
    terminal (Succeeded/Failed/Canceled) or ``deadline_seconds`` elapses.

    Returns the last observed provisioning state, resource body, and CLI
    result. Missing the deadline without reaching a terminal state returns
    whatever the last observed (non-terminal) state was; callers decide
    whether that is a failure (see SPEC.md section 11: connectors are
    tolerated past Terraform's own shorter timeout, but a missed overall
    deadline here is a real failure).
    """

    start = clock()
    while True:
        data, result = probe()
        state = provisioning_state(data)
        if state in TERMINAL_PROVISIONING_STATES or (clock() - start) >= deadline_seconds:
            return state, data, result
        sleep(interval_seconds)


def wait_for_agent_provisioned(
    agent_id: str,
    *,
    deadline_seconds: float = DEFAULT_AGENT_POLL_DEADLINE_SECONDS,
    interval_seconds: float = DEFAULT_AGENT_POLL_INTERVAL_SECONDS,
    runner: AzRunner = run_az,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, dict[str, Any] | None, CommandResult]:
    return poll_until_terminal(
        lambda: agent_show(agent_id, runner=runner),
        deadline_seconds=deadline_seconds,
        interval_seconds=interval_seconds,
        sleep=sleep,
        clock=clock,
    )


def wait_for_connector_provisioned(
    agent_id: str,
    connector_name: str,
    *,
    deadline_seconds: float = DEFAULT_CONNECTOR_POLL_DEADLINE_SECONDS,
    interval_seconds: float = DEFAULT_CONNECTOR_POLL_INTERVAL_SECONDS,
    runner: AzRunner = run_az,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, dict[str, Any] | None, CommandResult]:
    return poll_until_terminal(
        lambda: connector_show(agent_id, connector_name, runner=runner),
        deadline_seconds=deadline_seconds,
        interval_seconds=interval_seconds,
        sleep=sleep,
        clock=clock,
    )


__all__ = [
    "AGENT_API_VERSION",
    "CONNECTOR_NAMES",
    "TERMINAL_PROVISIONING_STATES",
    "DEFAULT_AGENT_POLL_DEADLINE_SECONDS",
    "DEFAULT_AGENT_POLL_INTERVAL_SECONDS",
    "DEFAULT_CONNECTOR_POLL_DEADLINE_SECONDS",
    "DEFAULT_CONNECTOR_POLL_INTERVAL_SECONDS",
    "agent_show",
    "set_incident_platform",
    "incident_platform_type",
    "connector_show",
    "connector_list",
    "provisioning_state",
    "poll_until_terminal",
    "wait_for_agent_provisioned",
    "wait_for_connector_provisioned",
]
