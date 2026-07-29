"""`labctl deploy` orchestration: Terraform apply, Azure SRE Agent readiness,
ACR cloud build, Container Apps baseline revision, warm-up, and workload
verification (see SPEC.md section 8 "Deployment sequence" and AGENTS.md
"`labctl deploy` owns the complete clean deployment path").
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from labctl import agent_azure, terraform_cli, tfvars, workload_azure
from labctl import context as ctx
from labctl import image as image_mod
from labctl.azure_cli import ensure_subscription_context
from labctl.config import Config
from labctl.http_client import get as http_get
from labctl.http_client import post as http_post
from labctl.provision import run_provision
from labctl.state import DeploymentState, save_deployment_state
from labctl.verify import run_verify

Echo = Callable[[str], None]

APP_DIR_NAME = "app"
IMAGE_REPOSITORY = "pulsemart"
TARGET_PORT = 8000
PLAN_FILENAME = "demo.tfplan"

# `terraform apply` itself waits up to 10 minutes per connector (see
# infra/modules/sre_agent's `connector_timeout`). Give the whole apply
# command enough headroom to observe that timeout cleanly as a normal
# nonzero exit rather than being killed mid-flight by our own subprocess
# timeout (see SPEC.md section 11).
AGENT_APPLY_TIMEOUT = 1500.0

# Markers that identify the documented, tolerated "connector still
# provisioning in the background" timeout from a real `terraform apply`
# failure. Re-verify these substrings against the actual error text the
# azapi provider produces once this has been exercised against a live
# subscription (see PLAN.md Milestone 3 "Known risks"); tighten or widen the
# heuristic based on what is actually observed.
_TOLERABLE_TIMEOUT_MARKERS = ("context deadline exceeded", "timeout while waiting")

#: Incident management platform this demo routes to the agent (matches
#: agent/automations/incident-platforms/azure-monitor.yaml's `platformType`).
#: Reconciled by `labctl deploy` itself, not Terraform (see B1 fix below and
#: docs/adr/0001-incident-platform-reconciliation.md).
INCIDENT_PLATFORM_TYPE = "AzMonitor"


@dataclass(frozen=True, slots=True)
class DeployResult:
    exit_code: int
    context: ctx.WorkloadContext | None = None


def _reconcile_incident_platform(agent_context: ctx.AgentContext, echo: Echo) -> bool:
    """PATCH `properties.incidentManagementConfiguration` back to
    :data:`INCIDENT_PLATFORM_TYPE` on every `labctl deploy` run (B1 fix).

    `azapi_resource`'s PUT semantics replace the agent's entire `properties`
    object on every apply that touches any other field (verified live
    2026-07-29), so this field -- which ARM only accepts through a real PATCH,
    not a PUT -- was silently reset to null by an unrelated Terraform change.
    A Terraform-native fix (`azapi_update_resource`) was tried and rejected:
    it failed live with ARM error `MismatchingResourceIdentityPrincipalId`
    because it performs a read-merge-PUT that echoes back this agent's
    read-only system-assigned identity `principalId` (see
    docs/adr/0001-incident-platform-reconciliation.md). Doing the real PATCH
    here instead, unconditionally and idempotently on every deploy, is the
    option this repository chose. `labctl provision` never PATCHes this
    field itself; it only reads it back to confirm this step already
    configured it, so there is exactly one writer.
    """

    agent_data, _show_result = agent_azure.agent_show(agent_context.agent_id)
    current = agent_azure.incident_platform_type(agent_data)
    if current == INCIDENT_PLATFORM_TYPE:
        echo(f"  incidentManagementConfiguration.type already {INCIDENT_PLATFORM_TYPE}.")
        return True
    _patched, patch_result = agent_azure.set_incident_platform(
        agent_context.agent_id, platform_type=INCIDENT_PLATFORM_TYPE
    )
    if not patch_result.ok:
        diag = patch_result.diagnostic()
        echo(f"  error: ARM PATCH incidentManagementConfiguration failed: {diag}")
        echo(patch_result.redacted_stderr())
        return False
    echo(f"  ok: ARM PATCH incidentManagementConfiguration -> {INCIDENT_PLATFORM_TYPE}")
    return True


def _plan_action_counts(cwd: Any, plan_path: Any) -> tuple[dict[str, int] | None, str]:
    """Return per-action resource-change counts from a saved plan file, or
    ``None`` if the plan could not be summarized (with a diagnostic
    string)."""

    result = terraform_cli.show_plan_json(cwd, plan_file=plan_path)
    if not result.ok:
        return None, result.diagnostic()
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"could not parse plan JSON: {exc}"
    changes = data.get("resource_changes", [])
    actions: dict[str, int] = {}
    for change in changes:
        for action in change.get("change", {}).get("actions", ["no-op"]):
            actions[action] = actions.get(action, 0) + 1
    return actions, ""


def _summarize_plan(cwd: Any, plan_path: Any, echo: Echo) -> None:
    actions, error = _plan_action_counts(cwd, plan_path)
    if actions is None:
        echo(f"  (could not summarize plan: {error})")
        return
    non_noop = {k: v for k, v in actions.items() if k != "no-op"}
    if not non_noop:
        echo("  no changes.")
        return
    summary = ", ".join(f"{count} to {action}" for action, count in sorted(non_noop.items()))
    echo(f"  {summary}.")


def _is_tolerable_connector_timeout(result: Any) -> bool:
    """Detect the documented, tolerated case where `terraform apply` itself
    times out waiting for an agent connector to finish its asynchronous
    provisioning (which can legitimately take 10-30 minutes; see SPEC.md
    section 11). Any other apply failure is treated as a hard failure.
    """

    text = result.redacted_stderr().lower()
    mentions_connector = "connector" in text or "agents/connectors" in text
    return mentions_connector and any(marker in text for marker in _TOLERABLE_TIMEOUT_MARKERS)


def _reconcile_after_connector_timeout(
    config: Config,
    tf_cwd: Any,
    tfvars_path: Any,
    agent_context: ctx.AgentContext,
    echo: Echo,
) -> bool:
    """Real reconciliation after a tolerated `terraform apply` connector
    timeout (M3 fix): poll Azure directly until every connector reaches a
    terminal state, re-run `terraform apply` so Terraform's own state
    reflects what Azure actually has (a client-side apply timeout can leave
    the connector resource entirely missing from Terraform state even
    though Azure finished creating it), and require a final no-op
    `terraform plan` before reporting success -- matching SPEC.md section
    11's contract precisely instead of just polling ARM and hoping state
    already agrees.
    """

    echo("  polling Azure directly until every connector reaches a terminal state...")
    all_terminal = True
    for name in agent_azure.CONNECTOR_NAMES:
        state, _data, result = agent_azure.wait_for_connector_provisioned(
            agent_context.agent_id, name
        )
        echo(f"    connector '{name}': {state}")
        if state != "Succeeded":
            echo(f"      {result.diagnostic()}")
            all_terminal = False
    if not all_terminal:
        echo(
            "  error: at least one connector did not reach Succeeded within its bounded "
            "deadline; cannot reconcile Terraform state against an unfinished Azure resource."
        )
        return False

    echo("  re-running `terraform apply` so Terraform's own state reflects Azure...")
    reconcile_plan_path = config.terraform_state_path() / f"reconcile-{PLAN_FILENAME}"
    reconcile_plan_result = terraform_cli.plan(
        tf_cwd, var_file=tfvars_path, out_file=reconcile_plan_path, timeout=300.0
    )
    if not reconcile_plan_result.ok:
        echo(
            f"  error: reconciliation `terraform plan` failed: {reconcile_plan_result.diagnostic()}"
        )
        echo(reconcile_plan_result.redacted_stderr())
        return False
    reconcile_apply_result = terraform_cli.apply(
        tf_cwd, plan_file=reconcile_plan_path, timeout=AGENT_APPLY_TIMEOUT
    )
    if not reconcile_apply_result.ok:
        diag = reconcile_apply_result.diagnostic()
        echo(f"  error: reconciliation `terraform apply` failed: {diag}")
        echo(reconcile_apply_result.redacted_stderr())
        return False

    echo("  requiring a final no-op plan to confirm Terraform state now matches Azure...")
    final_plan_path = config.terraform_state_path() / f"final-{PLAN_FILENAME}"
    final_plan_result = terraform_cli.plan(
        tf_cwd, var_file=tfvars_path, out_file=final_plan_path, timeout=300.0
    )
    if not final_plan_result.ok:
        echo(f"  error: final `terraform plan` failed: {final_plan_result.diagnostic()}")
        echo(final_plan_result.redacted_stderr())
        return False
    actions, error = _plan_action_counts(tf_cwd, final_plan_path)
    if actions is None:
        echo(f"  error: could not confirm the final plan is a no-op: {error}")
        return False
    non_noop = {k: v for k, v in actions.items() if k != "no-op"}
    if non_noop:
        summary = ", ".join(f"{count} to {action}" for action, count in sorted(non_noop.items()))
        echo(
            f"  error: final plan is not a no-op ({summary}); Terraform state does not yet "
            "match Azure after reconciliation."
        )
        return False
    echo("  ok: final plan is a no-op; Terraform state is reconciled with Azure.")
    return True


def _wait_for_agent(agent_context: ctx.AgentContext, echo: Echo) -> bool:
    """Poll the agent resource, then every connector, to a terminal
    provisioning state. Returns ``True`` only when the agent resource itself
    reached ``Succeeded`` and every connector reached ``Succeeded`` within
    its bounded deadline (see SPEC.md section 11: "fails only when a
    connector reports failure or misses that deadline"; M4: a deadline-
    expired or otherwise non-Succeeded terminal agent provisioning state is
    also a real failure, not a warning).
    """

    echo(f"  agent: {agent_context.agent_name}")
    state, _data, result = agent_azure.wait_for_agent_provisioned(agent_context.agent_id)
    all_ok = True
    if state == "Succeeded":
        echo("  agent provisioningState=Succeeded")
    else:
        echo(
            f"  error: agent provisioningState={state} ({result.diagnostic()}) -- expected "
            "Succeeded within the bounded wait. Re-run `labctl verify` for a detailed check, "
            "and `labctl deploy --yes` again once the underlying issue is fixed (idempotent)."
        )
        all_ok = False

    for name in agent_azure.CONNECTOR_NAMES:
        echo(f"  connector '{name}': waiting for provisioning (can take 10-30 minutes)...")
        c_state, _c_data, c_result = agent_azure.wait_for_connector_provisioned(
            agent_context.agent_id, name
        )
        if c_state == "Succeeded":
            echo("    -> Succeeded")
        elif c_state == "Failed":
            echo(f"    -> FAILED: {c_result.diagnostic()}")
            all_ok = False
        else:
            echo(
                f"    -> still {c_state!r} after the bounded wait, exceeding the connector's "
                "documented 10-30 minute async provisioning window (see SPEC.md section 11)."
            )
            all_ok = False
    return all_ok


def run_deploy(
    config: Config,
    *,
    yes: bool,
    plan_only: bool = False,
    skip_build: bool = False,
    echo: Echo = print,
) -> DeployResult:
    tf_cwd = ctx.terraform_cwd(config)
    account, fatal_message = ensure_subscription_context(config)
    if account is None:
        echo(f"error: {fatal_message}")
        return DeployResult(2)

    echo(
        f"Subscription: {account.subscription_name} ({account.subscription_id})\n"
        f"Tenant: {account.tenant_id}\n"
        f"Resource groups: {config.resource_groups.agent}, {config.resource_groups.workload}\n"
        f"Region: {config.azure.region}\n\n"
        "Cost notice: a deployed Azure SRE Agent bills a fixed 4 Azure Agent Units per "
        "agent-hour always-on from the moment it is created until `labctl destroy` deletes "
        f"it (monthly cap: {config.agent.monthly_aau_allocation} AAU) -- independent of "
        "whether it is actively investigating anything (see SPEC.md section 14)."
    )

    tfvars_path = tfvars.write_tfvars(config)

    echo("\n[1/10] terraform init")
    init_result = terraform_cli.init_backend(tf_cwd)
    if not init_result.ok:
        echo(f"error: terraform init failed: {init_result.diagnostic()}")
        echo(init_result.redacted_stderr())
        return DeployResult(1)

    echo("[2/10] terraform plan")
    plan_path = config.terraform_state_path() / PLAN_FILENAME
    plan_result = terraform_cli.plan(tf_cwd, var_file=tfvars_path, out_file=plan_path)
    if not plan_result.ok:
        echo(f"error: terraform plan failed: {plan_result.diagnostic()}")
        echo(plan_result.redacted_stderr())
        return DeployResult(1)
    _summarize_plan(tf_cwd, plan_path, echo)

    if plan_only:
        echo("\n--plan-only: no changes applied. Re-run with --yes to apply.")
        return DeployResult(0)

    if not yes:
        echo(
            "\nRefusing to apply without confirmation. Re-run with --yes to create/update the "
            "resources listed above (this makes real, billable Azure changes)."
        )
        return DeployResult(2)

    echo("[3/10] terraform apply")
    apply_result = terraform_cli.apply(tf_cwd, plan_file=plan_path, timeout=AGENT_APPLY_TIMEOUT)
    connector_timeout_tolerated = False
    if not apply_result.ok:
        if _is_tolerable_connector_timeout(apply_result):
            echo(
                "  warning: terraform apply timed out waiting for one or more Azure SRE Agent "
                "connectors to finish provisioning. This is documented, expected behavior: "
                "connector PUTs are asynchronous and can take 10-30 minutes in the background "
                "(see SPEC.md section 11). Continuing and polling Azure directly for the real "
                "outcome, then reconciling Terraform state and requiring a final no-op plan "
                "before reporting success."
            )
            connector_timeout_tolerated = True
        else:
            echo(f"error: terraform apply failed: {apply_result.diagnostic()}")
            echo(apply_result.redacted_stderr())
            echo(
                "Terraform state may be partially applied. Run `terraform -chdir="
                f"{tf_cwd} show` to inspect it, then re-run `labctl deploy --yes` "
                "(idempotent) once the underlying issue is fixed."
            )
            return DeployResult(1)

    workload_context, outputs_result = ctx.load_workload_context(config)
    if workload_context is None:
        echo("error: terraform apply succeeded but workload outputs are incomplete.")
        if outputs_result is not None:
            echo(outputs_result.redacted_stderr())
        return DeployResult(1)

    agent_context, agent_outputs_result = ctx.load_agent_context(config)
    if agent_context is None:
        echo("error: terraform apply succeeded but Azure SRE Agent outputs are incomplete.")
        if agent_outputs_result is not None:
            echo(agent_outputs_result.redacted_stderr())
        return DeployResult(1)

    if connector_timeout_tolerated:
        echo("Reconciling Terraform state after the tolerated connector timeout...")
        if not _reconcile_after_connector_timeout(config, tf_cwd, tfvars_path, agent_context, echo):
            return DeployResult(1)

    echo("[4/10] reconciling incident platform (ARM PATCH; see B1)")
    if not _reconcile_incident_platform(agent_context, echo):
        return DeployResult(1)

    echo("[5/10] computing deterministic image tag")
    app_dir = config.repo_root / APP_DIR_NAME
    image_tag = image_mod.compute_image_tag(config.repo_root, app_dir)
    image_ref = f"{workload_context.container_registry_login_server}/{IMAGE_REPOSITORY}:{image_tag}"
    echo(f"  image tag: {image_tag}")

    if skip_build:
        echo("[6/10] skipping ACR build (--skip-build)")
    else:
        existing_tags, _ = workload_azure.acr_repository_show_tags(
            workload_context.container_registry_name, IMAGE_REPOSITORY
        )
        if existing_tags is not None and image_tag in existing_tags:
            echo(f"[6/10] image {image_tag} already exists in {IMAGE_REPOSITORY}; skipping build")
        else:
            echo("[6/10] az acr build (this can take a few minutes)")
            build_result = workload_azure.acr_build(
                workload_context.container_registry_name,
                [f"{IMAGE_REPOSITORY}:{image_tag}", f"{IMAGE_REPOSITORY}:latest"],
                app_dir,
            )
            if not build_result.ok:
                echo(f"error: az acr build failed: {build_result.diagnostic()}")
                echo(build_result.redacted_stderr()[-4000:])
                return DeployResult(1)

    echo("[7/10] updating Container App to the immutable image")
    revision_suffix = f"baseline-{image_tag}"[:63]
    revision_name = f"{workload_context.container_app_name}--{revision_suffix}"

    existing_revisions, _ = workload_azure.containerapp_revision_list(
        workload_context.container_app_name, workload_context.workload_resource_group
    )
    revision_exists = any(r.get("name") == revision_name for r in existing_revisions or [])

    if revision_exists:
        echo(f"  revision {revision_name} already exists; skipping image update")
    else:
        env_vars = {
            # `secretref:` points at the Container App secret Terraform
            # already manages (see infra/modules/container_app's `secret`
            # block, name "app-insights-connection-string"), instead of
            # passing the connection string as a literal value here. A
            # literal value would appear both in this process's own
            # argument list (visible to anything that can read process
            # arguments on this machine) and in the resulting revision's
            # ARM configuration/history forever after; `secretref:` puts
            # neither the secret's name resolution nor its value through
            # this call (see AGENTS.md "avoid ... logging ... secret
            # values").
            "APPLICATIONINSIGHTS_CONNECTION_STRING": (
                f"secretref:{workload_azure.APP_INSIGHTS_CONNECTION_STRING_SECRET_NAME}"
            ),
            "PULSEMART_RELEASE": image_tag,
            "PULSEMART_ENVIRONMENT": config.tags.environment,
            "DEMO_FAILURE_MODE": "",
        }
        update_result = workload_azure.containerapp_update_image(
            workload_context.container_app_name,
            workload_context.workload_resource_group,
            image=image_ref,
            revision_suffix=revision_suffix,
            env_vars=env_vars,
        )
        if not update_result.ok:
            echo(f"error: az containerapp update failed: {update_result.diagnostic()}")
            echo(update_result.redacted_stderr())
            return DeployResult(1)

    ingress_result = workload_azure.containerapp_ingress_update(
        workload_context.container_app_name,
        workload_context.workload_resource_group,
        target_port=TARGET_PORT,
    )
    if not ingress_result.ok:
        echo(f"error: az containerapp ingress update failed: {ingress_result.diagnostic()}")
        echo(ingress_result.redacted_stderr())
        return DeployResult(1)

    traffic_result = workload_azure.containerapp_ingress_traffic_set(
        workload_context.container_app_name,
        workload_context.workload_resource_group,
        {revision_name: 100},
    )
    if not traffic_result.ok:
        echo(f"error: az containerapp ingress traffic set failed: {traffic_result.diagnostic()}")
        echo(traffic_result.redacted_stderr())
        return DeployResult(1)

    git_commit = image_mod.git_commit_short(config.repo_root)
    save_deployment_state(
        config,
        DeploymentState(
            image_tag=image_tag,
            image_ref=image_ref,
            baseline_revision_suffix=revision_suffix,
            baseline_revision_name=revision_name,
            deployed_at=datetime.now(UTC).isoformat(),
            git_commit=git_commit,
            terraform_outputs=workload_context.non_sensitive_dict(),
        ),
    )

    echo("[8/10] Azure SRE Agent: waiting for provisioning to reach a terminal state")
    agent_ok = _wait_for_agent(agent_context, echo)

    echo("[9/10] provisioning agent data-plane content (idempotent; see labctl.provision)")
    provision_result = run_provision(config, echo=echo)
    if provision_result.exit_code != 0:
        echo(
            "  warning: `labctl provision` reported failures (see FAIL lines above). "
            "`labctl deploy` still continues to warm-up/verify; re-run `labctl provision` "
            "once the underlying issue is fixed."
        )
    agent_ok = agent_ok and provision_result.exit_code == 0

    echo("[10/10] warming the application and verifying")
    _warm(workload_context, echo)

    verify_exit_code = run_verify(config, echo=echo)
    exit_code = verify_exit_code if agent_ok else max(verify_exit_code, 1)
    return DeployResult(exit_code, workload_context)


def _warm(workload_context: ctx.WorkloadContext, echo: Echo) -> None:
    url = workload_context.endpoint_url()
    health = http_get(f"{url}/healthz", timeout=10.0, retries=12, retry_delay=5.0)
    if not health.ok:
        echo(f"  warning: {url}/healthz did not respond after warm-up retries: {health.error}")
        return
    echo(f"  {url}/healthz -> HTTP {health.status_code}")
    checkout = http_post(f"{url}/api/checkout", timeout=15.0, retries=2)
    if checkout.ok:
        echo(f"  {url}/api/checkout -> HTTP {checkout.status_code}")


__all__ = ["DeployResult", "run_deploy"]
