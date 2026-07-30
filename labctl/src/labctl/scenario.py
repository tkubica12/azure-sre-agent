"""`labctl demo list/prepare/trigger/verify/reset`: orchestration for the
`scenarios/<slug>/` incident scenarios (see AGENTS.md repository layout,
SPEC.md sections 5 and 11, and PLAN.md Milestone 5).

Terraform intentionally ignores the Container App's `template`/`ingress`
fields after the first apply (see infra/modules/container_app and SPEC.md
section 7), so this module -- not Terraform -- owns every revision/traffic
change a scenario makes, and is the only place that decides which revision is
currently "the fault" versus "the known-good baseline".
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from labctl import agent_dataplane, workload_azure
from labctl import context as ctx
from labctl.azure_cli import Account, ensure_subscription_context
from labctl.config import Config
from labctl.http_client import HttpResult
from labctl.http_client import get as http_get
from labctl.http_client import post as http_post
from labctl.load import generate_checkout_load, generate_checkout_load_for
from labctl.procutil import CommandResult
from labctl.scenario_definition import (
    ScenarioDefinition,
    ScenarioError,
    list_scenario_slugs,
    load_scenario_definition,
)
from labctl.state import (
    DeploymentState,
    ScenarioState,
    load_deployment_state,
    load_scenario_state,
    save_scenario_state,
)
from labctl.verify import CheckResult, Status, summarize

Echo = Callable[[str], None]
Sleep = Callable[[float], None]

#: Env vars every revision this module creates carries unchanged from the
#: baseline (see labctl/src/labctl/deploy.py `run_deploy`'s own env_vars
#: block, the single other writer of Container App revisions). Kept in sync
#: manually; `labctl verify`'s `workload-checkout` check would fail loudly if
#: these ever drifted from what the app expects.
_APP_INSIGHTS_ENV_NAME = "APPLICATIONINSIGHTS_CONNECTION_STRING"


@dataclass(frozen=True, slots=True)
class DemoResult:
    exit_code: int


@dataclass(frozen=True, slots=True)
class _RollbackObservation:
    timestamp: datetime
    detail: str


#: Azure Container Apps' real constraint (live-verified 2026-07-29, ARM error
#: `ContainerAppInvalidRevisionName`): the container app name plus a "--"
#: separator plus the revision suffix must not exceed 54 characters
#: combined. This is materially shorter than the revision *suffix* argument's
#: own 63-character limit that `az containerapp update --help` documents in
#: isolation, and only becomes visible once a real revision-suffix write is
#: attempted against a real Container App name -- there is no client-side
#: warning for it.
_MAX_COMBINED_REVISION_NAME_LENGTH = 54
_CHECKOUT_OPERATION_NAME = "POST /api/checkout"
_RECOVERY_CANARY_MIN_REQUESTS = 6
_RECOVERY_CANARY_CONCURRENCY = 2
_RECOVERY_TELEMETRY_TIMEOUT_SECONDS = 120.0
_RECOVERY_TELEMETRY_POLL_SECONDS = 10.0
_PARTIAL_FAULT_PROBE_MIN_REQUESTS = 60


def _fault_revision_suffix(container_app_name: str, prefix: str, image_tag: str, epoch: int) -> str:
    """Build a revision suffix that is unique per `labctl demo trigger` call
    (via ``epoch``, so repeat runs never collide with a still-existing
    fault revision from an earlier pass) and fits Azure's real combined
    54-character revision-name limit for this specific container app name.
    Prefers including the image tag for traceability; falls back to a
    shorter ``<prefix>-<epoch>`` form when the full form would not fit.
    """

    budget = _MAX_COMBINED_REVISION_NAME_LENGTH - len(container_app_name) - len("--")
    with_image_tag = f"{prefix}-{image_tag}-{epoch}"
    if len(with_image_tag) <= budget:
        return with_image_tag
    return f"{prefix}-{epoch}"[:budget]


def _fail(echo: Echo, message: str) -> DemoResult:
    echo(f"error: {message}")
    return DemoResult(1)


def _describe_http(result: HttpResult) -> str:
    """A short, safe-to-print description of one HTTP outcome: either the
    status code, or "transport error: ..." when the request never completed
    (connection refused, DNS failure, timeout). Used everywhere a check
    reports an unexpected checkout response.
    """

    if result.ok:
        return str(result.status_code)
    return f"transport error: {result.error}"


def _parse_azure_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _kql_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _kql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _event_operation_value(event: dict[str, Any]) -> str:
    operation = event.get("operationName")
    if isinstance(operation, dict):
        return str(operation.get("value") or operation.get("localizedValue") or "")
    return str(operation or "")


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    return _parse_azure_timestamp(event.get("eventTimestamp")) or _parse_azure_timestamp(
        event.get("submissionTimestamp")
    )


def _latest_containerapp_write(events: list[dict[str, Any]]) -> datetime | None:
    candidates: list[datetime] = []
    for event in events:
        operation = _event_operation_value(event).lower()
        if "microsoft.app/containerapps/write" not in operation:
            continue
        status = event.get("status")
        status_value = (
            str(status.get("value") or status.get("localizedValue") or "")
            if isinstance(status, dict)
            else str(status or "")
        )
        if status_value.lower() not in {"accepted", "succeeded"}:
            continue
        timestamp = _event_timestamp(event)
        if timestamp is not None:
            candidates.append(timestamp)
    return max(candidates) if candidates else None


def _determine_recovery_write_timestamp(
    workload_context: ctx.WorkloadContext,
    deployment_state: DeploymentState,
    state: ScenarioState,
) -> tuple[_RollbackObservation | None, str]:
    # The Activity Log records the Container App write made by `az containerapp
    # ingress traffic set` (including the Azure SRE Agent's rollback). The log
    # entry does not carry the new traffic weights, so we pair the latest
    # successful Container App write after the scenario trigger with the live
    # ingress state already read by `demo verify` (baseline=100%) instead of
    # trusting a local timestamp or an agent claim.
    start_time = state.triggered_at or state.last_reset_at or deployment_state.deployed_at
    events, result = workload_azure.activity_log_list(
        workload_context.container_app_id, start_time=start_time or None
    )
    if events is None:
        return None, f"could not query Activity Log: {result.diagnostic()}"
    timestamp = _latest_containerapp_write(events)
    if timestamp is None:
        scope = f" since {start_time}" if start_time else ""
        return None, f"no successful Container App write was found in the Activity Log{scope}."
    return (
        _RollbackObservation(
            timestamp=timestamp,
            detail=f"latest successful Container App write at {_kql_datetime(timestamp)}",
        ),
        "",
    )


def _build_recovery_telemetry_query(proof_start: datetime, recovered_revision: str) -> str:
    revision_suffix = recovered_revision.split("--", 1)[-1]
    return (
        f"let proof_start = datetime({_kql_datetime(proof_start)});\n"
        "requests\n"
        "| where timestamp >= proof_start\n"
        f"| where name =~ {_kql_string(_CHECKOUT_OPERATION_NAME)} "
        f"or operation_Name =~ {_kql_string(_CHECKOUT_OPERATION_NAME)}\n"
        "| extend roleInstance = tostring(cloud_RoleInstance), "
        'serviceRevision = tostring(customDimensions["service.revision"]), '
        'serviceInstance = tostring(customDimensions["service.instance.id"])\n'
        "| where isempty(roleInstance) "
        f"or roleInstance has {_kql_string(recovered_revision)} "
        f"or serviceRevision =~ {_kql_string(revision_suffix)} "
        f"or serviceInstance =~ {_kql_string(revision_suffix)}\n"
        "| summarize total=count(), failed=countif(toint(resultCode) between (500 .. 599))"
    )


def _recovery_canary_request_count(config: Config) -> int:
    # Send more requests than the proof threshold because Application Insights
    # ingestion can occasionally lag or drop one successful request from a tiny
    # batch; verification still requires at least _RECOVERY_CANARY_MIN_REQUESTS
    # observed rows below.
    return max(_RECOVERY_CANARY_MIN_REQUESTS * 2, config.workload.alert_threshold_5xx, 1)


def _post_checkout_recovery_canary(url: str, **_kwargs: object) -> HttpResult:
    return http_post(url, timeout=30.0, retries=2, retry_delay=2.0)


def _query_recovery_telemetry(
    workload_context: ctx.WorkloadContext,
    query: str,
    *,
    min_observed: int,
    threshold: int,
) -> CheckResult:
    deadline = time.monotonic() + _RECOVERY_TELEMETRY_TIMEOUT_SECONDS
    last_detail = ""
    while True:
        rows, ai_result = workload_azure.app_insights_query(
            workload_context.app_insights_app_id, query
        )
        if rows is None:
            return CheckResult(
                "failure-rate-below-threshold",
                Status.FAIL,
                f"could not query Application Insights: {ai_result.diagnostic()}",
            )
        row = rows[0] if rows else {}
        total = int(row.get("total", 0))
        failed = int(row.get("failed", 0))
        if total >= min_observed:
            if failed >= threshold:
                return CheckResult(
                    "failure-rate-below-threshold",
                    Status.FAIL,
                    f"{failed} checkout 5xx request(s) since rollback; alert threshold is "
                    f"{threshold}.",
                )
            return CheckResult(
                "failure-rate-below-threshold",
                Status.PASS,
                f"{failed} checkout 5xx request(s) across {total} checkout request(s) since "
                f"the recovery proof started; alert threshold is {threshold}.",
            )
        last_detail = (
            f"only {total} checkout request telemetry row(s) observed since rollback; need at "
            f"least {min_observed} to prove the canary batch reached Application Insights."
        )
        if time.monotonic() >= deadline:
            return CheckResult("failure-rate-below-threshold", Status.FAIL, last_detail)
        time.sleep(_RECOVERY_TELEMETRY_POLL_SECONDS)


def _alert_matches(alert: dict[str, Any], alert_name: str) -> bool:
    essentials = alert.get("properties", {}).get("essentials", {})
    if not isinstance(essentials, dict):
        return False
    rule = str(essentials.get("alertRule") or essentials.get("alertRuleId") or "")
    return not rule or alert_name.lower() in rule.lower()


def _alert_target_resource_id(
    workload_context: ctx.WorkloadContext, scenario: ScenarioDefinition
) -> str:
    if scenario.alert.target_resource == "app_insights":
        return workload_context.app_insights_resource_id
    return workload_context.container_app_id


def _list_matching_alerts(
    account: Account, workload_context: ctx.WorkloadContext, scenario: ScenarioDefinition
) -> tuple[list[dict[str, Any]] | None, CommandResult]:
    alerts, result = workload_azure.list_fired_alerts(
        account.subscription_id,
        target_resource_id=_alert_target_resource_id(workload_context, scenario),
    )
    if alerts is None:
        return None, result
    return [alert for alert in alerts if _alert_matches(alert, scenario.alert.name)], result


def _monitor_condition(alert: dict[str, Any]) -> str:
    essentials = alert.get("properties", {}).get("essentials", {})
    if not isinstance(essentials, dict):
        return ""
    return str(essentials.get("monitorCondition") or "")


def _check_alert_not_firing(
    account: Account, workload_context: ctx.WorkloadContext, scenario: ScenarioDefinition
) -> CheckResult:
    alerts, result = _list_matching_alerts(account, workload_context, scenario)
    if alerts is None:
        return CheckResult(
            "alert-not-firing",
            Status.FAIL,
            f"could not query alert instances: {result.diagnostic()}",
        )
    fired = [alert for alert in alerts if _monitor_condition(alert) == "Fired"]
    if fired:
        return CheckResult(
            "alert-not-firing",
            Status.WARN,
            f"checkout canary and telemetry are below threshold, but Azure Monitor still shows "
            f"{scenario.alert.name!r} in Fired state; auto-resolution is pending.",
        )
    if alerts:
        conditions = sorted({_monitor_condition(alert) or "Unknown" for alert in alerts})
        return CheckResult(
            "alert-not-firing",
            Status.PASS,
            f"no matching Fired alert instance; observed condition(s): {', '.join(conditions)}.",
        )
    return CheckResult(
        "alert-not-firing",
        Status.PASS,
        "no matching Fired alert instance is present for this Container App.",
    )


def _load_prereqs(
    config: Config, slug: str, echo: Echo
) -> tuple[Account, ctx.WorkloadContext, DeploymentState, ScenarioDefinition] | None:
    account, fatal_message = ensure_subscription_context(config)
    if account is None:
        echo(f"error: {fatal_message}")
        return None

    try:
        scenario = load_scenario_definition(config, slug)
    except ScenarioError as exc:
        echo(f"error: {exc}")
        return None

    workload_context, result = ctx.load_workload_context(config)
    if workload_context is None:
        echo("error: could not read Terraform outputs. Has `labctl deploy` been run?")
        if result is not None:
            echo(result.redacted_stderr())
        return None

    deployment_state = load_deployment_state(config)
    if not deployment_state.baseline_revision_name or not deployment_state.image_ref:
        echo(
            "error: no recorded baseline revision in .state/deployment.json. "
            "Run `labctl deploy --yes` first."
        )
        return None

    return account, workload_context, deployment_state, scenario


def _fault_env_vars(
    deployment_state: DeploymentState, config: Config, scenario: ScenarioDefinition
) -> dict[str, str]:
    return {
        _APP_INSIGHTS_ENV_NAME: (
            f"secretref:{workload_azure.APP_INSIGHTS_CONNECTION_STRING_SECRET_NAME}"
        ),
        "PULSEMART_RELEASE": deployment_state.image_tag,
        "PULSEMART_ENVIRONMENT": config.tags.environment,
        **scenario.fault.env,
    }


def _current_traffic(workload_context: ctx.WorkloadContext) -> dict[str, int]:
    traffic, _result = workload_azure.containerapp_ingress_traffic_show(
        workload_context.container_app_name, workload_context.workload_resource_group
    )
    weights: dict[str, int] = {}
    for entry in traffic or []:
        name = entry.get("revisionName") or entry.get("latestRevision")
        if name:
            weights[str(name)] = int(entry.get("weight", 0))
    return weights


def _revision_exists(workload_context: ctx.WorkloadContext, revision_name: str) -> bool:
    revisions, _result = workload_azure.containerapp_revision_list(
        workload_context.container_app_name, workload_context.workload_resource_group
    )
    return any(r.get("name") == revision_name for r in revisions or [])


def _wait_for_revision_ready(
    workload_context: ctx.WorkloadContext,
    revision_name: str,
    *,
    echo: Echo,
    attempts: int = 12,
    delay_seconds: float = 10.0,
    sleep: Sleep = time.sleep,
) -> bool:
    for attempt in range(attempts):
        revisions, result = workload_azure.containerapp_revision_list(
            workload_context.container_app_name, workload_context.workload_resource_group
        )
        if revisions is None:
            echo(f"  warning: could not list revisions: {result.diagnostic()}")
        else:
            match = next((r for r in revisions if r.get("name") == revision_name), None)
            if match is not None:
                props = match.get("properties", {})
                if props.get("provisioningState") == "Provisioned":
                    return True
        if attempt < attempts - 1:
            sleep(delay_seconds)
    return False


def run_demo_list(config: Config, *, echo: Echo = print) -> DemoResult:
    slugs = list_scenario_slugs(config)
    if not slugs:
        echo("No scenarios found under scenarios/.")
        return DemoResult(0)

    deployment_state = load_deployment_state(config)
    has_baseline = bool(deployment_state.baseline_revision_name)

    echo(f"{'SLUG':<20} {'DURATION':<10} {'READY':<8} TITLE")
    for slug in slugs:
        try:
            scenario = load_scenario_definition(config, slug)
        except ScenarioError as exc:
            echo(f"{slug:<20} {'?':<10} {'ERROR':<8} {exc}")
            continue
        state = load_scenario_state(config, slug)
        ready = "yes" if has_baseline else "no (deploy)"
        phase = "fault-active" if state.fault_active else "baseline"
        echo(
            f"{slug:<20} {scenario.estimated_duration_minutes:>3} min    "
            f"{ready:<8} {scenario.title}  [{phase}]"
        )
    return DemoResult(0)


def run_demo_prepare(config: Config, slug: str, *, echo: Echo = print) -> DemoResult:
    prereqs = _load_prereqs(config, slug, echo)
    if prereqs is None:
        return DemoResult(1)
    _account, workload_context, deployment_state, _scenario = prereqs

    baseline = deployment_state.baseline_revision_name
    weights = _current_traffic(workload_context)
    echo(f"Baseline revision: {baseline}")
    echo(f"Current traffic:    {weights}")

    if weights.get(baseline, 0) != 100:
        if not _revision_exists(workload_context, baseline):
            return _fail(
                echo,
                f"baseline revision {baseline!r} no longer exists. Run `labctl deploy --yes` "
                "to recreate it.",
            )
        echo(f"Shifting 100% traffic back to baseline revision {baseline!r}...")
        traffic_result = workload_azure.containerapp_ingress_traffic_set(
            workload_context.container_app_name,
            workload_context.workload_resource_group,
            {baseline: 100},
        )
        if not traffic_result.ok:
            return _fail(echo, f"could not shift traffic: {traffic_result.diagnostic()}")
    else:
        echo("Traffic already 100% on the baseline revision; nothing to change.")

    url = workload_context.endpoint_url()
    health = http_get(f"{url}/healthz", timeout=10.0, retries=6, retry_delay=5.0)
    if not health.ok:
        return _fail(echo, f"GET {url}/healthz did not respond: {health.error}")
    echo(f"GET {url}/healthz -> HTTP {health.status_code}")

    checkout = http_post(f"{url}/api/checkout", timeout=15.0, retries=2)
    if not checkout.ok or checkout.status_code != 200:
        return _fail(
            echo,
            f"POST {url}/api/checkout returned {_describe_http(checkout)} "
            "while expecting a healthy HTTP 200. The baseline is not actually healthy.",
        )
    echo(f"POST {url}/api/checkout -> HTTP {checkout.status_code}")

    state = load_scenario_state(config, slug)
    if state.fault_active:
        state = ScenarioState(
            slug=slug,
            fault_active=False,
            baseline_revision_name=baseline,
            last_reset_at=datetime.now(UTC).isoformat(),
            run_count=state.run_count,
        )
        save_scenario_state(config, state)

    echo("\nScenario is prepared: healthy baseline confirmed, no active fault.")
    return DemoResult(0)


def run_demo_trigger(
    config: Config, slug: str, *, echo: Echo = print, sleep: Sleep = time.sleep
) -> DemoResult:
    prereqs = _load_prereqs(config, slug, echo)
    if prereqs is None:
        return DemoResult(1)
    account, workload_context, deployment_state, scenario = prereqs

    echo(f"Scenario: {scenario.title}")
    lo, hi = scenario.alert.expected_time_to_fire_minutes
    echo(
        f"Expected time to alert fire: {lo}-{hi} minutes after the failure threshold is "
        f"crossed (rule evaluates every 1 minute over a trailing window; see "
        "infra/modules/alerting)."
    )

    state = load_scenario_state(config, slug)
    baseline = deployment_state.baseline_revision_name

    fault_revision_name = state.fault_revision_name
    reuse = bool(
        state.fault_active
        and fault_revision_name
        and _revision_exists(workload_context, fault_revision_name)
    )

    if reuse:
        echo(f"[1/4] Reusing existing fault revision {fault_revision_name!r} (idempotent rerun).")
    else:
        image_tag = deployment_state.image_tag
        epoch = int(time.time())
        suffix = _fault_revision_suffix(
            workload_context.container_app_name,
            scenario.fault.revision_suffix_prefix,
            image_tag,
            epoch,
        )
        fault_revision_name = f"{workload_context.container_app_name}--{suffix}"
        echo(f"[1/4] Creating fault revision {fault_revision_name!r} from the baseline image.")
        env_vars = _fault_env_vars(deployment_state, config, scenario)
        update_result = workload_azure.containerapp_update_image(
            workload_context.container_app_name,
            workload_context.workload_resource_group,
            image=deployment_state.image_ref,
            revision_suffix=suffix,
            env_vars=env_vars,
        )
        if not update_result.ok:
            return _fail(echo, f"az containerapp update failed: {update_result.diagnostic()}")

        ready = _wait_for_revision_ready(
            workload_context, fault_revision_name, echo=echo, sleep=sleep
        )
        if not ready:
            return _fail(
                echo, f"revision {fault_revision_name!r} did not reach Provisioned in time."
            )

    fault_weight = scenario.fault.traffic_weight
    baseline_weight = 100 - fault_weight
    target_weights = (
        {fault_revision_name: 100}
        if fault_weight == 100
        else {baseline: baseline_weight, fault_revision_name: fault_weight}
    )
    echo(
        f"[2/4] Setting traffic split: {baseline!r}={baseline_weight}%, "
        f"{fault_revision_name!r}={fault_weight}%."
    )
    traffic_result = workload_azure.containerapp_ingress_traffic_set(
        workload_context.container_app_name,
        workload_context.workload_resource_group,
        target_weights,
    )
    if not traffic_result.ok:
        return _fail(echo, f"could not shift traffic: {traffic_result.diagnostic()}")

    triggered_at = datetime.now(UTC).isoformat()
    save_scenario_state(
        config,
        ScenarioState(
            slug=slug,
            fault_active=True,
            fault_revision_name=fault_revision_name,
            fault_revision_suffix=fault_revision_name.split("--", 1)[-1],
            baseline_revision_name=baseline,
            triggered_at=triggered_at,
            incident_thread_id=state.incident_thread_id,
            incident_thread_title=state.incident_thread_title,
            run_count=state.run_count + 1,
        ),
    )

    url = workload_context.endpoint_url()
    confirm = http_post(f"{url}/api/checkout", timeout=15.0, retries=2)
    if fault_weight == 100 and confirm.ok and confirm.status_code >= 500:
        echo(f"  confirmed: POST {url}/api/checkout -> HTTP {confirm.status_code}")
    elif fault_weight < 100:
        echo(
            f"  sampled mixed-traffic checkout returned {_describe_http(confirm)} "
            f"(expected to be ambiguous with only {fault_weight}% on the canary)."
        )
    else:
        echo(
            f"  warning: expected HTTP >=500 from the fault revision, got {_describe_http(confirm)}"
        )

    if scenario.load.duration_seconds > 0:
        echo(
            f"[3/4] Generating sustained synthetic checkout load "
            f"(duration={scenario.load.duration_seconds:.0f}s, "
            f"concurrency={scenario.load.concurrency})."
        )
        echo(
            f"  Sustaining mixed traffic for {scenario.load.duration_seconds:.0f}s while "
            "Azure Monitor evaluates."
        )
    else:
        echo(
            f"[3/4] Generating synthetic checkout load "
            f"({scenario.load.request_count} requests, concurrency={scenario.load.concurrency})."
        )
    load_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool:
        load_future = (
            pool.submit(
                generate_checkout_load_for,
                f"{url}/api/checkout",
                duration_seconds=scenario.load.duration_seconds,
                concurrency=scenario.load.concurrency,
                timeout=scenario.load.request_timeout_seconds,
                target_count=scenario.load.request_count,
            )
            if scenario.load.duration_seconds > 0
            else pool.submit(
                generate_checkout_load,
                f"{url}/api/checkout",
                count=scenario.load.request_count,
                concurrency=scenario.load.concurrency,
                timeout=scenario.load.request_timeout_seconds,
            )
        )

        echo(
            f"[4/4] Polling the real alert '{scenario.alert.name}' for up to "
            f"{scenario.alert.max_wait_seconds:.0f}s (evaluates every ~1 minute)."
        )
        start = time.monotonic()
        fired = False
        reported_fired = False
        while time.monotonic() - start < scenario.alert.max_wait_seconds:
            alerts, result = _list_matching_alerts(account, workload_context, scenario)
            if alerts is None:
                echo(f"  warning: could not query alert instances: {result.diagnostic()}")
            elif any(_monitor_condition(alert) == "Fired" for alert in alerts):
                fired = True
                if (
                    scenario.load.duration_seconds > 0
                    and not load_future.done()
                    and not reported_fired
                ):
                    reported_fired = True
                    echo(
                        f"  Alert '{scenario.alert.name}' entered Fired state after "
                        f"{time.monotonic() - start:.0f}s; continuing sustained traffic."
                    )
                else:
                    break
            if fired and load_future.done():
                break
            sleep(scenario.alert.poll_interval_seconds)

        load_result = load_future.result()

    elapsed = time.monotonic() - start
    load_elapsed = time.monotonic() - load_started
    echo(f"  {load_result.summary()} (wall clock {load_elapsed:.0f}s)")
    if load_result.failed < scenario.load.min_failures_required:
        return _fail(
            echo,
            f"only {load_result.failed} HTTP 5xx/4xx responses observed, need at least "
            f"{scenario.load.min_failures_required} to trust the real alert threshold. The "
            "fault revision may not actually be serving traffic yet.",
        )

    if fired:
        echo(f"  Alert '{scenario.alert.name}' entered Fired state after {elapsed:.0f}s.")
        current_state = load_scenario_state(config, slug)
        save_scenario_state(
            config,
            ScenarioState(
                slug=current_state.slug,
                fault_active=current_state.fault_active,
                fault_revision_name=current_state.fault_revision_name,
                fault_revision_suffix=current_state.fault_revision_suffix,
                baseline_revision_name=current_state.baseline_revision_name,
                triggered_at=current_state.triggered_at,
                alert_fired_at=datetime.now(UTC).isoformat(),
                incident_thread_id=current_state.incident_thread_id,
                incident_thread_title=current_state.incident_thread_title,
                last_reset_at=current_state.last_reset_at,
                run_count=current_state.run_count,
            ),
        )
    else:
        echo(
            f"  Alert '{scenario.alert.name}' had not entered Fired state after {elapsed:.0f}s. "
            "The checkout failures themselves are still real; re-run `labctl demo verify "
            f"{slug}` in a few minutes, or check the portal directly."
        )

    echo(
        "\nFault is live. Open the Azure SRE Agent portal Incidents view (see `labctl status`) "
        f"or run `labctl demo verify {slug}` to watch the investigation."
    )
    return DemoResult(0)


def _find_incident_thread(
    endpoint: str, token: str, scenario: ScenarioDefinition, *, since_iso: str
) -> tuple[dict[str, object] | None, str]:
    threads, result = agent_dataplane.list_threads(endpoint, token)
    if threads is None:
        return None, f"could not list agent threads: {result.diagnostic()}"
    candidates = [
        t
        for t in threads
        if scenario.incident.title_contains.lower() in str(t.get("title", "")).lower()
    ]
    if since_iso:
        candidates = [t for t in candidates if str(t.get("createdTimestamp", "")) >= since_iso]
    if not candidates:
        return None, "no matching incident thread found yet"
    candidates.sort(key=lambda t: str(t.get("createdTimestamp", "")))
    return candidates[-1], ""


def run_demo_verify(config: Config, slug: str, *, echo: Echo = print) -> DemoResult:
    prereqs = _load_prereqs(config, slug, echo)
    if prereqs is None:
        return DemoResult(1)
    account, workload_context, deployment_state, scenario = prereqs
    agent_context, _agent_result = ctx.load_agent_context(config)

    baseline = deployment_state.baseline_revision_name
    weights = _current_traffic(workload_context)
    baseline_weight = weights.get(baseline, 0)
    phase = "recovered" if baseline_weight == 100 else "fault"
    echo(f"Phase: {phase} (baseline weight={baseline_weight}%, traffic={weights})")

    url = workload_context.endpoint_url()
    results: list[CheckResult] = []

    if phase == "fault":
        if scenario.fault.traffic_weight < 100:
            probe_count = min(
                scenario.load.request_count,
                max(_PARTIAL_FAULT_PROBE_MIN_REQUESTS, scenario.load.min_failures_required * 10),
            )
            probe = generate_checkout_load(
                f"{url}/api/checkout",
                count=probe_count,
                concurrency=min(max(scenario.load.concurrency, 1), 8),
                timeout=scenario.load.request_timeout_seconds,
            )
            if (
                probe.failed >= scenario.load.min_failures_required
                and probe.succeeded > 0
                and probe.failed < probe.total
            ):
                results.append(
                    CheckResult(
                        "partial-checkout-degradation",
                        Status.PASS,
                        f"{probe.summary()}; mixed success/failure confirms partial impact.",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "partial-checkout-degradation",
                        Status.FAIL,
                        f"{probe.summary()}; expected at least "
                        f"{scenario.load.min_failures_required} failures and at least one success "
                        "while the canary carries a small traffic slice.",
                    )
                )
        else:
            checkout = http_post(f"{url}/api/checkout", timeout=15.0, retries=2)
            if checkout.ok and checkout.status_code >= 500:
                results.append(
                    CheckResult(
                        "checkout-returns-500",
                        Status.PASS,
                        f"POST /api/checkout -> HTTP {checkout.status_code}.",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "checkout-returns-500",
                        Status.FAIL,
                        f"expected HTTP >=500, got {_describe_http(checkout)}.",
                    )
                )
        non_baseline = {r: w for r, w in weights.items() if r != baseline and w > 0}
        if non_baseline:
            results.append(
                CheckResult(
                    "traffic-on-fault-revision", Status.PASS, f"fault traffic: {non_baseline}."
                )
            )
        else:
            results.append(
                CheckResult(
                    "traffic-on-fault-revision",
                    Status.FAIL,
                    f"no non-baseline revision is receiving traffic ({weights}).",
                )
            )

        state = load_scenario_state(config, slug)
        alerts, alert_result = _list_matching_alerts(account, workload_context, scenario)
        if alerts and any(
            _monitor_condition(alert) == "Fired"
            for alert in alerts
        ):
            results.append(CheckResult("alert-fired", Status.PASS, "alert is in Fired state."))
        elif state.alert_fired_at:
            results.append(
                CheckResult(
                    "alert-fired",
                    Status.PASS,
                    f"alert fired at {state.alert_fired_at} (local record).",
                )
            )
        else:
            detail = alert_result.diagnostic() if alerts is None else "no Fired instance yet."
            results.append(CheckResult("alert-fired", Status.WARN, detail))

        if agent_context is None:
            results.append(
                CheckResult(
                    "agent-incident-thread", Status.WARN, "Azure SRE Agent is not deployed."
                )
            )
        else:
            dp_token, token_result = agent_dataplane.get_data_plane_token()
            if dp_token is None:
                results.append(
                    CheckResult(
                        "agent-incident-thread",
                        Status.WARN,
                        f"could not acquire a data-plane token: {token_result.diagnostic()}",
                    )
                )
            else:
                thread, detail = _find_incident_thread(
                    agent_context.data_plane_endpoint,
                    dp_token,
                    scenario,
                    since_iso=state.triggered_at,
                )
                if thread is not None:
                    status_obj = thread.get("status")
                    incident_status_obj = (
                        status_obj.get("incidentStatus") if isinstance(status_obj, dict) else None
                    )
                    incident_status = (
                        incident_status_obj.get("status")
                        if isinstance(incident_status_obj, dict)
                        else None
                    )
                    results.append(
                        CheckResult(
                            "agent-incident-thread",
                            Status.PASS,
                            f"thread {thread.get('id')!r} title={thread.get('title')!r} "
                            f"status={incident_status!r}.",
                        )
                    )
                else:
                    results.append(CheckResult("agent-incident-thread", Status.WARN, detail))
        results.append(
            CheckResult(
                "recovery-not-established",
                Status.FAIL,
                "traffic is not 100% on the known-good baseline revision; the service is still "
                "in the fault phase.",
            )
        )
    else:
        canary_count = _recovery_canary_request_count(config)
        canary_started_at = datetime.now(UTC)
        canary = generate_checkout_load(
            f"{url}/api/checkout",
            count=canary_count,
            concurrency=(
                1 if canary_count <= _RECOVERY_CANARY_MIN_REQUESTS else _RECOVERY_CANARY_CONCURRENCY
            ),
            timeout=scenario.load.request_timeout_seconds,
            poster=_post_checkout_recovery_canary,
        )
        if canary.succeeded == canary.total and canary.failed == 0 and canary.transport_errors == 0:
            results.append(
                CheckResult(
                    "checkout-canary-batch",
                    Status.PASS,
                    f"{canary.summary()}; every checkout returned HTTP <400.",
                )
            )
        else:
            results.append(
                CheckResult(
                    "checkout-canary-batch",
                    Status.FAIL,
                    f"{canary.summary()}; expected every checkout to succeed after rollback.",
                )
            )
        if baseline_weight == 100:
            results.append(
                CheckResult("traffic-on-baseline-revision", Status.PASS, f"{baseline}=100%.")
            )
        else:
            results.append(
                CheckResult(
                    "traffic-on-baseline-revision",
                    Status.FAIL,
                    f"baseline weight is {baseline_weight}%, expected 100% ({weights}).",
                )
            )

        state = load_scenario_state(config, slug)
        rollback, rollback_detail = _determine_recovery_write_timestamp(
            workload_context, deployment_state, state
        )
        if rollback is None:
            results.append(
                CheckResult(
                    "rollback-timestamp-observed",
                    Status.WARN,
                    f"{rollback_detail} Using the current verification canary start time as the "
                    "telemetry proof window instead.",
                )
            )
            proof_start = canary_started_at
        else:
            results.append(
                CheckResult(
                    "rollback-timestamp-observed",
                    Status.PASS,
                    rollback.detail,
                )
            )
            proof_start = max(rollback.timestamp, canary_started_at)
        query = _build_recovery_telemetry_query(proof_start, baseline)
        results.append(
            _query_recovery_telemetry(
                workload_context,
                query,
                min_observed=min(canary_count, _RECOVERY_CANARY_MIN_REQUESTS),
                threshold=max(config.workload.alert_threshold_5xx, 1),
            )
        )
        results.append(_check_alert_not_firing(account, workload_context, scenario))

    table, exit_code = summarize(results)
    echo(table)
    return DemoResult(exit_code)


def run_demo_reset(config: Config, slug: str, *, echo: Echo = print) -> DemoResult:
    prereqs = _load_prereqs(config, slug, echo)
    if prereqs is None:
        return DemoResult(1)
    _account, workload_context, deployment_state, _scenario = prereqs

    baseline = deployment_state.baseline_revision_name
    weights = _current_traffic(workload_context)
    echo(f"Baseline revision: {baseline}")
    echo(f"Current traffic:    {weights}")

    if weights.get(baseline, 0) == 100:
        echo("Traffic already 100% on the baseline revision; nothing to change.")
    else:
        if not _revision_exists(workload_context, baseline):
            return _fail(
                echo,
                f"baseline revision {baseline!r} no longer exists. Run `labctl deploy --yes` "
                "to recreate it.",
            )
        echo(f"Shifting 100% traffic back to baseline revision {baseline!r}...")
        traffic_result = workload_azure.containerapp_ingress_traffic_set(
            workload_context.container_app_name,
            workload_context.workload_resource_group,
            {baseline: 100},
        )
        if not traffic_result.ok:
            return _fail(echo, f"could not shift traffic: {traffic_result.diagnostic()}")

    url = workload_context.endpoint_url()
    health = http_get(f"{url}/healthz", timeout=10.0, retries=6, retry_delay=5.0)
    if not health.ok:
        return _fail(echo, f"GET {url}/healthz did not respond: {health.error}")
    checkout = http_post(f"{url}/api/checkout", timeout=15.0, retries=3)
    if not checkout.ok or checkout.status_code != 200:
        return _fail(
            echo,
            f"POST {url}/api/checkout returned {_describe_http(checkout)} "
            "after reset (expected HTTP 200).",
        )
    echo(f"POST {url}/api/checkout -> HTTP {checkout.status_code} (recovered).")

    state = load_scenario_state(config, slug)
    save_scenario_state(
        config,
        ScenarioState(
            slug=slug,
            fault_active=False,
            fault_revision_name=state.fault_revision_name,
            fault_revision_suffix=state.fault_revision_suffix,
            baseline_revision_name=baseline,
            triggered_at=state.triggered_at,
            alert_fired_at=state.alert_fired_at,
            incident_thread_id=state.incident_thread_id,
            incident_thread_title=state.incident_thread_title,
            last_reset_at=datetime.now(UTC).isoformat(),
            run_count=state.run_count,
        ),
    )
    echo("\nReset complete: 100% traffic on the known-good baseline revision, checkout healthy.")
    return DemoResult(0)


__all__ = [
    "DemoResult",
    "run_demo_list",
    "run_demo_prepare",
    "run_demo_trigger",
    "run_demo_verify",
    "run_demo_reset",
]
