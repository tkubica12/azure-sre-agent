"""`labctl evidence collect`: capture a redacted evidence bundle for the
"Learn" beat (see AGENTS.md rhythm, SPEC.md section 11's `evidence collect`
contract, and PLAN.md Milestone 5).

Everything written here is either already non-secret Terraform/Azure-CLI
JSON output or has passed through :func:`labctl.procutil.redact`. Nothing
from this module is committed to git (`.evidence/` is repository-ignored;
see AGENTS.md "Treat ... generated evidence ... as sensitive local
artifacts").
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from labctl import agent_dataplane, workload_azure
from labctl import context as ctx
from labctl.azure_cli import ensure_subscription_context
from labctl.config import Config
from labctl.procutil import CommandResult, redact
from labctl.scenario_definition import list_scenario_slugs, load_scenario_definition
from labctl.state import load_deployment_state, load_scenario_state

Echo = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    exit_code: int
    output_dir: Path | None = None


def _redact_recursive(value: Any) -> Any:
    """Recursively apply :func:`labctl.procutil.redact` to every string leaf
    in ``value`` (dicts, lists, and scalars), keeping the surrounding JSON
    structure valid, unlike redacting the whole serialized text blob."""

    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_recursive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_recursive(v) for v in value]
    return value


def _write_json(path: Path, data: Any) -> None:
    """Recursively redact every string value in ``data`` (see
    :func:`_redact_recursive`) before serializing, as defense in depth beyond
    the ``secretref:``-only Container App env vars this deployment creates:
    stale revisions created before that convention (or by an earlier,
    unrelated deployment) can still carry a literal Application Insights
    connection string in raw `az containerapp revision list` output, and the
    agent's own tool-execution transcripts can echo back whatever a live
    Azure CLI/query call returned. Every evidence file goes through the same
    redaction as subprocess output (see AGENTS.md "avoid ... secret
    values"), not just the ones this module explicitly expects to be
    sensitive.
    """

    redacted = _redact_recursive(data)
    path.write_text(json.dumps(redacted, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _safe(result: CommandResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "ok": result.ok,
        "returncode": result.returncode,
        "diagnostic": redact(result.diagnostic()),
    }


def run_evidence_collect(config: Config, *, echo: Echo = print) -> EvidenceResult:
    account, fatal_message = ensure_subscription_context(config)
    if account is None:
        echo(f"error: {fatal_message}")
        return EvidenceResult(2)

    workload_context, _wc_result = ctx.load_workload_context(config)
    agent_context, _ac_result = ctx.load_agent_context(config)
    if workload_context is None:
        echo("error: could not read Terraform outputs. Has `labctl deploy` been run?")
        return EvidenceResult(1)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = config.evidence_path() / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    echo(f"Collecting evidence into {output_dir}")

    manifest: dict[str, Any] = {
        "collected_at": datetime.now(UTC).isoformat(),
        "subscription_id": account.subscription_id,
        "tenant_id": account.tenant_id,
        "workload_resource_group": workload_context.workload_resource_group,
        "agent_resource_group": (agent_context.agent_resource_group if agent_context else None),
        "files": [],
    }

    def record(name: str, data: Any) -> None:
        path = output_dir / name
        _write_json(path, data)
        manifest["files"].append(name)
        echo(f"  wrote {name}")

    # Revision and traffic history: proves the exact rollback/reset sequence.
    revisions, rev_result = workload_azure.containerapp_revision_list(
        workload_context.container_app_name, workload_context.workload_resource_group
    )
    record(
        "container-app-revisions.json",
        {"revisions": revisions or [], "cli": _safe(rev_result)},
    )

    traffic, traffic_result = workload_azure.containerapp_ingress_traffic_show(
        workload_context.container_app_name, workload_context.workload_resource_group
    )
    record("container-app-traffic.json", {"traffic": traffic or [], "cli": _safe(traffic_result)})

    # Alert rule definition and real fired/resolved instance history.
    alert_rule, alert_rule_result = workload_azure.monitor_metric_alert_show(
        workload_context.metric_alert_name, workload_context.workload_resource_group
    )
    record(
        "alert-rule.json",
        {"rule": alert_rule, "cli": _safe(alert_rule_result)},
    )
    alerts, alerts_result = workload_azure.list_fired_alerts(
        account.subscription_id, target_resource_id=workload_context.container_app_id
    )
    record(
        "alert-instances.json",
        {"instances": alerts or [], "cli": _safe(alerts_result)},
    )

    # Telemetry snapshots (last 30 minutes), same queries `labctl verify` uses.
    requests_rows, requests_result = workload_azure.app_insights_query(
        workload_context.app_insights_app_id,
        "requests | where timestamp > ago(30m) | project timestamp, name, success, "
        "resultCode, cloud_RoleInstance | order by timestamp desc | take 200",
    )
    record(
        "app-insights-requests.json",
        {"rows": requests_rows or [], "cli": _safe(requests_result)},
    )
    exceptions_rows, exceptions_result = workload_azure.app_insights_query(
        workload_context.app_insights_app_id,
        "exceptions | where timestamp > ago(30m) | project timestamp, type, outerMessage "
        "| order by timestamp desc | take 100",
    )
    record(
        "app-insights-exceptions.json",
        {"rows": exceptions_rows or [], "cli": _safe(exceptions_result)},
    )
    logs_rows, logs_result = workload_azure.log_analytics_query(
        workload_context.log_analytics_workspace_id,
        "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(30m) "
        f"| where ContainerAppName_s =~ '{workload_context.container_app_name}' "
        "| project TimeGenerated, Log_s, RevisionName_s | order by TimeGenerated desc | take 200",
    )
    record("log-analytics-console-logs.json", {"rows": logs_rows or [], "cli": _safe(logs_result)})

    # Scenario state (idempotency/repeatability record) for every scenario.
    scenario_states = {}
    for slug in list_scenario_slugs(config):
        state = load_scenario_state(config, slug)
        scenario_states[slug] = {
            "fault_active": state.fault_active,
            "fault_revision_name": state.fault_revision_name,
            "baseline_revision_name": state.baseline_revision_name,
            "triggered_at": state.triggered_at,
            "alert_fired_at": state.alert_fired_at,
            "last_reset_at": state.last_reset_at,
            "run_count": state.run_count,
        }
    record("scenario-state.json", scenario_states)

    deployment_state = load_deployment_state(config)
    record(
        "deployment-state.json",
        {
            "image_tag": deployment_state.image_tag,
            "baseline_revision_name": deployment_state.baseline_revision_name,
            "deployed_at": deployment_state.deployed_at,
            "git_commit": deployment_state.git_commit,
        },
    )

    # Real agent incident threads and their message transcripts (the "least
    # verified link" evidence -- see PLAN.md Milestone 5). Best-effort: an
    # agent that is not deployed, or a token failure, still lets the rest of
    # the bundle collect (see AGENTS.md "avoid ... silent fallbacks" -- this
    # is recorded explicitly in the manifest, never silently skipped).
    threads_note = "agent not deployed"
    if agent_context is not None:
        dp_token, token_result = agent_dataplane.get_data_plane_token()
        if dp_token is None:
            threads_note = f"could not acquire data-plane token: {token_result.diagnostic()}"
        else:
            threads, threads_result = agent_dataplane.list_threads(
                agent_context.data_plane_endpoint, dp_token
            )
            if threads is None:
                threads_note = f"could not list threads: {threads_result.diagnostic()}"
            else:
                record("agent-threads.json", {"threads": threads})
                threads_note = f"{len(threads)} thread(s) captured"
                incident_scenarios = []
                for slug in list_scenario_slugs(config):
                    scenario = load_scenario_definition(config, slug)
                    matching = [
                        t
                        for t in threads
                        if scenario.incident.title_contains.lower()
                        in str(t.get("title", "")).lower()
                    ]
                    for thread in matching:
                        thread_id = str(thread.get("id", ""))
                        if not thread_id:
                            continue
                        messages, messages_result = agent_dataplane.get_thread_messages(
                            agent_context.data_plane_endpoint, dp_token, thread_id
                        )
                        if messages is not None:
                            record(
                                f"agent-thread-{thread_id}-messages.json",
                                {"thread": thread, "messages": messages},
                            )
                        else:
                            echo(
                                f"  warning: could not fetch messages for thread "
                                f"{thread_id}: {messages_result.diagnostic()}"
                            )
                        incident_scenarios.append(slug)
                manifest["incident_scenarios_matched"] = incident_scenarios
            dp_token = None  # never keep the token in a local variable longer than needed

    manifest["agent_threads_note"] = threads_note
    _write_json(output_dir / "manifest.json", manifest)
    echo(f"  wrote manifest.json ({threads_note})")

    echo(f"\nDone. Evidence bundle: {output_dir}")
    return EvidenceResult(0, output_dir)


__all__ = ["EvidenceResult", "run_evidence_collect"]
