"""`labctl destroy`: confirm ownership, destroy Terraform-owned resources,
and verify deletion (see SPEC.md section 11 and AGENTS.md "Keep destructive
scope limited to resources created by this repository" / "Every destructive
operation checks repository ownership tags and exact resource IDs before
execution").

Since Milestone 3, the same Terraform state also owns the Azure SRE Agent
(identities, telemetry, connectors, and RBAC); `terraform destroy` removes it
together with the workload resource group in one pass. The agent incurs
always-on Azure Agent Unit cost until it is deleted (see SPEC.md section 14),
so `labctl destroy` is the normal end of every rehearsal.

Ownership verification (B3 fix, see AGENTS.md/SPEC.md section 11):

1. All four ownership tags (repository, environment, owner, deployment_id) --
   not just three -- must be present and match `config.local.toml` on both
   resource groups.
2. A blank or placeholder-looking `deployment_id` (e.g. "change-me", "todo")
   refuses outright, since it cannot prove exclusive ownership of anything.
3. The resource groups' exact ARM IDs are checked against Terraform's own
   state (via the `agent_resource_group_id`/`workload_resource_group_id`
   root outputs), not just resource *names* -- a same-named resource group
   recreated outside Terraform would have a different ID.
4. Every child resource directly inside each resource group is enumerated
   and must itself carry matching tags, be a recognized child/proxy
   resource of one that does (e.g. an Azure SRE Agent connector, whose own
   ARM type never carries independent tags), or be a recognized Azure
   platform companion resource (e.g. Application Insights' automatic
   "Failure Anomalies" Smart Detector alert rule, which Azure creates
   without tags and cannot be disabled). Anything else blocks the destroy
   with the resource's exact ID printed, unless the operator passes
   `--allow-unrecognized-resources` after reviewing that list.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from labctl import context as ctx
from labctl import terraform_cli, tfvars
from labctl.azure_cli import (
    ResourceSummary,
    ensure_subscription_context,
    is_not_found,
    resource_group_show,
    resource_list,
)
from labctl.config import Config
from labctl.deploy import PLAN_FILENAME
from labctl.state import DEPLOYMENT_STATE_FILENAME

Echo = Callable[[str], None]

#: Deployment IDs that indicate the operator never customized
#: `config.local.toml` and so cannot prove exclusive ownership of anything
#: (see AGENTS.md "Every destructive operation checks repository ownership
#: tags and exact resource IDs before execution"). "local" is deliberately
#: NOT here: it is this repository's own documented default for an
#: operator-run rehearsal (see config.example.toml), not a placeholder.
_PLACEHOLDER_DEPLOYMENT_IDS: frozenset[str] = frozenset(
    {
        "",
        "change-me",
        "changeme",
        "todo",
        "replace-me",
        "replaceme",
        "tbd",
        "xxx",
        "sample",
        "unset",
        "default",
    }
)

#: The four tags every owned resource is expected to carry (see AGENTS.md
#: "Tag every Azure resource with repository, environment, owner, and
#: deployment identity metadata").
_OWNERSHIP_TAG_KEYS: tuple[str, ...] = ("repository", "environment", "owner", "deployment_id")


@dataclass(frozen=True, slots=True)
class DestroyResult:
    exit_code: int


def _expected_tags(config: Config) -> dict[str, str]:
    return {
        "repository": config.tags.repository,
        "environment": config.tags.environment,
        "owner": config.tags.owner,
        "deployment_id": config.tags.deployment_id,
    }


def _reject_placeholder_deployment_id(config: Config, echo: Echo) -> bool:
    deployment_id = config.tags.deployment_id.strip().lower()
    if deployment_id in _PLACEHOLDER_DEPLOYMENT_IDS:
        echo(
            f"error: tags.deployment_id={config.tags.deployment_id!r} in config.local.toml looks "
            "like a placeholder that was never customized. Refusing to destroy: a placeholder "
            "value cannot prove exclusive ownership of anything. Set a real deployment_id and "
            "re-run `labctl deploy --yes` before destroying (see AGENTS.md)."
        )
        return False
    return True


def _tags_match(
    tags: dict[str, str], expected: dict[str, str]
) -> dict[str, tuple[str | None, str]]:
    return {k: (tags.get(k), v) for k, v in expected.items() if tags.get(k) != v}


def _check_resource_group_tags(config: Config, echo: Echo) -> bool:
    """Refuse to proceed if either resource group exists but does not carry
    all four expected ownership tags. A missing resource group is not an
    ownership failure (there is simply nothing to destroy yet)."""

    ok = True
    expected = _expected_tags(config)
    for rg_name in (config.resource_groups.agent, config.resource_groups.workload):
        data, result = resource_group_show(rg_name)
        if data is None:
            if is_not_found(result):
                echo(f"  {rg_name}: not found (nothing to destroy).")
            else:
                echo(
                    f"  {rg_name}: could not query resource group ({result.diagnostic()}); "
                    'treating this as a failure, not "nothing to destroy".'
                )
                ok = False
            continue
        tags = {str(k): str(v) for k, v in (data.get("tags") or {}).items()}
        mismatches = _tags_match(tags, expected)
        if mismatches:
            details = ", ".join(
                f"{key}: found {found!r}, expected {want!r}"
                for key, (found, want) in mismatches.items()
            )
            echo(f"  {rg_name}: tag mismatch, refusing to destroy ({details}).")
            ok = False
        else:
            echo(f"  {rg_name}: all four ownership tags match ({', '.join(_OWNERSHIP_TAG_KEYS)}).")
    return ok


def _check_resource_group_ids(config: Config, echo: Echo) -> bool:
    """Verify the exact resource-group IDs Azure reports match Terraform's
    own state (via the root `agent_resource_group_id`/
    `workload_resource_group_id` outputs), not just resource names. A
    resource group recreated outside Terraform with the same name would
    have a different ID and must never be treated as owned."""

    rg_ids, result = ctx.load_resource_group_ids(config)
    if rg_ids is None:
        echo(
            "  could not read agent_resource_group_id/workload_resource_group_id from Terraform "
            f"outputs ({result.diagnostic() if result is not None else 'no Terraform state'}); "
            "nothing to verify IDs against (if resource groups do not exist, this is expected)."
        )
        return True

    ok = True
    for rg_name, expected_id in (
        (config.resource_groups.agent, rg_ids.agent_resource_group_id),
        (config.resource_groups.workload, rg_ids.workload_resource_group_id),
    ):
        data, azure_result = resource_group_show(rg_name)
        if data is None:
            continue  # already reported by _check_resource_group_tags
        actual_id = str(data.get("id", ""))
        if actual_id.lower() != expected_id.lower():
            echo(
                f"  {rg_name}: ARM resource ID {actual_id!r} does not match Terraform state's "
                f"{expected_id!r}. Refusing to destroy: this resource group was not created by "
                f"this Terraform state ({azure_result.diagnostic()})."
            )
            ok = False
        else:
            echo(f"  {rg_name}: ARM resource ID matches Terraform state ({actual_id}).")
    return ok


def _is_recognized_child(resource: ResourceSummary, owned_id_prefixes: list[str]) -> bool:
    """A resource with no independent tags of its own (or mismatched ones)
    is still recognized as owned if it is a child/proxy resource of one
    that IS tagged correctly -- for example an Azure SRE Agent connector
    (`Microsoft.App/agents/connectors`), which never carries independent
    tags. Detected by ID prefix: a child resource's ID always starts with
    its parent's ID followed by `/`.
    """

    return any(
        resource.id.lower() != prefix.lower()
        and resource.id.lower().startswith(prefix.lower() + "/")
        for prefix in owned_id_prefixes
    )


#: Azure automatically creates one "Failure Anomalies" Smart Detector alert
#: rule per Application Insights component the instant the component is
#: created -- it cannot be disabled, tagged at creation, or otherwise
#: attributed to the Terraform run that (indirectly) caused it, and it is
#: not a child resource by ID (its ID is a sibling in the resource group,
#: not nested under the Application Insights component's ID). Live-observed
#: 2026-07-29 in both `rg-sre-agent-demo` and `rg-sre-agent-workload-demo`.
#: Recognized here by name convention rather than trusted blindly by type
#: alone, since the alert is only genuinely "ours" if it names an
#: Application Insights component this deployment actually owns.
_SMART_DETECTOR_ALERT_TYPE = "microsoft.alertsmanagement/smartdetectoralertrules"
_APP_INSIGHTS_COMPONENT_TYPE = "microsoft.insights/components"


def _is_recognized_platform_companion(
    resource: ResourceSummary, owned_resources: list[ResourceSummary]
) -> bool:
    if resource.type.lower() != _SMART_DETECTOR_ALERT_TYPE:
        return False
    name = resource.id.rsplit("/", maxsplit=1)[-1]
    owned_app_insights_names = {
        r.id.rsplit("/", maxsplit=1)[-1]
        for r in owned_resources
        if r.type.lower() == _APP_INSIGHTS_COMPONENT_TYPE
    }
    return any(name == f"Failure Anomalies - {ai_name}" for ai_name in owned_app_insights_names)


def _check_resource_group_contents(config: Config, echo: Echo, *, allow_unrecognized: bool) -> bool:
    """Enumerate every resource directly inside each owned resource group
    and refuse to proceed if any resource is neither tagged as owned, a
    recognized child of one that is, nor a recognized Azure platform
    companion resource (see module docstring point 4)."""

    expected = _expected_tags(config)
    ok = True
    for rg_name in (config.resource_groups.agent, config.resource_groups.workload):
        group_data, group_result = resource_group_show(rg_name)
        if group_data is None:
            continue  # already reported by _check_resource_group_tags

        resources, result = resource_list(rg_name)
        if resources is None:
            echo(f"  {rg_name}: could not enumerate resources ({result.diagnostic()}).")
            ok = False
            continue
        if not resources:
            echo(f"  {rg_name}: no child resources to check (empty).")
            continue

        owned_resources = [r for r in resources if not _tags_match(r.tags, expected)]
        owned_ids = [r.id for r in owned_resources]
        unrecognized = [
            r
            for r in resources
            if _tags_match(r.tags, expected)
            and not _is_recognized_child(r, owned_ids)
            and not _is_recognized_platform_companion(r, owned_resources)
        ]
        echo(
            f"  {rg_name}: {len(resources)} resource(s) enumerated, "
            f"{len(unrecognized)} unrecognized."
        )
        if unrecognized:
            for r in unrecognized:
                echo(f"    UNRECOGNIZED: {r.id} (type={r.type}, tags={r.tags or {}})")
            if allow_unrecognized:
                echo(
                    "  --allow-unrecognized-resources set: proceeding despite the resource(s) "
                    "above. This is an explicit operator override; verify manually that they "
                    "are safe to destroy."
                )
            else:
                echo(
                    "  refusing to destroy: the resource(s) above do not carry this "
                    "deployment's ownership tags and are not recognized children of one that "
                    "does. Investigate manually, or pass --allow-unrecognized-resources to "
                    "`labctl destroy` once you have confirmed they are safe to remove."
                )
                ok = False
        del group_result
    return ok


def run_destroy(
    config: Config,
    *,
    yes: bool,
    plan_only: bool = False,
    allow_unrecognized_resources: bool = False,
    echo: Echo = print,
) -> DestroyResult:
    tf_cwd = ctx.terraform_cwd(config)

    account, fatal_message = ensure_subscription_context(config)
    if account is None:
        echo(f"error: {fatal_message}")
        return DestroyResult(2)

    echo("Checking ownership before any destructive operation:")
    if not _reject_placeholder_deployment_id(config, echo):
        return DestroyResult(2)

    tags_ok = _check_resource_group_tags(config, echo)
    ids_ok = _check_resource_group_ids(config, echo)
    contents_ok = _check_resource_group_contents(
        config, echo, allow_unrecognized=allow_unrecognized_resources
    )
    if not (tags_ok and ids_ok and contents_ok):
        echo(
            "error: refusing to destroy; ownership could not be fully verified. See the "
            "messages above and investigate manually before retrying."
        )
        return DestroyResult(2)
    echo(
        "Ownership verified: all four tags, exact resource-group IDs, and every enumerated "
        "child resource are accounted for."
    )

    agent_context, _agent_result = ctx.load_agent_context(config)
    if agent_context is not None:
        echo(
            f"Note: Azure SRE Agent '{agent_context.agent_name}' is deployed and incurs "
            "always-on Azure Agent Unit cost until it is deleted. This destroy removes it "
            "along with the workload resource group (see SPEC.md section 14)."
        )

    tfvars_path = tfvars.write_tfvars(config)

    init_result = terraform_cli.init_backend(tf_cwd)
    if not init_result.ok:
        echo(f"error: terraform init failed: {init_result.diagnostic()}")
        echo(init_result.redacted_stderr())
        return DestroyResult(1)

    plan_path = config.terraform_state_path() / f"destroy-{PLAN_FILENAME}"
    plan_result = terraform_cli.plan(tf_cwd, var_file=tfvars_path, out_file=plan_path, destroy=True)
    if not plan_result.ok:
        echo(f"error: terraform plan -destroy failed: {plan_result.diagnostic()}")
        echo(plan_result.redacted_stderr())
        return DestroyResult(1)
    echo(plan_result.redacted_stdout()[-3000:])

    if plan_only:
        echo("\n--plan-only: no resources destroyed. Re-run with --yes to destroy.")
        return DestroyResult(0)

    if not yes:
        echo(
            "\nRefusing to destroy without confirmation. Re-run with --yes to permanently "
            f"delete every resource in {config.resource_groups.agent} and "
            f"{config.resource_groups.workload}."
        )
        return DestroyResult(2)

    echo("Destroying Terraform-owned resources...")
    destroy_result = terraform_cli.destroy(tf_cwd, var_file=tfvars_path)
    if not destroy_result.ok:
        remaining = terraform_cli.state_list(tf_cwd)
        echo(f"error: terraform destroy failed: {destroy_result.diagnostic()}")
        echo(destroy_result.redacted_stderr())
        if remaining.ok and remaining.stdout.strip():
            echo("Resources still present in Terraform state:")
            echo(remaining.stdout)
        return DestroyResult(1)

    echo("Verifying resource groups are gone:")
    all_gone = True
    for rg_name in (config.resource_groups.agent, config.resource_groups.workload):
        data, result = resource_group_show(rg_name)
        if data is None:
            if is_not_found(result):
                echo(f"  {rg_name}: confirmed removed.")
            else:
                echo(
                    f"  {rg_name}: could not confirm removal ({result.diagnostic()}); treating "
                    "as a failure, not a confirmed deletion."
                )
                all_gone = False
        else:
            echo(f"  {rg_name}: STILL PRESENT (Azure deletion may still be in progress).")
            all_gone = False

    _cleanup_local_state(config)
    return DestroyResult(0 if all_gone else 1)


def _cleanup_local_state(config: Config) -> None:
    state_dir = config.terraform_state_path()
    deployment_state = state_dir / DEPLOYMENT_STATE_FILENAME
    if deployment_state.is_file():
        deployment_state.unlink()
    for stray_plan in state_dir.glob("*.tfplan"):
        _safe_unlink(stray_plan)


def _safe_unlink(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


__all__ = ["DestroyResult", "run_destroy"]
