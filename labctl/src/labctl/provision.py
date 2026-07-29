"""`labctl provision`: idempotently apply Azure SRE Agent data-plane content
(knowledge, skills, subagents, hooks, common prompts, scheduled tasks, the
incident platform, a response plan, and the GitHub source connection) to the
already-deployed agent (see SPEC.md sections 10-11 and PLAN.md Milestone 4).

This is the "second phase" of agent configuration described in SPEC.md
section 3: ARM (via ``labctl deploy``) creates the agent resource, its
identities, RBAC, and connectors; this module configures everything that
only exists on the agent's own data-plane API. Every step is a PUT/PATCH
keyed by a stable name, so re-running this command is always safe -- it
converges the agent to whatever is currently in ``agent/``, it never
creates duplicates.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from labctl import agent_azure, agent_content, agent_dataplane, github_cli
from labctl import context as ctx
from labctl.agent_dataplane import DataPlaneResult
from labctl.azure_cli import ensure_subscription_context
from labctl.config import Config
from labctl.state import ProvisionState, save_provision_state

Echo = Callable[[str], None]

#: Official template waits 30s after the ARM incident-platform PATCH before
#: the platform is ready to accept a response plan (`Apply-Extras.ps1`
#: section 1: "Waiting 30s for platform to initialize..."). Only paid when
#: this run actually changed the platform (see `_ensure_incident_platform`).
INCIDENT_PLATFORM_INIT_DELAY_SECONDS = 30.0

#: The incident platform can still be initializing right after the ARM
#: PATCH above; the official template retries the response-plan PUT up to 4
#: times, 30s apart, in that case.
INCIDENT_FILTER_RETRY_ATTEMPTS = 4
INCIDENT_FILTER_RETRY_DELAY_SECONDS = 15.0

REPO_DESCRIPTION = (
    "PulseMart demo application, infrastructure, and Azure SRE Agent content "
    "(source-grounded investigation)."
)


@dataclass(frozen=True, slots=True)
class ProvisionResult:
    exit_code: int


def _report(echo: Echo, label: str, result: DataPlaneResult) -> bool:
    if result.ok:
        echo(f"  ok   {label}")
    else:
        echo(f"  FAIL {result.diagnostic()}")
    return result.ok


def _retry(
    call: Callable[[], DataPlaneResult],
    *,
    attempts: int,
    delay: float,
    sleep: Callable[[float], None] = time.sleep,
) -> DataPlaneResult:
    result = call()
    tries = 1
    while not result.ok and tries < attempts:
        sleep(delay)
        result = call()
        tries += 1
    return result


def _confirm_incident_platform(
    agent_context: ctx.AgentContext,
    platform_type: str,
    *,
    echo: Echo,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Confirm ``properties.incidentManagementConfiguration.type`` already
    matches ``platform_type``.

    ``labctl deploy`` owns writing this field via a direct ARM PATCH right
    after ``terraform apply`` (see ``labctl.deploy._reconcile_incident_platform``
    and ``docs/adr/0001-incident-platform-reconciliation.md`` for why this is
    not a Terraform resource: the agent's own PUT semantics reset this field
    on any unrelated apply, and the Terraform-native alternative --
    ``azapi_update_resource`` -- failed live with ARM error
    ``MismatchingResourceIdentityPrincipalId``). ``labctl provision``
    therefore only reads this field back to confirm ``labctl deploy``
    already configured it -- it never PATCHes it itself, so there is
    exactly one writer. A short bounded retry covers the case where this
    run follows a `labctl deploy` from only moments ago and the platform is
    still finishing its documented ~30s initialization.
    """

    current: str | None = None
    for attempt in range(INCIDENT_FILTER_RETRY_ATTEMPTS):
        agent_data, _show_result = agent_azure.agent_show(agent_context.agent_id)
        current = agent_azure.incident_platform_type(agent_data)
        if current == platform_type:
            echo(
                f"  ok   incidentManagementConfiguration.type={platform_type} "
                "(managed by `labctl deploy`; see docs/adr/0001-incident-platform-"
                "reconciliation.md)"
            )
            return True
        if attempt < INCIDENT_FILTER_RETRY_ATTEMPTS - 1:
            sleep(INCIDENT_PLATFORM_INIT_DELAY_SECONDS)
    echo(
        f"  FAIL incidentManagementConfiguration.type={current!r}, expected {platform_type!r}. "
        "`labctl deploy` owns this field; run `labctl deploy --yes` first (see "
        "docs/adr/0001-incident-platform-reconciliation.md)."
    )
    return False


