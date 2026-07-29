from __future__ import annotations

import pytest
from conftest import make_config, make_result

import labctl.provision as provision_mod
from labctl import agent_content
from labctl.agent_dataplane import DataPlaneResult
from labctl.azure_cli import Account
from labctl.context import AgentContext

AGENT_ID = (
    "/subscriptions/sub-1/resourceGroups/rg-agent/providers/Microsoft.App/agents/sre-agent-demo"
)

ACCOUNT = Account(
    subscription_id="sub-1",
    subscription_name="Test Subscription",
    tenant_id="tenant-1",
    user_name="me@example.com",
    user_type="user",
)


def _agent_context() -> AgentContext:
    return AgentContext(
        agent_id=AGENT_ID,
        agent_name="sre-agent-demo",
        agent_resource_group="rg-agent",
        portal_url="https://sre.azure.com/#/agent/sub-1/rg-agent/sre-agent-demo",
        data_plane_endpoint="https://sre-agent-demo--hash.swedencentral.azuresre.ai",
        uami_id="/subscriptions/sub-1/resourceGroups/rg-agent/.../sre-agent-demo-uami",
        uami_principal_id="uami-principal",
        uami_client_id="uami-client",
        system_identity_principal_id="system-principal",
        agent_app_insights_id="/subscriptions/sub-1/appi-agent",
        agent_app_insights_app_id="appi-agent-guid",
        agent_log_analytics_id="/subscriptions/sub-1/law-agent",
        agent_log_analytics_workspace_id="law-agent-guid",
        connector_names=("app-insights", "log-analytics", "azure-monitor"),
    )


def _content() -> agent_content.AgentContent:
    return agent_content.AgentContent(
        skills=(
            agent_content.SkillContent(
                name="triage-checkout-failures",
                description="d",
                tools=("RunAzCliReadCommands",),
                skill_content="do the thing",
            ),
        ),
        subagents=(
            agent_content.SubagentContent(
                name="incident-investigator",
                instructions="x" * 60,
                handoff_description="d",
                handoffs=(),
                tools=(),
                agent_type="Autonomous",
                temperature=0.2,
                enable_skills=True,
                allowed_skills=("triage-checkout-failures",),
            ),
        ),
        hooks=(
            agent_content.HookContent(
                name="deny-destructive-deletes",
                event_type="PreToolUse",
                hook_type="prompt",
                prompt="deny",
                matcher="^(delete_).*",
                permission_decision="deny",
                enabled=True,
            ),
        ),
        common_prompts=(agent_content.CommonPromptContent(name="safety-rules", prompt="be safe"),),
        scheduled_tasks=(
            agent_content.ScheduledTaskContent(
                name="daily-reliability-summary",
                description="d",
                cron_expression="0 8 * * *",
                agent_prompt="summarize",
                agent_mode="Review",
                enabled=True,
            ),
        ),
        incident_filters=(
            agent_content.IncidentFilterContent(
                name="checkout-5xx",
                incident_platform="AzMonitor",
                handling_agent="incident-investigator",
                is_enabled=True,
                priorities=("Sev2",),
                agent_mode="Autonomous",
                deep_investigation_enabled=False,
                max_automated_investigation_attempts=3,
                title_contains="checkout",
            ),
        ),
        incident_platform=agent_content.IncidentPlatformContent(
            name="azure-monitor", platform_type="AzMonitor", display_name="d", description="d"
        ),
        knowledge_files=(
            agent_content.KnowledgeFileContent(filename="architecture.md", content="# Arch"),
        ),
    )


def _patch_common(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        provision_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(
        provision_mod.ctx, "load_agent_context", lambda config, **_kw: (_agent_context(), None)
    )
    monkeypatch.setattr(
        provision_mod.agent_dataplane,
        "get_data_plane_token",
        lambda **_kw: ("fake-token", make_result(stdout="fake-token")),
    )
    monkeypatch.setattr(
        provision_mod.agent_content, "load_agent_content", lambda repo_root: _content()
    )
    monkeypatch.setattr(
        provision_mod.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            # Terraform now owns incidentManagementConfiguration (see B1
            # fix); provision only reads it back to confirm, so the happy
            # path here reflects it already being set correctly.
            {"properties": {"incidentManagementConfiguration": {"type": "AzMonitor"}}},
            make_result(stdout="{}"),
        ),
    )
    monkeypatch.setattr(
        provision_mod.agent_azure,
        "set_incident_platform",
        lambda agent_id, **_kw: ({"properties": {}}, make_result(stdout="{}")),
    )
    monkeypatch.setattr(provision_mod, "time", provision_mod.time)  # keep real time module
    monkeypatch.setattr(
        provision_mod.agent_dataplane,
        "put_extended_item",
        lambda endpoint, token, *, kind, name, properties, **_kw: DataPlaneResult(
            True, 202, f"PUT {kind}/{name}"
        ),
    )
    monkeypatch.setattr(
        provision_mod.agent_dataplane,
        "upload_knowledge_file",
        lambda endpoint, token, *, filename, content, **_kw: DataPlaneResult(
            True, 200, f"POST knowledge/{filename}"
        ),
    )
    monkeypatch.setattr(
        provision_mod.github_cli, "auth_token", lambda **_kw: ("gh-token", make_result())
    )
    monkeypatch.setattr(
        provision_mod.agent_dataplane,
        "put_github_domain_pat",
        lambda endpoint, token, *, pat, **_kw: DataPlaneResult(True, 200, "PUT github/domains"),
    )
    monkeypatch.setattr(
        provision_mod.agent_dataplane,
        "put_repo",
        lambda endpoint, token, *, name, url, **_kw: DataPlaneResult(
            True, 202, f"PUT repos/{name}"
        ),
    )


