"""`labctl verify` checks for the workload and the Azure SRE Agent (see
SPEC.md section 11 contract and AGENTS.md validation requirements). Agent
data-plane content (knowledge, subagents, hooks, incident platform, response
plans) is Milestone 4 work and is deliberately reported as WARN/"not
configured" here, not a failure (see PLAN.md Milestone 4 scope).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from labctl import agent_azure, agent_dataplane, azure_cli, workload_azure
from labctl import agent_content as agent_content_mod
from labctl import context as ctx
from labctl.config import Config
from labctl.http_client import get as http_get
from labctl.http_client import post as http_post

Echo = Callable[[str], None]
T = TypeVar("T")


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: Status
    detail: str


def _retry_until(
    probe: Callable[[], T | None],
    *,
    attempts: int,
    delay_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> T | None:
    """Call ``probe`` up to ``attempts`` times, sleeping ``delay_seconds``
    between calls, until it returns a truthy value or attempts are
    exhausted. Used for telemetry queries, which can lag ingestion by up to
    a couple of minutes (see AGENTS.md "bounded retries and explicit
    timeouts").
    """

    for attempt in range(attempts):
        result = probe()
        if result:
            return result
        if attempt < attempts - 1:
            sleep(delay_seconds)
    return None


def check_endpoint_health(base_url: str) -> CheckResult:
    result = http_get(f"{base_url}/healthz", timeout=10.0, retries=3, retry_delay=5.0)
    if not result.ok:
        return CheckResult(
            "workload-health", Status.FAIL, f"GET /healthz unreachable: {result.error}"
        )
    if result.status_code != 200:
        return CheckResult(
            "workload-health", Status.FAIL, f"GET /healthz returned HTTP {result.status_code}"
        )
    return CheckResult("workload-health", Status.PASS, "GET /healthz returned HTTP 200.")


def check_checkout_behavior(base_url: str) -> CheckResult:
    status = http_get(f"{base_url}/api/status", timeout=10.0, retries=2)
    if not status.ok:
        return CheckResult(
            "workload-checkout", Status.FAIL, f"GET /api/status unreachable: {status.error}"
        )

    checkout = http_post(f"{base_url}/api/checkout", timeout=15.0, retries=2)
    if not checkout.ok:
        return CheckResult(
            "workload-checkout", Status.FAIL, f"POST /api/checkout unreachable: {checkout.error}"
        )

    if checkout.status_code == 200:
        return CheckResult(
            "workload-checkout", Status.PASS, "POST /api/checkout returned HTTP 200."
        )
    return CheckResult(
        "workload-checkout",
        Status.FAIL,
        f"POST /api/checkout returned HTTP {checkout.status_code} while healthy (expected 200).",
    )


def check_revision_mode(workload_context: ctx.WorkloadContext) -> CheckResult:
    data, result = workload_azure.containerapp_show(
        workload_context.container_app_name, workload_context.workload_resource_group
    )
    if data is None:
        return CheckResult(
            "container-app-revision-mode",
            Status.FAIL,
            f"az containerapp show failed: {result.diagnostic()}",
        )
    mode = str(data.get("properties", {}).get("configuration", {}).get("activeRevisionsMode", ""))
    if mode == "Multiple":
        return CheckResult(
            "container-app-revision-mode", Status.PASS, "activeRevisionsMode is Multiple."
        )
    return CheckResult(
        "container-app-revision-mode",
        Status.FAIL,
        f"activeRevisionsMode is {mode!r}, expected 'Multiple'.",
    )


def check_traffic_target(workload_context: ctx.WorkloadContext) -> CheckResult:
    traffic, result = workload_azure.containerapp_ingress_traffic_show(
        workload_context.container_app_name, workload_context.workload_resource_group
    )
    if traffic is None:
        return CheckResult(
            "container-app-traffic",
            Status.FAIL,
            f"could not read ingress traffic: {result.diagnostic()}",
        )
    total = sum(int(entry.get("weight", 0)) for entry in traffic)
    revisions = ", ".join(
        f"{entry.get('revisionName', entry.get('latestRevision'))}={entry.get('weight')}%"
        for entry in traffic
    )
    if total == 100:
        return CheckResult(
            "container-app-traffic", Status.PASS, f"Traffic sums to 100% ({revisions})."
        )
    return CheckResult(
        "container-app-traffic",
        Status.WARN,
        f"Traffic sums to {total}%, expected 100% ({revisions}).",
    )


def check_metric_alert(workload_context: ctx.WorkloadContext) -> CheckResult:
    data, result = workload_azure.monitor_metric_alert_show(
        workload_context.metric_alert_name, workload_context.workload_resource_group
    )
    if data is None:
        return CheckResult(
            "metric-alert",
            Status.FAIL,
            f"az monitor metrics alert show failed: {result.diagnostic()}",
        )
    enabled = bool(data.get("enabled", False))
    criteria = data.get("criteria", {}).get("allOf", [{}])
    metric_name = criteria[0].get("metricName") if criteria else None
    if enabled and metric_name == "Requests":
        return CheckResult(
            "metric-alert",
            Status.PASS,
            f"Alert '{workload_context.metric_alert_name}' is enabled on the Requests metric.",
        )
    return CheckResult(
        "metric-alert",
        Status.FAIL,
        f"Alert enabled={enabled}, metric={metric_name!r} "
        "(expected enabled=True, metric='Requests').",
    )


def check_log_analytics_telemetry(
    workload_context: ctx.WorkloadContext, *, attempts: int = 8, delay_seconds: float = 15.0
) -> CheckResult:
    query = (
        "ContainerAppConsoleLogs_CL "
        "| where TimeGenerated > ago(30m) "
        f"| where ContainerAppName_s =~ '{workload_context.container_app_name}' "
        "| count"
    )

    def probe() -> int | None:
        rows, _ = workload_azure.log_analytics_query(
            workload_context.log_analytics_workspace_id, query
        )
        if not rows:
            return None
        count = int(rows[0].get("Count", 0))
        return count or None

    count = _retry_until(probe, attempts=attempts, delay_seconds=delay_seconds)
    if count:
        return CheckResult(
            "log-analytics-telemetry",
            Status.PASS,
            f"{count} console log record(s) found in Log Analytics.",
        )
    return CheckResult(
        "log-analytics-telemetry",
        Status.WARN,
        "No ContainerAppConsoleLogs_CL records found yet; ingestion can lag by a few minutes.",
    )


def check_app_insights_telemetry(
    workload_context: ctx.WorkloadContext, *, attempts: int = 8, delay_seconds: float = 15.0
) -> CheckResult:
    query = "requests | where timestamp > ago(30m) | count"

    def probe() -> int | None:
        rows, _ = workload_azure.app_insights_query(workload_context.app_insights_app_id, query)
        if not rows:
            return None
        count = int(rows[0].get("Count", 0))
        return count or None

    count = _retry_until(probe, attempts=attempts, delay_seconds=delay_seconds)
    if count:
        return CheckResult(
            "app-insights-telemetry",
            Status.PASS,
            f"{count} request(s) found in Application Insights.",
        )
    return CheckResult(
        "app-insights-telemetry",
        Status.WARN,
        "No Application Insights requests found yet; ingestion can lag by a few minutes.",
    )


# --------------------------------------------------------------------------
# Azure SRE Agent checks (Milestone 3: agent infrastructure). Data-plane
# content (knowledge, subagents, hooks, incident platform, response plans)
# is Milestone 4 and is deliberately reported as WARN/"not configured", not
# a failure (see SPEC.md section 10 and PLAN.md Milestone 4).
# --------------------------------------------------------------------------

#: Roles expected at the workload resource-group scope regardless of
#: `workload_access_level` (see SPEC.md section 9 and
#: infra/modules/sre_agent).
_EXPECTED_WORKLOAD_RG_ROLES: frozenset[str] = frozenset({"Reader", "Log Analytics Reader"})

#: Write-capable role granted at Container-App scope under the narrow
#: (default) access level, instead of blanket Contributor at the whole
#: resource group (see SPEC.md section 9 / M2).
_EXPECTED_NARROW_APP_ROLE = "Container Apps Contributor"

#: Write-capable role granted at resource-group scope under the "broad"
#: access-level escape hatch (see SPEC.md section 9).
_EXPECTED_BROAD_RG_ROLE = "Contributor"
_EXPECTED_ALERT_LIFECYCLE_ACTIONS: frozenset[str] = frozenset(
    {
        "Microsoft.AlertsManagement/alerts/read",
        "Microsoft.AlertsManagement/alerts/changestate/action",
    }
)
_FORBIDDEN_SUBSCRIPTION_MONITORING_ROLE = "Monitoring Contributor"

#: `experimentalSettings` flags Terraform sets on the agent resource (see
#: infra/modules/sre_agent/main.tf); all must be `true`.
_EXPECTED_EXPERIMENTAL_FLAGS: tuple[str, ...] = (
    "EnableWorkspaceTools",
    "EnableHttpTriggers",
    "EnableV2AgentLoop",
)


def _resource_group_scope(resource_id: str) -> str | None:
    """Extract the `/subscriptions/<sub>/resourceGroups/<rg>` scope from a
    full ARM resource ID, used to check RBAC at resource-group scope without
    requiring a dedicated Terraform output for it.
    """

    parts = [p for p in resource_id.split("/") if p]
    if (
        len(parts) >= 4
        and parts[0].lower() == "subscriptions"
        and parts[2].lower() == "resourcegroups"
    ):
        return "/" + "/".join(parts[:4])
    return None


def check_agent_provisioning(
    agent_context: ctx.AgentContext,
) -> tuple[CheckResult, dict[str, object] | None]:
    data, result = agent_azure.agent_show(agent_context.agent_id)
    if data is None:
        return (
            CheckResult(
                "agent-provisioning",
                Status.FAIL,
                f"could not read the agent resource: {result.diagnostic()}",
            ),
            None,
        )
    state = agent_azure.provisioning_state(data)
    if state == "Succeeded":
        return CheckResult("agent-provisioning", Status.PASS, "provisioningState=Succeeded."), data
    if state in agent_azure.TERMINAL_PROVISIONING_STATES:
        # Every terminal state other than Succeeded (Failed, Canceled, and
        # any future terminal value ARM adds) is a real failure, not a
        # warning: there is no "still converging" explanation left once a
        # resource has reached a terminal provisioningState (see M4).
        return (
            CheckResult(
                "agent-provisioning",
                Status.FAIL,
                f"provisioningState={state} (terminal, not Succeeded).",
            ),
            data,
        )
    return (
        CheckResult(
            "agent-provisioning", Status.WARN, f"provisioningState={state!r} (still converging)."
        ),
        data,
    )


def check_agent_running_state(data: dict[str, object] | None) -> CheckResult:
    """Assert the agent is actually powered on and running, not just
    ``provisioningState=Succeeded`` (a successfully provisioned agent can
    still be administratively stopped; see M4)."""

    if data is None:
        return CheckResult("agent-running-state", Status.FAIL, "agent resource unavailable.")
    properties = data.get("properties")
    properties_dict = properties if isinstance(properties, dict) else {}
    running_state = properties_dict.get("runningState")
    power_state = properties_dict.get("powerState")
    observed = {
        k: v for k, v in (("runningState", running_state), ("powerState", power_state)) if v
    }
    if not observed:
        return CheckResult(
            "agent-running-state",
            Status.FAIL,
            "neither runningState nor powerState was reported by ARM.",
        )
    not_running = {k: v for k, v in observed.items() if v != "Running"}
    if not_running:
        mismatches = ", ".join(f"{k}={v!r}" for k, v in not_running.items())
        return CheckResult("agent-running-state", Status.FAIL, f"{mismatches} (expected Running).")
    detail = ", ".join(f"{k}={v}" for k, v in observed.items())
    return CheckResult("agent-running-state", Status.PASS, detail)


def check_agent_identities(
    agent_context: ctx.AgentContext, data: dict[str, object] | None
) -> CheckResult:
    if data is None:
        return CheckResult("agent-identities", Status.FAIL, "agent resource unavailable.")
    identity = data.get("identity")
    identity_dict = identity if isinstance(identity, dict) else {}
    id_type = str(identity_dict.get("type", ""))
    system_principal = identity_dict.get("principalId")
    user_assigned = identity_dict.get("userAssignedIdentities")
    user_assigned_dict = user_assigned if isinstance(user_assigned, dict) else {}
    has_uami = any(k.lower() == agent_context.uami_id.lower() for k in user_assigned_dict)
    if "SystemAssigned" in id_type and "UserAssigned" in id_type and system_principal and has_uami:
        return CheckResult(
            "agent-identities",
            Status.PASS,
            f"identity type={id_type!r}; system-assigned principalId present; UAMI attached.",
        )
    return CheckResult(
        "agent-identities",
        Status.FAIL,
        f"identity type={id_type!r}, system principalId present={bool(system_principal)}, "
        f"UAMI attached={has_uami}.",
    )


def check_agent_configuration(config: Config, data: dict[str, object] | None) -> CheckResult:
    if data is None:
        return CheckResult("agent-configuration", Status.FAIL, "agent resource unavailable.")
    properties = data.get("properties")
    properties_dict = properties if isinstance(properties, dict) else {}
    model = properties_dict.get("defaultModel")
    model_dict = model if isinstance(model, dict) else {}
    action_configuration = properties_dict.get("actionConfiguration")
    action_dict = action_configuration if isinstance(action_configuration, dict) else {}

    provider = model_dict.get("provider")
    model_name = model_dict.get("name")
    access_level = action_dict.get("accessLevel")
    mode = action_dict.get("mode")
    monthly_limit = properties_dict.get("monthlyAgentUnitLimit")
    upgrade_channel = properties_dict.get("upgradeChannel")
    experimental_settings = properties_dict.get("experimentalSettings")
    experimental_dict = experimental_settings if isinstance(experimental_settings, dict) else {}

    mismatches = []
    if provider != config.agent.model_provider:
        mismatches.append(f"model.provider={provider!r} (expected {config.agent.model_provider!r})")
    if model_name != config.agent.model_name:
        mismatches.append(f"model.name={model_name!r} (expected {config.agent.model_name!r})")
    if access_level != "High":
        mismatches.append(f"accessLevel={access_level!r} (expected 'High')")
    if mode != "Review":
        mismatches.append(f"mode={mode!r} (expected 'Review')")
    if monthly_limit != config.agent.monthly_aau_allocation:
        mismatches.append(
            f"monthlyAgentUnitLimit={monthly_limit!r} "
            f"(expected {config.agent.monthly_aau_allocation!r})"
        )
    if upgrade_channel != config.agent.upgrade_channel:
        mismatches.append(
            f"upgradeChannel={upgrade_channel!r} (expected {config.agent.upgrade_channel!r})"
        )
    for flag in _EXPECTED_EXPERIMENTAL_FLAGS:
        if experimental_dict.get(flag) is not True:
            mismatches.append(
                f"experimentalSettings.{flag}={experimental_dict.get(flag)!r} (expected True)"
            )
    if mismatches:
        return CheckResult("agent-configuration", Status.FAIL, "; ".join(mismatches))
    return CheckResult(
        "agent-configuration",
        Status.PASS,
        f"model={provider}/{model_name}, accessLevel={access_level}, mode={mode}, "
        f"monthlyAgentUnitLimit={monthly_limit}.",
    )


def check_agent_workload_rbac(
    config: Config, agent_context: ctx.AgentContext, workload_context: ctx.WorkloadContext
) -> CheckResult:
    """Verify the agent's identities hold the expected roles for the
    configured `agent.workload_access_level` (see SPEC.md section 9 / M2):
    Reader + Log Analytics Reader at the workload resource group always,
    plus either Container Apps Contributor scoped to just the Container App
    (narrow, default) or Contributor at the whole resource group (broad).
    """

    rg_scope = _resource_group_scope(workload_context.container_app_id)
    if rg_scope is None:
        return CheckResult(
            "agent-rbac-workload",
            Status.WARN,
            "could not derive the workload resource group scope for an RBAC check.",
        )

    narrow = config.agent.workload_access_level != "broad"
    app_scope = workload_context.container_app_id if narrow else None
    expected_rg_roles = set(_EXPECTED_WORKLOAD_RG_ROLES)
    expected_app_roles: set[str] = {_EXPECTED_NARROW_APP_ROLE} if narrow else set()
    if not narrow:
        expected_rg_roles.add(_EXPECTED_BROAD_RG_ROLE)

    findings = []
    ok = True
    for label, principal_id in (
        ("UAMI", agent_context.uami_principal_id),
        ("system-assigned identity", agent_context.system_identity_principal_id),
    ):
        rg_roles, rg_result = azure_cli.role_assignments(principal_id, rg_scope)
        if not rg_result.ok:
            ok = False
            findings.append(f"{label}: could not list RG roles ({rg_result.diagnostic()})")
            continue
        missing = expected_rg_roles - set(rg_roles)
        held = set(expected_rg_roles)

        if app_scope is not None:
            app_roles, app_result = azure_cli.role_assignments(principal_id, app_scope)
            if not app_result.ok:
                ok = False
                findings.append(
                    f"{label}: could not list Container App roles ({app_result.diagnostic()})"
                )
                continue
            missing |= expected_app_roles - set(app_roles)

        if missing:
            ok = False
            findings.append(f"{label}: missing {', '.join(sorted(missing))}")
        else:
            findings.append(f"{label}: has {', '.join(sorted(held | expected_app_roles))}")
    return CheckResult(
        "agent-rbac-workload", Status.PASS if ok else Status.FAIL, "; ".join(findings)
    )


def _alert_lifecycle_role_name(config: Config, agent_context: ctx.AgentContext) -> str:
    return (
        "Azure SRE Agent Alert Lifecycle - "
        f"{agent_context.agent_name} - {config.tags.deployment_id}"
    )


def _role_definition_actions(role_definition: dict[str, object]) -> frozenset[str]:
    permissions = role_definition.get("permissions")
    if not isinstance(permissions, list) or not permissions:
        return frozenset()
    first_permission = permissions[0]
    if not isinstance(first_permission, dict):
        return frozenset()
    actions = first_permission.get("actions")
    if not isinstance(actions, list):
        return frozenset()
    return frozenset(str(action) for action in actions)


def _role_definition_non_action_permissions(role_definition: dict[str, object]) -> frozenset[str]:
    permissions = role_definition.get("permissions")
    if not isinstance(permissions, list):
        return frozenset()
    entries: list[str] = []
    for permission in permissions:
        if not isinstance(permission, dict):
            continue
        for key in ("notActions", "dataActions", "notDataActions"):
            values = permission.get(key)
            if isinstance(values, list):
                entries.extend(f"{key}:{value}" for value in values)
    return frozenset(str(entry) for entry in entries)


def check_agent_alert_lifecycle_rbac(
    config: Config, agent_context: ctx.AgentContext
) -> CheckResult:
    """Verify the UAMI holds this deployment's custom alert-lifecycle role at
    subscription scope, the system-assigned identity does not get a duplicate
    subscription-scoped write grant, neither identity has Monitoring
    Contributor at subscription scope, and the UAMI keeps Monitoring Reader on
    the agent resource group.
    """

    subscription_scope = f"/subscriptions/{agent_context.agent_id.split('/')[2]}"
    agent_rg_scope = _resource_group_scope(agent_context.agent_id)
    expected_role_name = _alert_lifecycle_role_name(config, agent_context)
    findings = []
    ok = True

    role_definition, role_result = azure_cli.role_definition_by_name(expected_role_name)
    if role_definition is None:
        ok = False
        findings.append(
            f"custom role {expected_role_name!r}: missing or unreadable "
            f"({role_result.diagnostic()})"
        )
    else:
        actions = _role_definition_actions(role_definition)
        non_action_permissions = _role_definition_non_action_permissions(role_definition)
        if actions != _EXPECTED_ALERT_LIFECYCLE_ACTIONS or non_action_permissions:
            ok = False
            findings.append(
                f"custom role {expected_role_name!r}: actions={sorted(actions)} "
                f"(expected {sorted(_EXPECTED_ALERT_LIFECYCLE_ACTIONS)}), "
                f"other permissions={sorted(non_action_permissions)}"
            )
        else:
            findings.append(
                f"custom role {expected_role_name!r}: exactly alert read/change-state actions"
            )

    uami_roles, uami_sub_result = azure_cli.role_assignments(
        agent_context.uami_principal_id, subscription_scope
    )
    if not uami_sub_result.ok:
        ok = False
        findings.append(f"UAMI: could not list subscription roles ({uami_sub_result.diagnostic()})")
    else:
        if expected_role_name not in uami_roles:
            ok = False
            findings.append(f"UAMI: missing {expected_role_name} at subscription scope")
        else:
            findings.append(f"UAMI: has {expected_role_name} at subscription scope")
        if _FORBIDDEN_SUBSCRIPTION_MONITORING_ROLE in uami_roles:
            ok = False
            findings.append("UAMI: forbidden Monitoring Contributor still present")

    system_roles, system_sub_result = azure_cli.role_assignments(
        agent_context.system_identity_principal_id, subscription_scope
    )
    if not system_sub_result.ok:
        ok = False
        findings.append(
            f"system-assigned identity: could not list subscription roles "
            f"({system_sub_result.diagnostic()})"
        )
    else:
        if expected_role_name in system_roles:
            ok = False
            findings.append("system-assigned identity: duplicate custom alert role present")
        if _FORBIDDEN_SUBSCRIPTION_MONITORING_ROLE in system_roles:
            ok = False
            findings.append(
                "system-assigned identity: forbidden Monitoring Contributor still present"
            )
        if expected_role_name not in system_roles and (
            _FORBIDDEN_SUBSCRIPTION_MONITORING_ROLE not in system_roles
        ):
            findings.append(
                "system-assigned identity: no subscription-scoped alert write role present"
            )

    if agent_rg_scope is not None:
        uami_rg_roles, uami_rg_result = azure_cli.role_assignments(
            agent_context.uami_principal_id, agent_rg_scope
        )
        if not uami_rg_result.ok:
            ok = False
            findings.append(f"UAMI: could not list agent-RG roles ({uami_rg_result.diagnostic()})")
        elif "Monitoring Reader" not in uami_rg_roles:
            ok = False
            findings.append("UAMI: missing Monitoring Reader on the agent resource group")
        else:
            findings.append("UAMI: has Monitoring Reader on the agent resource group")
    return CheckResult(
        "agent-rbac-alert-lifecycle", Status.PASS if ok else Status.FAIL, "; ".join(findings)
    )


def check_agent_admin_rbac(agent_context: ctx.AgentContext) -> CheckResult:
    """Verify "SRE Agent Administrator" RBAC on the agent resource itself.

    The deployer must hold this role (needed to manage the agent's data-plane
    content and to approve/deny pending actions). The agent's own UAMI must
    NOT hold this role. This was tested (PLAN.md Milestone 5) as a plausible
    fix for the Review-mode approval gate never visibly engaging on real
    incident-driven mutating actions, since "only SRE Agent Administrators
    can approve actions" (https://learn.microsoft.com/azure/sre-agent/permissions)
    made self-approval a reasonable hypothesis -- **live-tested 2026-07-29 and
    found insufficient alone**: a genuinely fresh Review-mode thread still
    executed the mutating write unattended even with this grant removed. The
    grant stays `false` by default as ordinary least-privilege practice (not
    as a claimed fix for the approval-gate behavior; tool-scoping is the
    demonstration's actual governance control -- see SPEC.md section 5 Scene
    5). `infra/modules/sre_agent`'s `grant_uami_agent_administrator` variable
    defaults to `false`; this check fails if that grant is ever present, so a
    future `terraform apply` that re-introduces it is caught immediately.
    """
    findings = []
    fail = False

    uami_roles, uami_result = azure_cli.role_assignments(
        agent_context.uami_principal_id, agent_context.agent_id
    )
    if not uami_result.ok:
        fail = True
        findings.append(f"UAMI: could not list agent-scope roles ({uami_result.diagnostic()})")
    elif "SRE Agent Administrator" in uami_roles:
        fail = True
        findings.append(
            "UAMI: SRE Agent Administrator present (self-approval risk -- see PLAN.md "
            "Milestone 5; set grant_uami_agent_administrator=false and redeploy)"
        )
    else:
        findings.append("UAMI: SRE Agent Administrator correctly absent (no self-approval path)")

    deployer_object_id, id_result = azure_cli.signed_in_object_id()
    if deployer_object_id is None:
        findings.append(
            "deployer: signed-in principal lookup unavailable "
            f"({id_result.diagnostic()}); live data-plane checks separately prove the current "
            "operator can administer agent content."
        )
    else:
        deployer_roles, deployer_result = azure_cli.role_assignments(
            deployer_object_id, agent_context.agent_id
        )
        if deployer_result.ok and "SRE Agent Administrator" in deployer_roles:
            findings.append("deployer: SRE Agent Administrator present")
        else:
            fail = True
            findings.append(
                f"deployer: SRE Agent Administrator missing ({deployer_result.diagnostic()})"
            )

    status = Status.FAIL if fail else Status.PASS
    return CheckResult("agent-rbac-admin", status, "; ".join(findings))


def check_agent_connectors(agent_context: ctx.AgentContext) -> CheckResult:
    connectors, result = agent_azure.connector_list(agent_context.agent_id)
    if connectors is None:
        return CheckResult(
            "agent-connectors", Status.FAIL, f"could not list connectors: {result.diagnostic()}"
        )
    states: dict[str, str] = {}
    for connector in connectors:
        name = str(connector.get("name", "")).rsplit("/", maxsplit=1)[-1]
        states[name] = agent_azure.provisioning_state(connector)

    detail = ", ".join(
        f"{name}={states.get(name, 'missing')}" for name in agent_azure.CONNECTOR_NAMES
    )
    missing = [name for name in agent_azure.CONNECTOR_NAMES if name not in states]
    if missing:
        # A missing connector is never a transient "still converging" state
        # -- there is nothing there to converge -- so it is always a
        # failure, distinct from a connector that exists but has not yet
        # reached a terminal provisioningState (see M4).
        return CheckResult(
            "agent-connectors", Status.FAIL, f"{detail} (missing: {', '.join(missing)})."
        )
    failed = [name for name in agent_azure.CONNECTOR_NAMES if states.get(name) == "Failed"]
    if failed:
        return CheckResult("agent-connectors", Status.FAIL, f"{detail}.")
    canceled = [name for name in agent_azure.CONNECTOR_NAMES if states.get(name) == "Canceled"]
    if canceled:
        return CheckResult("agent-connectors", Status.FAIL, f"{detail}.")
    converging = [name for name in agent_azure.CONNECTOR_NAMES if states.get(name) != "Succeeded"]
    if converging:
        return CheckResult(
            "agent-connectors",
            Status.WARN,
            f"{detail} (async provisioning can take 10-30 minutes; re-run `labctl verify` "
            "shortly if a connector is still converging).",
        )
    return CheckResult("agent-connectors", Status.PASS, f"{detail}.")


def check_agent_endpoints(
    agent_context: ctx.AgentContext, data: dict[str, object] | None
) -> CheckResult:
    """Assert the Terraform-reported data-plane endpoint (what every other
    check and `labctl provision`/`status` use) still equals ARM's own
    `properties.agentEndpoint` right now, not just at the last `terraform
    apply` (see M4)."""

    if data is None:
        return CheckResult("agent-endpoints", Status.FAIL, "agent resource unavailable.")
    properties = data.get("properties")
    properties_dict = properties if isinstance(properties, dict) else {}
    live_endpoint = properties_dict.get("agentEndpoint")
    detail = f"portal={agent_context.portal_url} data-plane={agent_context.data_plane_endpoint}"
    expected = agent_context.data_plane_endpoint
    live_normalized = str(live_endpoint).rstrip("/") if live_endpoint else ""
    expected_normalized = expected.rstrip("/")
    if not live_endpoint:
        return CheckResult(
            "agent-endpoints", Status.FAIL, f"{detail}; ARM reported no properties.agentEndpoint."
        )
    if live_normalized != expected_normalized:
        return CheckResult(
            "agent-endpoints",
            Status.FAIL,
            f"{detail}; ARM properties.agentEndpoint={live_endpoint!r} does not match.",
        )
    return CheckResult("agent-endpoints", Status.PASS, detail)


def check_agent_knowledge_graph_scope(
    agent_context: ctx.AgentContext,
    workload_context: ctx.WorkloadContext,
    data: dict[str, object] | None,
) -> CheckResult:
    """Assert `properties.knowledgeGraphConfiguration` grounds the agent in
    exactly the workload resource group (via the UAMI), matching
    infra/modules/sre_agent/main.tf (see M4)."""

    if data is None:
        return CheckResult(
            "agent-knowledge-graph-scope", Status.FAIL, "agent resource unavailable."
        )
    properties = data.get("properties")
    properties_dict = properties if isinstance(properties, dict) else {}
    kg = properties_dict.get("knowledgeGraphConfiguration")
    kg_dict = kg if isinstance(kg, dict) else {}
    identity = str(kg_dict.get("identity", ""))
    managed_resources = kg_dict.get("managedResources")
    managed_list = (
        [str(r) for r in managed_resources] if isinstance(managed_resources, list) else []
    )
    workload_rg_scope = _resource_group_scope(workload_context.container_app_id) or ""

    mismatches = []
    if identity.lower() != agent_context.uami_id.lower():
        mismatches.append(f"identity={identity!r} (expected UAMI {agent_context.uami_id!r})")
    if not any(r.lower() == workload_rg_scope.lower() for r in managed_list):
        mismatches.append(
            f"managedResources={managed_list!r} (expected to include {workload_rg_scope!r})"
        )
    if mismatches:
        return CheckResult("agent-knowledge-graph-scope", Status.FAIL, "; ".join(mismatches))
    return CheckResult(
        "agent-knowledge-graph-scope",
        Status.PASS,
        f"identity matches UAMI; managedResources includes {workload_rg_scope}.",
    )


def check_agent_action_identity(
    agent_context: ctx.AgentContext, data: dict[str, object] | None
) -> CheckResult:
    """Assert `properties.actionConfiguration.identity` is the agent's own
    UAMI, matching infra/modules/sre_agent/main.tf (see M4)."""

    if data is None:
        return CheckResult("agent-action-identity", Status.FAIL, "agent resource unavailable.")
    properties = data.get("properties")
    properties_dict = properties if isinstance(properties, dict) else {}
    action_configuration = properties_dict.get("actionConfiguration")
    action_dict = action_configuration if isinstance(action_configuration, dict) else {}
    identity = str(action_dict.get("identity", ""))
    if identity.lower() != agent_context.uami_id.lower():
        return CheckResult(
            "agent-action-identity",
            Status.FAIL,
            f"actionConfiguration.identity={identity!r} (expected UAMI {agent_context.uami_id!r})",
        )
    return CheckResult("agent-action-identity", Status.PASS, f"identity={identity}.")


def check_agent_not_deployed() -> CheckResult:
    return CheckResult(
        "sre-agent",
        Status.WARN,
        "Azure SRE Agent Terraform outputs were not found; run `labctl deploy --yes` to "
        "deploy it (see PLAN.md Milestone 3).",
    )


# --------------------------------------------------------------------------
# Azure SRE Agent data-plane content checks (Milestone 4: knowledge, skills,
# subagents, hooks, common prompts, scheduled tasks, incident platform,
# response plan, and GitHub source). Every check reads the live agent data
# plane (or, for the incident platform, the ARM resource) back -- it never
# trusts the local `agent/` content or the last `labctl provision` run's
# reported success (see AGENTS.md "avoid ... silent fallbacks" and PLAN.md
# Milestone 4 "Live gate").
# --------------------------------------------------------------------------


def load_expected_agent_content(config: Config) -> agent_content_mod.AgentContent | None:
    """Load `agent/` content for comparison against the live agent. Returns
    ``None`` if the directory is missing or malformed, in which case data-
    plane content checks are skipped with a WARN rather than a FAIL (a
    missing `agent/` directory is a repository problem, not necessarily an
    unprovisioned agent)."""

    try:
        return agent_content_mod.load_agent_content(config.repo_root)
    except agent_content_mod.AgentContentError:
        return None


def _name_set_result(name: str, expected: tuple[str, ...], actual: list[str]) -> CheckResult:
    expected_set = set(expected)
    actual_set = set(actual)
    missing = sorted(expected_set - actual_set)
    if missing:
        present = ", ".join(sorted(actual_set)) or "none"
        return CheckResult(
            name, Status.FAIL, f"missing: {', '.join(missing)} (present on agent: {present})."
        )
    return CheckResult(name, Status.PASS, f"present: {', '.join(sorted(actual_set)) or 'none'}.")


def get_data_plane_token_for_verify(
    agent_context: ctx.AgentContext,
) -> tuple[str | None, CheckResult]:
    token, result = agent_dataplane.get_data_plane_token()
    if token is None:
        return None, CheckResult(
            "agent-data-plane-token",
            Status.FAIL,
            f"could not acquire a data-plane token (audience "
            f"{agent_dataplane.DATA_PLANE_AUDIENCE}): {result.diagnostic()}",
        )
    del agent_context  # only used for a consistent call signature with other checks
    return token, CheckResult(
        "agent-data-plane-token",
        Status.PASS,
        f"acquired a token for audience {agent_dataplane.DATA_PLANE_AUDIENCE}.",
    )


def check_agent_incident_platform(
    agent_data: dict[str, object] | None, expected: agent_content_mod.IncidentPlatformContent | None
) -> CheckResult:
    if expected is None:
        return CheckResult(
            "agent-incident-platform", Status.WARN, "no expected incident platform content found."
        )
    actual = agent_azure.incident_platform_type(agent_data)
    if actual == expected.platform_type:
        return CheckResult("agent-incident-platform", Status.PASS, f"type={actual}.")
    return CheckResult(
        "agent-incident-platform",
        Status.FAIL,
        f"type={actual!r}, expected {expected.platform_type!r}.",
    )


def check_agent_knowledge(
    endpoint: str, token: str, expected: tuple[agent_content_mod.KnowledgeFileContent, ...]
) -> CheckResult:
    """Confirm every expected knowledge file is present. Deliberately does
    NOT fail (or even warn) if the live agent has *extra* files beyond
    `expected` -- a stray `probe-knowledge.md` test artifact uploaded while
    validating the multipart upload route by hand, before any provisioning
    code existed, remains on this agent (see M8 / PLAN.md Milestone 4:
    ``DELETE`` on every plausible AgentMemory route returned HTTP 405 and no
    delete route was found in the official template's own scripts either).
    `labctl provision` never re-creates it and only ever uploads the real
    files under `agent/knowledge/`, so this check only asserts subset
    presence, never exact-set equality.
    """

    items, result = agent_dataplane.list_knowledge_files(endpoint, token)
    if items is None:
        return CheckResult("agent-knowledge", Status.FAIL, f"could not list: {result.diagnostic()}")
    return _name_set_result(
        "agent-knowledge",
        tuple(k.filename for k in expected),
        [str(i.get("name", "")) for i in items],
    )


def check_agent_skills(
    endpoint: str, token: str, expected: tuple[agent_content_mod.SkillContent, ...]
) -> CheckResult:
    items, result = agent_dataplane.get_extended_items(endpoint, token, kind="skills")
    if items is None:
        return CheckResult("agent-skills", Status.FAIL, f"could not list: {result.diagnostic()}")
    return _name_set_result(
        "agent-skills", tuple(s.name for s in expected), [str(i.get("name", "")) for i in items]
    )


def check_agent_subagents(
    endpoint: str, token: str, expected: tuple[agent_content_mod.SubagentContent, ...]
) -> CheckResult:
    """Verify every expected subagent exists AND holds exactly its expected
    tool set.

    Tool scoping -- not the platform's Review-mode approval gate, which
    live testing (PLAN.md Milestone 5) proved does not reliably engage in
    this preview build -- is this demonstration's real, verified governance
    control (see SPEC.md section 5 Scene 5): `rollback-advisor` must hold
    `RunAzCliWriteCommands` (product-owner decision, 2026-07-30: it executes
    the real rollback itself) while `incident-investigator` must never hold
    it (it stays structurally read-only). A silent content drift here would
    quietly break that guarantee without any other check catching it, so
    this fails on any tool-set mismatch, not just a missing subagent name.
    """
    items, result = agent_dataplane.get_extended_items(endpoint, token, kind="agents")
    if items is None:
        return CheckResult("agent-subagents", Status.FAIL, f"could not list: {result.diagnostic()}")

    name_result = _name_set_result(
        "agent-subagents", tuple(s.name for s in expected), [str(i.get("name", "")) for i in items]
    )
    if name_result.status != Status.PASS:
        return name_result

    actual_by_name = {str(i.get("name", "")): i for i in items}
    mismatches: list[str] = []
    for subagent in expected:
        actual = actual_by_name.get(subagent.name) or {}
        properties_raw = actual.get("properties")
        properties = properties_raw if isinstance(properties_raw, dict) else {}
        actual_tools = set(properties.get("tools") or [])
        expected_tools = set(subagent.tools)
        if actual_tools != expected_tools:
            mismatches.append(
                f"{subagent.name}: tools={sorted(actual_tools)} (expected {sorted(expected_tools)})"
            )
    if mismatches:
        return CheckResult("agent-subagents", Status.FAIL, "; ".join(mismatches))

    write_holders = sorted(s.name for s in expected if "RunAzCliWriteCommands" in s.tools)
    return CheckResult(
        "agent-subagents",
        Status.PASS,
        f"present: {', '.join(sorted(actual_by_name))}; tool sets match "
        f"(RunAzCliWriteCommands scoped to: {', '.join(write_holders) or 'none'}).",
    )


def check_agent_hooks(
    endpoint: str, token: str, expected: tuple[agent_content_mod.HookContent, ...]
) -> CheckResult:
    items, result = agent_dataplane.get_extended_items(endpoint, token, kind="hooks")
    if items is None:
        return CheckResult("agent-hooks", Status.FAIL, f"could not list: {result.diagnostic()}")
    return _name_set_result(
        "agent-hooks", tuple(h.name for h in expected), [str(i.get("name", "")) for i in items]
    )


def check_agent_common_prompts(
    endpoint: str, token: str, expected: tuple[agent_content_mod.CommonPromptContent, ...]
) -> CheckResult:
    items, result = agent_dataplane.get_extended_items(endpoint, token, kind="commonprompts")
    if items is None:
        return CheckResult(
            "agent-common-prompts", Status.FAIL, f"could not list: {result.diagnostic()}"
        )
    return _name_set_result(
        "agent-common-prompts",
        tuple(p.name for p in expected),
        [str(i.get("name", "")) for i in items],
    )


def check_agent_scheduled_tasks(
    endpoint: str, token: str, expected: tuple[agent_content_mod.ScheduledTaskContent, ...]
) -> CheckResult:
    items, result = agent_dataplane.get_scheduled_tasks(endpoint, token)
    if items is None:
        return CheckResult(
            "agent-scheduled-tasks", Status.FAIL, f"could not list: {result.diagnostic()}"
        )
    return _name_set_result(
        "agent-scheduled-tasks",
        tuple(t.name for t in expected),
        [str(i.get("name", "")) for i in items],
    )


def check_agent_response_plans(
    endpoint: str, token: str, expected: tuple[agent_content_mod.IncidentFilterContent, ...]
) -> CheckResult:
    """Verify every expected response plan exists AND has the expected
    `agentMode`.

    `containerapp-5xx` must read `agentMode: Autonomous` -- product-owner
    decision, 2026-07-30 (see SPEC.md section 5 Scene 5 and PLAN.md
    Milestone 5): live testing proved this preview build's Review-mode
    Approve/Deny gate does not reliably engage before a mutating write
    executes, so configuring `Review` here would assert a safety property
    that is not actually true. This check fails if the live value ever
    drifts from what `agent/` declares, in either direction.
    """
    items, result = agent_dataplane.get_incident_filters(endpoint, token)
    if items is None:
        return CheckResult(
            "agent-response-plans", Status.FAIL, f"could not list: {result.diagnostic()}"
        )
    # This route's items key their name under either "id" or "name"
    # depending on build (see PLAN.md Milestone 4 "API/schema adaptations");
    # accept either.
    actual_names = [str(i.get("id") or i.get("name") or "") for i in items]
    name_result = _name_set_result(
        "agent-response-plans", tuple(f.name for f in expected), actual_names
    )
    if name_result.status != Status.PASS:
        return name_result

    actual_by_name = {str(i.get("id") or i.get("name") or ""): i for i in items}
    mismatches: list[str] = []
    for response_plan in expected:
        actual = actual_by_name.get(response_plan.name) or {}
        actual_mode = actual.get("agentMode")
        if actual_mode != response_plan.agent_mode:
            mismatches.append(
                f"{response_plan.name}: agentMode={actual_mode!r} "
                f"(expected {response_plan.agent_mode!r})"
            )
    if mismatches:
        return CheckResult("agent-response-plans", Status.FAIL, "; ".join(mismatches))
    return CheckResult(
        "agent-response-plans",
        Status.PASS,
        "present: "
        + ", ".join(f"{f.name} (agentMode={f.agent_mode})" for f in expected)
        + ". Autonomous is the honest, product-owner-decided label: Review-mode's "
        "Approve/Deny gate did not engage in this preview build (see SPEC.md section 5 "
        "Scene 5).",
    )


def check_agent_github_repo(endpoint: str, token: str, repository: str) -> CheckResult:
    repo_name = repository.split("/")[-1]
    items, result = agent_dataplane.get_repos(endpoint, token)
    if items is None:
        return CheckResult(
            "agent-github-repo", Status.FAIL, f"could not list: {result.diagnostic()}"
        )
    matching = next((i for i in items if i.get("name") == repo_name), None)
    if matching is None:
        present = ", ".join(str(i.get("name", "")) for i in items) or "none"
        return CheckResult(
            "agent-github-repo", Status.FAIL, f"repo {repo_name!r} not found (present: {present})."
        )
    matching_properties = matching.get("properties") if isinstance(matching, dict) else None
    actual_url = (matching_properties or {}).get("url")
    expected_url = f"https://github.com/{repository}"
    if actual_url != expected_url:
        return CheckResult(
            "agent-github-repo",
            Status.FAIL,
            f"repo {repo_name!r} present but url={actual_url!r}, expected {expected_url!r}.",
        )
    domains, domains_result = agent_dataplane.get_github_domains(endpoint, token)
    if domains is None:
        return CheckResult(
            "agent-github-repo",
            Status.WARN,
            f"repo {repo_name!r} present with the expected url, but could not confirm GitHub "
            f"domain authentication: {domains_result.diagnostic()}.",
        )
    if not any(d.get("name") == "github.com" for d in domains):
        return CheckResult(
            "agent-github-repo",
            Status.FAIL,
            f"repo {repo_name!r} present, but no github.com domain authentication is configured "
            "(see PLAN.md Milestone 4 'GitHub authorization').",
        )
    return CheckResult("agent-github-repo", Status.PASS, f"repo {repo_name!r}, url matches.")


def check_agent_data_plane_content(
    config: Config, agent_context: ctx.AgentContext, agent_data: dict[str, object] | None
) -> list[CheckResult]:
    """Live-read every Milestone 4 data-plane content kind and compare it
    against `agent/` (see :mod:`labctl.agent_content`). Returns one
    ``CheckResult`` per kind so callers can fold them into the same PASS/
    WARN/FAIL table as every other check.
    """

    expected = load_expected_agent_content(config)
    if expected is None:
        return [
            CheckResult(
                "sre-agent-data-plane",
                Status.WARN,
                f"`agent/` content directory not found or invalid under {config.repo_root}; "
                "skipping data-plane content checks.",
            )
        ]

    token, token_check = get_data_plane_token_for_verify(agent_context)
    if token is None:
        return [token_check]

    endpoint = agent_context.data_plane_endpoint
    results = [
        token_check,
        check_agent_incident_platform(agent_data, expected.incident_platform),
        check_agent_knowledge(endpoint, token, expected.knowledge_files),
        check_agent_skills(endpoint, token, expected.skills),
        check_agent_subagents(endpoint, token, expected.subagents),
        check_agent_hooks(endpoint, token, expected.hooks),
        check_agent_common_prompts(endpoint, token, expected.common_prompts),
        check_agent_scheduled_tasks(endpoint, token, expected.scheduled_tasks),
        check_agent_response_plans(endpoint, token, expected.incident_filters),
        check_agent_github_repo(endpoint, token, config.github.repository),
    ]
    return results


def summarize(results: list[CheckResult]) -> tuple[str, int]:
    counts = {Status.PASS: 0, Status.WARN: 0, Status.FAIL: 0}
    lines = []
    name_width = max((len(r.name) for r in results), default=4)
    for r in results:
        counts[r.status] += 1
        lines.append(f"[{r.status.value:<4}] {r.name.ljust(name_width)}  {r.detail}")
    summary = (
        f"\n{counts[Status.PASS]} passed, {counts[Status.WARN]} warned, "
        f"{counts[Status.FAIL]} failed."
    )
    exit_code = 1 if counts[Status.FAIL] else 0
    return "\n".join(lines) + summary, exit_code


def run_verify(config: Config, *, echo: Echo = print) -> int:
    _account, fatal_message = azure_cli.ensure_subscription_context(config)
    if _account is None:
        echo(f"error: {fatal_message}")
        return 2

    workload_context, result = ctx.load_workload_context(config)
    if workload_context is None:
        echo("error: could not read Terraform outputs. Has `labctl deploy` been run?")
        if result is not None:
            echo(result.redacted_stderr())
        return 1

    base_url = workload_context.endpoint_url()
    results: list[CheckResult] = [
        check_endpoint_health(base_url),
        check_checkout_behavior(base_url),
        check_revision_mode(workload_context),
        check_traffic_target(workload_context),
        check_metric_alert(workload_context),
        check_log_analytics_telemetry(workload_context),
        check_app_insights_telemetry(workload_context),
    ]

    agent_context, _agent_outputs_result = ctx.load_agent_context(config)
    if agent_context is None:
        results.append(check_agent_not_deployed())
    else:
        provisioning_result, agent_data = check_agent_provisioning(agent_context)
        results.append(provisioning_result)
        results.append(check_agent_running_state(agent_data))
        results.append(check_agent_identities(agent_context, agent_data))
        results.append(check_agent_configuration(config, agent_data))
        results.append(
            check_agent_knowledge_graph_scope(agent_context, workload_context, agent_data)
        )
        results.append(check_agent_action_identity(agent_context, agent_data))
        results.append(check_agent_workload_rbac(config, agent_context, workload_context))
        results.append(check_agent_alert_lifecycle_rbac(config, agent_context))
        results.append(check_agent_admin_rbac(agent_context))
        results.append(check_agent_connectors(agent_context))
        results.append(check_agent_endpoints(agent_context, agent_data))
        results.extend(check_agent_data_plane_content(config, agent_context, agent_data))

    table, exit_code = summarize(results)
    echo(table)
    return exit_code


__all__ = [
    "Status",
    "CheckResult",
    "check_endpoint_health",
    "check_checkout_behavior",
    "check_revision_mode",
    "check_traffic_target",
    "check_metric_alert",
    "check_log_analytics_telemetry",
    "check_app_insights_telemetry",
    "check_agent_provisioning",
    "check_agent_running_state",
    "check_agent_identities",
    "check_agent_configuration",
    "check_agent_knowledge_graph_scope",
    "check_agent_action_identity",
    "check_agent_workload_rbac",
    "check_agent_alert_lifecycle_rbac",
    "check_agent_admin_rbac",
    "check_agent_connectors",
    "check_agent_endpoints",
    "check_agent_not_deployed",
    "load_expected_agent_content",
    "get_data_plane_token_for_verify",
    "check_agent_incident_platform",
    "check_agent_knowledge",
    "check_agent_skills",
    "check_agent_subagents",
    "check_agent_hooks",
    "check_agent_common_prompts",
    "check_agent_scheduled_tasks",
    "check_agent_response_plans",
    "check_agent_github_repo",
    "check_agent_data_plane_content",
    "summarize",
    "run_verify",
]
