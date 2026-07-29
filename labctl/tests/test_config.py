from __future__ import annotations

from pathlib import Path

import pytest

from labctl.config import (
    CONFIG_EXAMPLE_FILENAME,
    ConfigError,
    find_repo_root,
    load_config,
    parse_config,
)

VALID_DOCUMENT = {
    "azure": {"region": "swedencentral", "subscription_id": "", "tenant_id": ""},
    "resource_groups": {"agent": "rg-agent", "workload": "rg-workload"},
    "tags": {
        "repository": "azure-sre-agent",
        "environment": "demo",
        "owner": "me",
        "deployment_id": "local",
    },
    "github": {"repository": "tkubica12/azure-sre-agent"},
    "agent": {"name": "sre-agent-demo", "monthly_aau_allocation": 3000, "data_plane_endpoint": ""},
    "workload": {
        "alert_notification_email": "",
        "alert_threshold_5xx": 3,
        "log_retention_days": 30,
    },
    "paths": {"terraform_state_dir": ".state", "evidence_dir": ".evidence"},
}


def _repo(tmp_path: Path) -> Path:
    (tmp_path / CONFIG_EXAMPLE_FILENAME).write_text("# example\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    return tmp_path


def test_parse_config_valid(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    config = parse_config(
        VALID_DOCUMENT, repo_root=repo_root, source_path=repo_root / "config.local.toml"
    )

    assert config.azure.region == "swedencentral"
    assert config.resource_groups.agent == "rg-agent"
    assert config.github.repository == "tkubica12/azure-sre-agent"
    assert config.agent.monthly_aau_allocation == 3000
    assert config.terraform_state_path() == repo_root / ".state"
    assert config.evidence_path() == repo_root / ".evidence"


def test_parse_config_rejects_unsupported_region(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {**VALID_DOCUMENT, "azure": {"region": "eastus"}}

    with pytest.raises(ConfigError, match="not a currently supported"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_missing_section_raises(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {k: v for k, v in VALID_DOCUMENT.items() if k != "github"}

    with pytest.raises(ConfigError, match=r"\[github\]"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_missing_key_raises(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = dict(VALID_DOCUMENT)
    document["resource_groups"] = {"agent": "rg-agent"}  # missing "workload"

    with pytest.raises(ConfigError, match="workload"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_rejects_malformed_github_repository(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {**VALID_DOCUMENT, "github": {"repository": "not-a-slug"}}

    with pytest.raises(ConfigError, match="owner/repo"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_rejects_non_positive_aau(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {
        **VALID_DOCUMENT,
        "agent": {"name": "sre-agent-demo", "monthly_aau_allocation": 0, "data_plane_endpoint": ""},
    }

    with pytest.raises(ConfigError, match="between 1 and"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_rejects_aau_above_demo_sized_cap(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {
        **VALID_DOCUMENT,
        "agent": {
            "name": "sre-agent-demo",
            "monthly_aau_allocation": 10000,
            "data_plane_endpoint": "",
        },
    }

    with pytest.raises(ConfigError, match="between 1 and"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_rejects_invalid_workload_access_level(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {
        **VALID_DOCUMENT,
        "agent": {
            "name": "sre-agent-demo",
            "monthly_aau_allocation": 3000,
            "workload_access_level": "wide-open",
        },
    }

    with pytest.raises(ConfigError, match="workload_access_level"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_defaults_workload_access_level_to_narrow(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    config = parse_config(
        VALID_DOCUMENT, repo_root=repo_root, source_path=repo_root / "config.local.toml"
    )

    assert config.agent.workload_access_level == "narrow"


def test_parse_config_rejects_malformed_agent_name(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {
        **VALID_DOCUMENT,
        "agent": {"name": "Not_Valid!", "monthly_aau_allocation": 3000},
    }

    with pytest.raises(ConfigError, match="agent.name"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_rejects_unsupported_upgrade_channel(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {
        **VALID_DOCUMENT,
        "agent": {
            "name": "sre-agent-demo",
            "monthly_aau_allocation": 3000,
            "upgrade_channel": "Nightly",
        },
    }

    with pytest.raises(ConfigError, match="upgrade_channel"):
        parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")


def test_parse_config_applies_agent_defaults(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    document = {
        **VALID_DOCUMENT,
        "agent": {"name": "sre-agent-demo", "monthly_aau_allocation": 3000},
    }

    config = parse_config(document, repo_root=repo_root, source_path=repo_root / "x.toml")

    assert config.agent.upgrade_channel == "Preview"
    assert config.agent.model_provider == "Anthropic"
    assert config.agent.model_name == "Automatic"


def test_load_config_missing_file_gives_actionable_error(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)

    with pytest.raises(ConfigError, match="config.local.toml"):
        load_config(repo_root=repo_root)


def test_load_config_reads_and_validates_real_file(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    config_path = repo_root / "config.local.toml"
    config_path.write_text(
        """
        [azure]
        region = "swedencentral"

        [resource_groups]
        agent = "rg-agent"
        workload = "rg-workload"

        [tags]
        repository = "azure-sre-agent"
        environment = "demo"
        owner = "me"
        deployment_id = "local"

        [github]
        repository = "tkubica12/azure-sre-agent"

        [agent]
        name = "sre-agent-demo"
        monthly_aau_allocation = 3000

        [workload]
        alert_notification_email = ""
        alert_threshold_5xx = 3
        log_retention_days = 30

        [paths]
        terraform_state_dir = ".state"
        evidence_dir = ".evidence"
        """,
        encoding="utf-8",
    )

    config = load_config(repo_root=repo_root)

    assert config.azure.region == "swedencentral"
    assert config.source_path == config_path


def test_load_config_reports_toml_parse_errors(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    (repo_root / "config.local.toml").write_text("not = [valid toml", encoding="utf-8")

    with pytest.raises(ConfigError, match="Failed to parse"):
        load_config(repo_root=repo_root)


def test_find_repo_root_walks_up_from_subdirectory(tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    nested = repo_root / "infra" / "environments" / "demo"
    nested.mkdir(parents=True)

    assert find_repo_root(nested) == repo_root


def test_find_repo_root_raises_when_not_found(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Could not locate the repository root"):
        find_repo_root(tmp_path)