def test_run_provision_fails_fast_when_agent_not_deployed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        provision_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(provision_mod.ctx, "load_agent_context", lambda config, **_kw: (None, None))

    result = provision_mod.run_provision(make_config(tmp_path), echo=lambda _msg: None)

    assert result.exit_code == 1


def test_run_provision_fails_fast_on_subscription_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        provision_mod,
        "ensure_subscription_context",
        lambda config, **_kw: (None, "subscription mismatch"),
    )
    messages: list[str] = []

    result = provision_mod.run_provision(make_config(tmp_path), echo=messages.append)

    assert result.exit_code == 2
    assert any("subscription mismatch" in m for m in messages)


def test_run_provision_fails_when_token_acquisition_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        provision_mod, "ensure_subscription_context", lambda config, **_kw: (ACCOUNT, None)
    )
    monkeypatch.setattr(
        provision_mod.ctx, "load_agent_context", lambda config, **_kw: (_agent_context(), None)
    )
    monkeypatch.setattr(
        provision_mod.agent_dataplane,
        "get_data_plane_token",
        lambda **_kw: (None, make_result(returncode=1, stderr="not logged in")),
    )

    result = provision_mod.run_provision(make_config(tmp_path), echo=lambda _msg: None)

    assert result.exit_code == 1


def test_run_provision_happy_path_reports_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(provision_mod.time, "sleep", lambda _seconds: None)

    result = provision_mod.run_provision(
        make_config(tmp_path), echo=lambda _msg: None, sleep=lambda _s: None
    )

    assert result.exit_code == 0


def test_run_provision_reports_failure_when_one_put_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)

    def failing_put(endpoint, token, *, kind, name, properties, **_kw):
        if kind == "skills":
            return DataPlaneResult(False, 400, f"PUT {kind}/{name}", "bad request")
        return DataPlaneResult(True, 202, f"PUT {kind}/{name}")

    monkeypatch.setattr(provision_mod.agent_dataplane, "put_extended_item", failing_put)

    result = provision_mod.run_provision(
        make_config(tmp_path), echo=lambda _msg: None, sleep=lambda _s: None
    )

    assert result.exit_code == 1


def test_run_provision_never_arm_patches_incident_platform(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Terraform owns `incidentManagementConfiguration` now (B1 fix);
    `labctl provision` must only read it back to confirm, never PATCH it
    itself -- otherwise there would be two writers racing each other."""

    _patch_common(monkeypatch, tmp_path)
    patch_calls: list[str] = []
    monkeypatch.setattr(
        provision_mod.agent_azure,
        "set_incident_platform",
        lambda agent_id, **_kw: patch_calls.append("patched") or ({}, make_result()),
    )

    result = provision_mod.run_provision(
        make_config(tmp_path), echo=lambda _msg: None, sleep=lambda _s: None
    )

    assert result.exit_code == 0
    assert patch_calls == []


def test_run_provision_fails_when_terraform_never_set_incident_platform(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """If Terraform hasn't (yet) set the incident platform, provision must
    fail rather than silently PATCH it itself (see B1 fix: exactly one
    writer)."""

    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(
        provision_mod.agent_azure,
        "agent_show",
        lambda agent_id, **_kw: (
            {"properties": {"incidentManagementConfiguration": None}},
            make_result(stdout="{}"),
        ),
    )
    messages: list[str] = []

    result = provision_mod.run_provision(
        make_config(tmp_path), echo=messages.append, sleep=lambda _s: None
    )

    assert result.exit_code == 1
    assert any("`labctl deploy` owns this field" in m for m in messages)


def test_run_provision_warns_and_continues_without_github_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(
        provision_mod.github_cli,
        "auth_token",
        lambda **_kw: (None, make_result(returncode=1, stderr="not logged in")),
    )
    repo_calls: list[str] = []
    monkeypatch.setattr(
        provision_mod.agent_dataplane,
        "put_repo",
        lambda *a, **k: repo_calls.append("called"),
    )

    result = provision_mod.run_provision(
        make_config(tmp_path), echo=lambda _msg: None, sleep=lambda _s: None
    )

    assert result.exit_code == 0
    assert repo_calls == []


def test_run_provision_never_echoes_the_data_plane_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(
        provision_mod.agent_dataplane,
        "get_data_plane_token",
        lambda **_kw: ("super-secret-token", make_result(stdout="super-secret-token")),
    )
    messages: list[str] = []

    provision_mod.run_provision(make_config(tmp_path), echo=messages.append, sleep=lambda _s: None)

    assert not any("super-secret-token" in m for m in messages)
