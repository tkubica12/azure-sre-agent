"""Loads the PulseMart-specific Azure SRE Agent content that
``labctl provision`` applies (see SPEC.md section 10 and AGENTS.md
"repository layout").

Content lives under the repository's ``agent/`` directory, following the
same ``metadata``/``spec`` YAML shape (with markdown content referenced by
relative path) used by the official ``microsoft/sre-agent`` template's
``recipes/*/config/`` and ``recipes/*/automations/`` directories, so this
demo's content stays directly comparable to the first-party recipes. See
``agent/README.md`` for the full layout.

Every loader is read-only and side-effect free; :mod:`labctl.provision` is
responsible for turning these dataclasses into real data-plane/ARM calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

AGENT_DIR_NAME = "agent"


class AgentContentError(RuntimeError):
    """Raised when content under ``agent/`` is missing or malformed."""


def agent_dir(repo_root: Path) -> Path:
    return repo_root / AGENT_DIR_NAME


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise AgentContentError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentContentError(f"{path}: expected a YAML mapping at the top level.")
    return data


def _read_ref(config_dir: Path, relative: str) -> str:
    path = config_dir / relative
    if not path.is_file():
        raise AgentContentError(f"Referenced content file not found: {path}")
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class SkillContent:
    name: str
    description: str
    tools: tuple[str, ...]
    skill_content: str
    additional_files: tuple[str, ...] = ()


def load_skills(config_dir: Path) -> list[SkillContent]:
    out: list[SkillContent] = []
    for path in sorted((config_dir / "skills").glob("*.yaml")):
        doc = _load_yaml(path)
        meta = doc.get("metadata") or {}
        spec = meta.get("spec") or {}
        name = str(meta.get("name") or path.stem)
        ref = doc.get("skillContent", "")
        content = _read_ref(config_dir, ref) if ref else ""
        out.append(
            SkillContent(
                name=name,
                description=str(meta.get("description", "")),
                tools=tuple(spec.get("tools") or []),
                skill_content=content,
                additional_files=tuple(doc.get("additionalFiles") or []),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class SubagentContent:
    name: str
    instructions: str
    handoff_description: str
    handoffs: tuple[str, ...]
    tools: tuple[str, ...]
    agent_type: str
    temperature: float
    enable_skills: bool
    allowed_skills: tuple[str, ...]


def load_subagents(config_dir: Path) -> list[SubagentContent]:
    out: list[SubagentContent] = []
    for path in sorted((config_dir / "subagents").glob("*.yaml")):
        doc = _load_yaml(path)
        meta = doc.get("metadata") or {}
        spec = doc.get("spec") or {}
        name = str(meta.get("name") or path.stem)
        ref = spec.get("instructions", "")
        instructions = _read_ref(config_dir, ref) if ref else ""
        out.append(
            SubagentContent(
                name=name,
                instructions=instructions,
                handoff_description=str(spec.get("handoffDescription", "")),
                handoffs=tuple(spec.get("handoffs") or []),
                tools=tuple(spec.get("tools") or []),
                agent_type=str(spec.get("agentType", "Autonomous")),
                temperature=float(spec.get("temperature", 0.2)),
                enable_skills=bool(spec.get("enableSkills", True)),
                allowed_skills=tuple(spec.get("allowedSkills") or []),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class HookContent:
    name: str
    event_type: str
    hook_type: str
    prompt: str
    matcher: str
    permission_decision: str
    enabled: bool


def load_hooks(config_dir: Path) -> list[HookContent]:
    out: list[HookContent] = []
    for path in sorted((config_dir / "hooks").glob("*.yaml")):
        doc = _load_yaml(path)
        meta = doc.get("metadata") or {}
        spec = doc.get("spec") or {}
        hook = spec.get("hook") or {}
        out.append(
            HookContent(
                name=str(meta.get("name") or path.stem),
                event_type=str(spec.get("eventType", "PreToolUse")),
                hook_type=str(hook.get("type", "prompt")),
                prompt=str(hook.get("prompt", "")),
                matcher=str(hook.get("matcher", ".*")),
                permission_decision=str(spec.get("permissionDecision", "allow")),
                enabled=bool(spec.get("enabled", True)),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class CommonPromptContent:
    name: str
    prompt: str


def load_common_prompts(config_dir: Path) -> list[CommonPromptContent]:
    out: list[CommonPromptContent] = []
    for path in sorted((config_dir / "common-prompts").glob("*.yaml")):
        doc = _load_yaml(path)
        meta = doc.get("metadata") or {}
        spec = doc.get("spec") or {}
        out.append(
            CommonPromptContent(
                name=str(meta.get("name") or path.stem), prompt=str(spec.get("prompt", ""))
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class ScheduledTaskContent:
    name: str
    description: str
    cron_expression: str
    agent_prompt: str
    agent_mode: str
    enabled: bool


def load_scheduled_tasks(automations_dir: Path) -> list[ScheduledTaskContent]:
    out: list[ScheduledTaskContent] = []
    for path in sorted((automations_dir / "scheduled-tasks").glob("*.yaml")):
        doc = _load_yaml(path)
        meta = doc.get("metadata") or {}
        spec = doc.get("spec") or {}
        out.append(
            ScheduledTaskContent(
                name=str(meta.get("name") or path.stem),
                description=str(spec.get("description", "")),
                cron_expression=str(spec.get("schedule") or spec.get("cronExpression", "")),
                agent_prompt=str(spec.get("prompt") or spec.get("agentPrompt", "")),
                agent_mode=str(spec.get("mode") or spec.get("agentMode", "Review")),
                enabled=bool(spec.get("enabled", True)),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class IncidentFilterContent:
    name: str
    incident_platform: str
    handling_agent: str
    is_enabled: bool
    priorities: tuple[str, ...]
    agent_mode: str
    deep_investigation_enabled: bool
    max_automated_investigation_attempts: int
    title_contains: str = ""


def load_incident_filters(automations_dir: Path) -> list[IncidentFilterContent]:
    out: list[IncidentFilterContent] = []
    for path in sorted((automations_dir / "incident-filters").glob("*.yaml")):
        doc = _load_yaml(path)
        meta = doc.get("metadata") or {}
        spec = doc.get("spec") or {}
        out.append(
            IncidentFilterContent(
                name=str(meta.get("name") or path.stem),
                incident_platform=str(spec.get("incidentPlatform", "AzMonitor")),
                handling_agent=str(spec.get("handlingAgent", "default")),
                is_enabled=bool(spec.get("isEnabled", True)),
                priorities=tuple(spec.get("priorities") or []),
                agent_mode=str(spec.get("agentMode", "Autonomous")),
                deep_investigation_enabled=bool(spec.get("deepInvestigationEnabled", False)),
                max_automated_investigation_attempts=int(
                    spec.get("maxAutomatedInvestigationAttempts", 3)
                ),
                title_contains=str(spec.get("titleContains", "")),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class IncidentPlatformContent:
    name: str
    platform_type: str
    display_name: str
    description: str


def load_incident_platform(automations_dir: Path) -> IncidentPlatformContent | None:
    paths = sorted((automations_dir / "incident-platforms").glob("*.yaml"))
    if not paths:
        return None
    doc = _load_yaml(paths[0])
    spec = doc.get("spec") or {}
    return IncidentPlatformContent(
        name=str(doc.get("name") or paths[0].stem),
        platform_type=str(spec.get("platformType", "AzMonitor")),
        display_name=str(spec.get("displayName", "")),
        description=str(spec.get("description", "")),
    )


@dataclass(frozen=True, slots=True)
class KnowledgeFileContent:
    filename: str
    content: str
    mime_type: str = "text/markdown"


def load_knowledge_files(base_dir: Path) -> list[KnowledgeFileContent]:
    out: list[KnowledgeFileContent] = []
    for path in sorted((base_dir / "knowledge").glob("*.md")):
        out.append(KnowledgeFileContent(filename=path.name, content=path.read_text("utf-8")))
    return out


@dataclass(frozen=True, slots=True)
class AgentContent:
    skills: tuple[SkillContent, ...]
    subagents: tuple[SubagentContent, ...]
    hooks: tuple[HookContent, ...]
    common_prompts: tuple[CommonPromptContent, ...]
    scheduled_tasks: tuple[ScheduledTaskContent, ...]
    incident_filters: tuple[IncidentFilterContent, ...]
    incident_platform: IncidentPlatformContent | None
    knowledge_files: tuple[KnowledgeFileContent, ...]


def load_agent_content(repo_root: Path) -> AgentContent:
    base = agent_dir(repo_root)
    config_dir = base / "config"
    automations_dir = base / "automations"
    if not base.is_dir():
        raise AgentContentError(
            f"Agent content directory not found: {base}. Expected `agent/config/` and "
            "`agent/automations/` (see SPEC.md section 10, agent/README.md)."
        )
    return AgentContent(
        skills=tuple(load_skills(config_dir)),
        subagents=tuple(load_subagents(config_dir)),
        hooks=tuple(load_hooks(config_dir)),
        common_prompts=tuple(load_common_prompts(config_dir)),
        scheduled_tasks=tuple(load_scheduled_tasks(automations_dir)),
        incident_filters=tuple(load_incident_filters(automations_dir)),
        incident_platform=load_incident_platform(automations_dir),
        knowledge_files=tuple(load_knowledge_files(base)),
    )


__all__ = [
    "AGENT_DIR_NAME",
    "AgentContentError",
    "agent_dir",
    "SkillContent",
    "load_skills",
    "SubagentContent",
    "load_subagents",
    "HookContent",
    "load_hooks",
    "CommonPromptContent",
    "load_common_prompts",
    "ScheduledTaskContent",
    "load_scheduled_tasks",
    "IncidentFilterContent",
    "load_incident_filters",
    "IncidentPlatformContent",
    "load_incident_platform",
    "KnowledgeFileContent",
    "load_knowledge_files",
    "AgentContent",
    "load_agent_content",
]
