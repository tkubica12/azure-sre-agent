from __future__ import annotations

from pathlib import Path

import pytest

import labctl.agent_content as agent_content

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_agent_content_reads_the_real_repository_content() -> None:
    """The actual `agent/` directory this milestone authored must parse
    cleanly and match `agent/expected-config.json` (see PLAN.md
    Milestone 4)."""

    content = agent_content.load_agent_content(REPO_ROOT)

    assert {s.name for s in content.skills} == {"triage-checkout-failures"}
    assert {s.name for s in content.subagents} == {"incident-investigator", "rollback-advisor"}
    assert {h.name for h in content.hooks} == {
        "require-approval-for-changes",
        "deny-destructive-deletes",
    }
    assert {p.name for p in content.common_prompts} == {
        "investigation-guidelines",
        "safety-rules",
    }
    assert {t.name for t in content.scheduled_tasks} == {"daily-reliability-summary"}
    assert {f.name for f in content.incident_filters} == {"containerapp-5xx"}
    assert content.incident_platform is not None
    assert content.incident_platform.platform_type == "AzMonitor"
    assert {k.filename for k in content.knowledge_files} == {
        "architecture.md",
        "checkout-500-runbook.md",
        "investigation-report-template.md",
        "remediation-report-template.md",
    }


def test_skill_content_is_inlined_from_the_referenced_markdown_file() -> None:
    content = agent_content.load_agent_content(REPO_ROOT)

    skill = next(s for s in content.skills if s.name == "triage-checkout-failures")

    assert skill.skill_content.strip() != ""
    assert "checkout-500-runbook" in skill.skill_content


def test_subagent_instructions_are_inlined_and_reference_the_skill() -> None:
    content = agent_content.load_agent_content(REPO_ROOT)

    investigator = next(s for s in content.subagents if s.name == "incident-investigator")

    assert "triage-checkout-failures" in investigator.instructions
    assert investigator.allowed_skills == ("triage-checkout-failures",)
    # Live-verified 2026-07-29: once the agent's `experimentalSettings
    # .EnableV2AgentLoop` is enabled, the data plane rejects any *new*
    # agent-to-agent handoff outright ("New agent-to-agent handoffs are not
    # supported in workspace mode."), so this content deliberately declares
    # no handoffs and coordinates via instructions/skills instead (see
    # PLAN.md Milestone 4 "API/schema adaptations").
    assert investigator.handoffs == ()


def test_incident_filter_routes_pulsemart_5xx_alerts_to_the_investigator() -> None:
    content = agent_content.load_agent_content(REPO_ROOT)

    incident_filter = next(f for f in content.incident_filters if f.name == "containerapp-5xx")

    assert incident_filter.handling_agent == "incident-investigator"
    assert "pulsemart" in incident_filter.title_contains
    # Product-owner decision, 2026-07-30 (SPEC.md section 5 Scene 5, PLAN.md
    # Milestone 5): Review-mode's Approve/Deny gate does not reliably engage
    # in this preview build, so this response plan is honestly configured
    # Autonomous rather than claiming a gate that does not work.
    assert incident_filter.agent_mode == "Autonomous"


def test_rollback_advisor_holds_the_scoped_write_tool_and_investigator_does_not() -> None:
    """Tool scoping is this demonstration's real, live-proven governance
    control (see SPEC.md section 5 Scene 5): `rollback-advisor` executes the
    real rollback under its own identity and must hold
    `RunAzCliWriteCommands`; `incident-investigator` must never hold it."""

    content = agent_content.load_agent_content(REPO_ROOT)
    subagents_by_name = {s.name: s for s in content.subagents}

    assert "RunAzCliWriteCommands" in subagents_by_name["rollback-advisor"].tools
    assert "RunAzCliWriteCommands" not in subagents_by_name["incident-investigator"].tools


def test_hooks_deny_deletes_and_require_approval_for_changes() -> None:
    content = agent_content.load_agent_content(REPO_ROOT)

    hooks_by_name = {h.name: h for h in content.hooks}
    assert hooks_by_name["deny-destructive-deletes"].permission_decision == "deny"
    assert hooks_by_name["require-approval-for-changes"].permission_decision == "allow"


def test_load_agent_content_raises_when_the_directory_is_missing(tmp_path: Path) -> None:
    with pytest.raises(agent_content.AgentContentError):
        agent_content.load_agent_content(tmp_path)


def test_load_skills_raises_when_a_referenced_file_is_missing(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    skills_dir = config_dir / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "broken.yaml").write_text(
        "metadata:\n  name: broken\nskillContent: skills/missing.md\n", encoding="utf-8"
    )

    with pytest.raises(agent_content.AgentContentError):
        agent_content.load_skills(config_dir)


def test_load_hooks_parses_the_nested_hook_shape(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    hooks_dir = config_dir / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "deny.yaml").write_text(
        "metadata:\n"
        "  name: deny-things\n"
        "spec:\n"
        "  eventType: PreToolUse\n"
        "  hook:\n"
        "    type: prompt\n"
        "    prompt: deny it\n"
        "    matcher: ^(delete_).*\n"
        "  permissionDecision: deny\n"
        "  enabled: true\n",
        encoding="utf-8",
    )

    hooks = agent_content.load_hooks(config_dir)

    assert len(hooks) == 1
    assert hooks[0].name == "deny-things"
    assert hooks[0].matcher == "^(delete_).*"
    assert hooks[0].permission_decision == "deny"


def test_load_knowledge_files_reads_every_markdown_file(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "a.md").write_text("# A", encoding="utf-8")
    (knowledge_dir / "b.md").write_text("# B", encoding="utf-8")

    files = agent_content.load_knowledge_files(tmp_path)

    assert {f.filename for f in files} == {"a.md", "b.md"}
    assert all(f.mime_type == "text/markdown" for f in files)