def run_provision(
    config: Config, *, echo: Echo = print, sleep: Callable[[float], None] = time.sleep
) -> ProvisionResult:
    _account, fatal_message = ensure_subscription_context(config)
    if _account is None:
        echo(f"error: {fatal_message}")
        return ProvisionResult(2)

    agent_context, outputs_result = ctx.load_agent_context(config)
    if agent_context is None:
        echo(
            "error: Azure SRE Agent Terraform outputs not found. Run `labctl deploy --yes` "
            "first (see PLAN.md Milestone 3)."
        )
        if outputs_result is not None:
            echo(outputs_result.redacted_stderr())
        return ProvisionResult(1)

    echo(f"Agent:               {agent_context.agent_name}")
    echo(f"Data-plane endpoint: {agent_context.data_plane_endpoint}")
    endpoint = agent_context.data_plane_endpoint

    echo(f"\n[1/8] Acquiring data-plane token (audience: {agent_dataplane.DATA_PLANE_AUDIENCE})")
    dp_token, token_result = agent_dataplane.get_data_plane_token()
    if dp_token is None:
        echo(f"error: could not acquire a data-plane token: {token_result.diagnostic()}")
        echo(token_result.redacted_stderr())
        return ProvisionResult(1)
    echo("  token acquired")

    try:
        content = agent_content.load_agent_content(config.repo_root)
    except agent_content.AgentContentError as exc:
        echo(f"error: {exc}")
        return ProvisionResult(1)

    all_ok = True

    echo("\n[2/8] Skills")
    for skill in content.skills:
        properties: dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
            "tools": list(skill.tools),
            "skillContent": skill.skill_content,
            "additionalFiles": list(skill.additional_files),
        }
        result = agent_dataplane.put_extended_item(
            endpoint, dp_token, kind="skills", name=skill.name, properties=properties
        )
        all_ok &= _report(echo, f"skills/{skill.name}", result)

    echo("\n[3/8] Subagents")

    # A single PUT per subagent, carrying `handoffs` exactly as declared in
    # `agent/` (currently always empty; see
    # agent/config/subagents/incident-investigator.yaml for why). An earlier
    # version of this loop bootstrapped forward handoff references with a
    # two-pass "PUT empty handoffs, then PUT real handoffs" sequence, which
    # was necessary before this agent's `experimentalSettings
    # .EnableV2AgentLoop` was enabled (the data plane rejected a PUT whose
    # `handoffs` target did not exist yet). Once that flag is live the
    # platform runs in "workspace mode", where creating *any* new
    # agent-to-agent handoff is rejected outright ("New agent-to-agent
    # handoffs are not supported in workspace mode. Existing handoffs may
    # only be retained or removed."). The two-pass bootstrap became actively
    # harmful under that mode: its first pass unconditionally PUT every
    # subagent with `handoffs=[]`, which -- on a subagent that already had a
    # real handoff from a prior `provision` run -- counts as *removing* an
    # existing handoff; the second pass then tried to re-add it, which
    # workspace mode now rejects as "new" (live-reproduced 2026-07-29 right
    # after the `EnableV2AgentLoop` change: `incident-investigator`'s
    # `rollback-advisor` handoff was wiped this way and could not be
    # restored). See PLAN.md Milestone 4 "API/schema adaptations" for the
    # full timeline; cross-subagent coordination is now carried by
    # instructions text and the shared skill instead of `handoffs`.
    for subagent in content.subagents:
        sub_properties: dict[str, Any] = {
            "instructions": subagent.instructions,
            "handoffDescription": subagent.handoff_description,
            "handoffs": list(subagent.handoffs),
            "tools": list(subagent.tools),
            "agentType": subagent.agent_type,
            "temperature": subagent.temperature,
            "enableSkills": subagent.enable_skills,
            "allowedSkills": list(subagent.allowed_skills),
        }
        result = agent_dataplane.put_extended_item(
            endpoint, dp_token, kind="agents", name=subagent.name, properties=sub_properties
        )
        all_ok &= _report(echo, f"subagents/{subagent.name}", result)

    echo("\n[4/8] Hooks and common prompts")
    for hook in content.hooks:
        hook_properties: dict[str, Any] = {
            "eventType": hook.event_type,
            "hook": {"type": hook.hook_type, "prompt": hook.prompt, "matcher": hook.matcher},
            "permissionDecision": hook.permission_decision,
            "enabled": hook.enabled,
        }
        result = agent_dataplane.put_extended_item(
            endpoint, dp_token, kind="hooks", name=hook.name, properties=hook_properties
        )
        all_ok &= _report(echo, f"hooks/{hook.name}", result)
    for prompt in content.common_prompts:
        result = agent_dataplane.put_extended_item(
            endpoint,
            dp_token,
            kind="commonprompts",
            name=prompt.name,
            properties={"prompt": prompt.prompt},
        )
        all_ok &= _report(echo, f"commonprompts/{prompt.name}", result)

    echo("\n[5/8] Knowledge (AgentMemory)")
    for knowledge_file in content.knowledge_files:
        result = agent_dataplane.upload_knowledge_file(
            endpoint,
            dp_token,
            filename=knowledge_file.filename,
            content=knowledge_file.content.encode("utf-8"),
            mime_type=knowledge_file.mime_type,
        )
        all_ok &= _report(echo, f"knowledge/{knowledge_file.filename}", result)

    echo("\n[6/8] Incident platform and response plan")
    if content.incident_platform is not None:
        platform_ok = _confirm_incident_platform(
            agent_context, content.incident_platform.platform_type, echo=echo, sleep=sleep
        )
        all_ok &= platform_ok
        for incident_filter in content.incident_filters:
            filter_properties: dict[str, Any] = {
                "incidentPlatform": incident_filter.incident_platform,
                "handlingAgent": incident_filter.handling_agent,
                "isEnabled": incident_filter.is_enabled,
                "priorities": list(incident_filter.priorities),
                "agentMode": incident_filter.agent_mode,
                "maxAutomatedInvestigationAttempts": (
                    incident_filter.max_automated_investigation_attempts
                ),
                # `deepInvestigationEnabled` is deliberately omitted: this
                # preview build's IncidentFilterView rejects it outright
                # ("could not be mapped to any .NET member"), and including
                # it causes the whole request body to fail to bind (live-
                # verified 2026-07-29; see PLAN.md Milestone 4 "API/schema
                # adaptations"). `agent_content.IncidentFilterContent` still
                # models the field so `agent/` stays comparable to the
                # official recipe's `azmon-sev01.yaml`, it is just not sent.
            }
            if incident_filter.title_contains:
                filter_properties["titleContains"] = incident_filter.title_contains

            def _put_filter(
                name: str = incident_filter.name, props: dict[str, Any] = filter_properties
            ) -> DataPlaneResult:
                return agent_dataplane.put_extended_item(
                    endpoint, dp_token, kind="incidentFilters", name=name, properties=props
                )

            result = _retry(
                _put_filter,
                attempts=INCIDENT_FILTER_RETRY_ATTEMPTS,
                delay=INCIDENT_FILTER_RETRY_DELAY_SECONDS,
                sleep=sleep,
            )
            all_ok &= _report(echo, f"incidentFilters/{incident_filter.name}", result)
    else:
        echo("  no incident platform content found under agent/automations/incident-platforms/")

    echo("\n[7/8] Scheduled tasks")
    for task in content.scheduled_tasks:
        task_properties: dict[str, Any] = {
            "name": task.name,
            "description": task.description,
            "cronExpression": task.cron_expression,
            "agentPrompt": task.agent_prompt,
            "agentMode": task.agent_mode,
            "isEnabled": task.enabled,
        }
        result = agent_dataplane.put_extended_item(
            endpoint, dp_token, kind="scheduledtasks", name=task.name, properties=task_properties
        )
        all_ok &= _report(echo, f"scheduledtasks/{task.name}", result)

    echo("\n[8/8] GitHub source connection")
    github_wired = False
    gh_token, gh_result = github_cli.auth_token()
    if gh_token is None:
        echo(
            f"  WARN could not read a `gh` CLI token ({gh_result.diagnostic()}); skipping GitHub "
            "wiring. Run `gh auth login` and re-run `labctl provision` (see SPEC.md section 10)."
        )
    else:
        domain_result = agent_dataplane.put_github_domain_pat(endpoint, dp_token, pat=gh_token)
        gh_token = None  # never keep the token in a local variable longer than needed
        github_domain_ok = _report(echo, "github/domains/github_com", domain_result)
        all_ok &= github_domain_ok
        repo_owner_repo = config.github.repository
        repo_name = repo_owner_repo.split("/")[-1]
        repo_result = agent_dataplane.put_repo(
            endpoint,
            dp_token,
            name=repo_name,
            url=f"https://github.com/{repo_owner_repo}",
            repo_type="GitHub",
            description=REPO_DESCRIPTION,
        )
        repo_ok = _report(echo, f"repos/{repo_name}", repo_result)
        all_ok &= repo_ok
        github_wired = github_domain_ok and repo_ok

    save_provision_state(
        config,
        ProvisionState(
            provisioned_at=datetime.now(UTC).isoformat(), ok=all_ok, github_wired=github_wired
        ),
    )

    if all_ok:
        echo("\nDone. Run `labctl verify` to confirm this content is visible on the live agent.")
    else:
        echo("\nCompleted with failures; see FAIL lines above. Re-running is safe (idempotent).")
    return ProvisionResult(0 if all_ok else 1)


__all__ = ["ProvisionResult", "run_provision"]
