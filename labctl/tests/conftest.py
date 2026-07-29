from __future__ import annotations

from pathlib import Path

import pytest

from labctl import azure_cli
from labctl.config import (
    AgentConfig,
    AzureConfig,
    Config,
    GithubConfig,
    PathsConfig,
    ResourceGroupsConfig,
    TagsConfig,
    WorkloadConfig,
)
from labctl.procutil import CommandResult


@pytest.fixture(autouse=True)
def _reset_bound_subscription():
    """`azure_cli.bind_subscription` sets process-wide state so every
    `run_az` call in the same process is pinned to one subscription (see
    B2 fix). Reset it around every test so no test's real
    `ensure_subscription_context` call (e.g. in test_preflight.py) can leak
    a bound subscription into an unrelated test that exercises the real
    `run_az` (e.g. test_azure_cli.py)."""

    azure_cli.bind_subscription(None)
    yield
    azure_cli.bind_subscription(None)


def make_config(tmp_path: Path, **overrides: object) -> Config:
    defaults: dict[str, object] = dict(
        repo_root=tmp_path,
        source_path=tmp_path / "config.local.toml",
        azure=AzureConfig(region="swedencentral", subscription_id="sub-1", tenant_id="tenant-1"),
        resource_groups=ResourceGroupsConfig(agent="rg-agent", workload="rg-workload"),
        tags=TagsConfig(
            repository="azure-sre-agent", environment="demo", owner="me", deployment_id="local"
        ),
        github=GithubConfig(repository="tkubica12/azure-sre-agent"),
        agent=AgentConfig(name="sre-agent-demo", monthly_aau_allocation=3000),
        workload=WorkloadConfig(
            alert_notification_email="", alert_threshold_5xx=3, log_retention_days=30
        ),
        paths=PathsConfig(terraform_state_dir=".state", evidence_dir=".evidence"),
    )
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


def make_result(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    timed_out: bool = False,
    attempts: int = 1,
    args: tuple[str, ...] = ("fake",),
) -> CommandResult:
    """Build a CommandResult for tests without spawning a real process."""

    return CommandResult(
        args=args,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.001,
        timed_out=timed_out,
        attempts=attempts,
    )


@pytest.fixture
def result_factory():
    return make_result
