"""Azure CLI helpers specific to the PulseMart workload: ACR cloud builds,
Container Apps revision/traffic management, and Log Analytics/Application
Insights queries.

Kept separate from :mod:`labctl.azure_cli` (which stays a thin, generic
``az`` layer) because every function here encodes workload-specific command
shapes. All functions accept an injectable ``runner`` for unit tests, same
convention as the rest of the codebase.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from labctl.azure_cli import AzRunner, run_az
from labctl.procutil import CommandResult

DEFAULT_ACR_BUILD_TIMEOUT = 900.0

#: Name of the Container App secret that holds the Application Insights
#: connection string (see infra/modules/container_app's `secret` block).
#: `labctl deploy` references it via `secretref:<name>` instead of ever
#: passing the connection string itself as a literal `az containerapp
#: update` argument (see AGENTS.md and SPEC.md section 9).
APP_INSIGHTS_CONNECTION_STRING_SECRET_NAME = "app-insights-connection-string"


def _parse_json(result: CommandResult) -> Any | None:
    if not result.ok or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _parse_kql_table(data: Any) -> list[dict[str, Any]] | None:
    """Normalize a Log Analytics / Application Insights CLI query response
    into a list of column-name-keyed records.

    `az monitor log-analytics query`/`az monitor app-insights query` with
    ``--output json`` already flatten the Kusto result into a plain JSON
    array of row objects (verified against the installed `log-analytics`/
    `application-insights` extensions). The nested
    ``{"tables": [{"columns": [...], "rows": [[...]]}]}`` shape is the raw
    REST API response and is handled too, defensively, in case a future CLI
    version reverts to it.
    """

    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return None
    tables = data.get("tables")
    if not isinstance(tables, list) or not tables:
        return None
    table = tables[0]
    columns = [c.get("name", "") for c in table.get("columns", [])]
    rows = table.get("rows", [])
    return [dict(zip(columns, row, strict=False)) for row in rows]


# --------------------------------------------------------------------------
# ACR cloud build
# --------------------------------------------------------------------------


def acr_build(
    registry_name: str,
    image_refs: list[str],
    source_path: str | Path,
    *,
    platform: str = "linux",
    runner: AzRunner = run_az,
    timeout: float = DEFAULT_ACR_BUILD_TIMEOUT,
) -> CommandResult:
    """Run `az acr build`, tagging the built image with every ref in
    ``image_refs`` (e.g. an immutable content tag plus a floating
    ``latest``). No local Docker daemon is used (see PLAN.md environment
    facts).

    ``--no-logs`` suppresses streaming the remote build log to stdout;
    without it, Azure CLI's colorama console wrapper crashes with a
    ``UnicodeEncodeError`` against the legacy Windows code page whenever the
    streamed log contains certain non-ASCII bytes (observed against a real
    ACR build in this repository's own Windows environment, independent of
    `PYTHONIOENCODING`/`AZURE_CORE_NO_COLOR`). `az acr build` still blocks
    until the queued run finishes and returns its real exit code either way;
    only the live log tail is skipped.
    """

    args = [
        "acr",
        "build",
        "--registry",
        registry_name,
        "--platform",
        platform,
        "--no-logs",
    ]
    for ref in image_refs:
        args += ["--image", ref]
    args.append(str(source_path))
    return runner(args, timeout=timeout, retries=0)


def acr_repository_show_tags(
    registry_name: str, repository: str, *, runner: AzRunner = run_az
) -> tuple[list[str] | None, CommandResult]:
    """List existing tags for ``repository``, used by `labctl deploy` to skip
    a redundant `az acr build` when the deterministic content tag already
    exists (idempotent reruns).
    """

    result = runner(
        [
            "acr",
            "repository",
            "show-tags",
            "--name",
            registry_name,
            "--repository",
            repository,
            "--output",
            "json",
        ],
        timeout=30.0,
        retries=1,
    )
    if not result.ok:
        # A brand new registry with no pushed repository yet reports a
        # nonzero exit; treat that as "no tags" rather than a hard failure.
        return [], result
    data = _parse_json(result)
    return (data if isinstance(data, list) else []), result


# --------------------------------------------------------------------------
# Container Apps
# --------------------------------------------------------------------------


def containerapp_show(
    name: str, resource_group: str, *, runner: AzRunner = run_az
) -> tuple[dict[str, Any] | None, CommandResult]:
    result = runner(
        [
            "containerapp",
            "show",
            "--name",
            name,
            "--resource-group",
            resource_group,
            "--output",
            "json",
        ],
        timeout=60.0,
        retries=1,
    )
    data = _parse_json(result)
    return (data if isinstance(data, dict) else None), result


def containerapp_update_image(
    name: str,
    resource_group: str,
    *,
    image: str,
    revision_suffix: str,
    env_vars: dict[str, str],
    runner: AzRunner = run_az,
    timeout: float = 300.0,
) -> CommandResult:
    """Create a new immutable revision from ``image`` with an explicit
    ``revision_suffix``, replacing the container's environment variables
    with exactly ``env_vars`` (via ``--replace-env-vars``, so a stale payment
    dependency profile from a previous scenario revision cannot leak into the
    new one).
    """

    args = [
        "containerapp",
        "update",
        "--name",
        name,
        "--resource-group",
        resource_group,
        "--image",
        image,
        "--revision-suffix",
        revision_suffix,
    ]
    if env_vars:
        args.append("--replace-env-vars")
        args += [f"{key}={value}" for key, value in env_vars.items()]
    return runner(args, timeout=timeout, retries=1)


def containerapp_ingress_update(
    name: str,
    resource_group: str,
    *,
    target_port: int,
    transport: str = "auto",
    runner: AzRunner = run_az,
    timeout: float = 120.0,
) -> CommandResult:
    return runner(
        [
            "containerapp",
            "ingress",
            "update",
            "--name",
            name,
            "--resource-group",
            resource_group,
            "--type",
            "external",
            "--target-port",
            str(target_port),
            "--transport",
            transport,
        ],
        timeout=timeout,
        retries=1,
    )


def containerapp_ingress_traffic_set(
    name: str,
    resource_group: str,
    revision_weights: dict[str, int],
    *,
    runner: AzRunner = run_az,
    timeout: float = 120.0,
) -> CommandResult:
    """Set explicit traffic weights by revision name (never by 'latest'), so
    the baseline is pinned to a specific immutable revision rather than
    silently following whatever revision is created next (see SPEC.md
    section 7: "`labctl` ... records the known-good revision, and owns all
    traffic changes").
    """

    weight_args = [f"{revision}={weight}" for revision, weight in revision_weights.items()]
    return runner(
        [
            "containerapp",
            "ingress",
            "traffic",
            "set",
            "--name",
            name,
            "--resource-group",
            resource_group,
            "--revision-weight",
            *weight_args,
        ],
        timeout=timeout,
        retries=1,
    )


def containerapp_ingress_traffic_show(
    name: str, resource_group: str, *, runner: AzRunner = run_az
) -> tuple[list[dict[str, Any]] | None, CommandResult]:
    result = runner(
        [
            "containerapp",
            "ingress",
            "traffic",
            "show",
            "--name",
            name,
            "--resource-group",
            resource_group,
            "--output",
            "json",
        ],
        timeout=60.0,
        retries=1,
    )
    data = _parse_json(result)
    return (data if isinstance(data, list) else None), result


def containerapp_revision_list(
    name: str,
    resource_group: str,
    *,
    include_inactive: bool = True,
    runner: AzRunner = run_az,
) -> tuple[list[dict[str, Any]] | None, CommandResult]:
    args = [
        "containerapp",
        "revision",
        "list",
        "--name",
        name,
        "--resource-group",
        resource_group,
        "--output",
        "json",
    ]
    if include_inactive:
        args.append("--all")
    result = runner(args, timeout=60.0, retries=1)
    data = _parse_json(result)
    return (data if isinstance(data, list) else None), result


# --------------------------------------------------------------------------
# Azure Monitor alerting
# --------------------------------------------------------------------------


#: The `Microsoft.AlertsManagement/alerts` API version this demo pins for
#: reading real fired-alert *instances* (distinct from the metric alert
#: *rule* resource `monitor_metric_alert_show` reads). Live-verified
#: 2026-07-29 against a real fired Container App 5xx alert instance:
#: the `alertRule` query parameter (accepted by the API, unlike the rejected
#: `alertRuleName`) filters on the alert rule's full ARM resource ID, not its
#: bare name -- passing just the name silently matched zero alerts instead of
#: erroring. `targetResource` (the monitored resource's own full ID, which
#: `labctl` already has from Terraform outputs) reliably filters instead.
ALERTS_MANAGEMENT_API_VERSION = "2019-05-05-preview"


def list_fired_alerts(
    subscription_id: str,
    *,
    target_resource_id: str | None = None,
    runner: AzRunner = run_az,
    timeout: float = 30.0,
) -> tuple[list[dict[str, Any]] | None, CommandResult]:
    """List real `Microsoft.AlertsManagement` alert instances (the actual
    fired/resolved lifecycle of every alert rule scoped to one resource),
    optionally filtered to one monitored resource via the `targetResource`
    query parameter (live-verified 2026-07-29; see `ALERTS_MANAGEMENT_API_VERSION`).

    Each item's ``properties.essentials.monitorCondition`` is ``"Fired"`` or
    ``"Resolved"``; ``properties.essentials.alertState`` is the separate
    human-acknowledgement lifecycle (``New``/``Acknowledged``/``Closed``).
    Used by `labctl demo trigger`/`verify` to observe the real alert
    transition instead of only the static rule definition, and by `labctl
    evidence collect` to capture its state history.
    """

    url_path = f"/subscriptions/{subscription_id}/providers/Microsoft.AlertsManagement/alerts"
    query = f"?api-version={ALERTS_MANAGEMENT_API_VERSION}"
    if target_resource_id:
        query += f"&targetResource={quote(target_resource_id, safe='')}"
    result = runner(
        ["rest", "--method", "get", "--url", f"{url_path}{query}", "--output", "json"],
        timeout=timeout,
        retries=1,
    )
    data = _parse_json(result)
    if not isinstance(data, dict):
        return None, result
    value = data.get("value")
    return ([v for v in value if isinstance(v, dict)] if isinstance(value, list) else []), result


def activity_log_list(
    resource_id: str,
    *,
    start_time: str | None = None,
    offset: str = "7d",
    runner: AzRunner = run_az,
    timeout: float = 60.0,
) -> tuple[list[dict[str, Any]] | None, CommandResult]:
    """Read Azure Activity Log entries for one resource without server-side
    JMESPath filtering.

    PowerShell can mangle quoted ``--query`` expressions, so callers filter
    the JSON client-side. ``start_time`` is preferred when the scenario has a
    recorded trigger/deploy timestamp; ``offset`` keeps a bounded fallback for
    older local state.
    """

    args = [
        "monitor",
        "activity-log",
        "list",
        "--resource-id",
        resource_id,
        "--output",
        "json",
    ]
    if start_time:
        args += ["--start-time", start_time]
    else:
        args += ["--offset", offset]
    result = runner(args, timeout=timeout, retries=1)
    data = _parse_json(result)
    return ([v for v in data if isinstance(v, dict)] if isinstance(data, list) else None), result


def monitor_metric_alert_show(
    name: str, resource_group: str, *, runner: AzRunner = run_az
) -> tuple[dict[str, Any] | None, CommandResult]:
    result = runner(
        [
            "monitor",
            "metrics",
            "alert",
            "show",
            "--name",
            name,
            "--resource-group",
            resource_group,
            "--output",
            "json",
        ],
        timeout=60.0,
        retries=1,
    )
    data = _parse_json(result)
    return (data if isinstance(data, dict) else None), result


# --------------------------------------------------------------------------
# Telemetry queries
# --------------------------------------------------------------------------


def log_analytics_query(
    workspace_id: str,
    query: str,
    *,
    timespan: str | None = None,
    runner: AzRunner = run_az,
    timeout: float = 60.0,
) -> tuple[list[dict[str, Any]] | None, CommandResult]:
    args = [
        "monitor",
        "log-analytics",
        "query",
        "--workspace",
        workspace_id,
        "--analytics-query",
        query,
        "--output",
        "json",
    ]
    if timespan:
        args += ["--timespan", timespan]
    result = runner(args, timeout=timeout, retries=1)
    return _parse_kql_table(_parse_json(result)), result


def app_insights_query(
    app_id: str,
    query: str,
    *,
    offset: str = "1h",
    runner: AzRunner = run_az,
    timeout: float = 60.0,
) -> tuple[list[dict[str, Any]] | None, CommandResult]:
    args = [
        "monitor",
        "app-insights",
        "query",
        "--apps",
        app_id,
        "--analytics-query",
        query,
        "--offset",
        offset,
        "--output",
        "json",
    ]
    result = runner(args, timeout=timeout, retries=1)
    return _parse_kql_table(_parse_json(result)), result


__all__ = [
    "DEFAULT_ACR_BUILD_TIMEOUT",
    "APP_INSIGHTS_CONNECTION_STRING_SECRET_NAME",
    "acr_build",
    "acr_repository_show_tags",
    "containerapp_show",
    "containerapp_update_image",
    "containerapp_ingress_update",
    "containerapp_ingress_traffic_set",
    "containerapp_ingress_traffic_show",
    "containerapp_revision_list",
    "ALERTS_MANAGEMENT_API_VERSION",
    "list_fired_alerts",
    "activity_log_list",
    "monitor_metric_alert_show",
    "log_analytics_query",
    "app_insights_query",
]
