"""labctl command-line interface.

Implements the full command surface required by AGENTS.md (see PLAN.md for
milestone history: every lifecycle command is implemented as of Milestone 5).
"""

from __future__ import annotations

import contextlib
import sys

import click

from labctl.config import Config, ConfigError, load_config
from labctl.deploy import run_deploy
from labctl.destroy import run_destroy
from labctl.evidence import run_evidence_collect
from labctl.preflight import run_preflight, summarize
from labctl.provision import run_provision
from labctl.scenario import (
    run_demo_list,
    run_demo_prepare,
    run_demo_reset,
    run_demo_trigger,
    run_demo_verify,
)
from labctl.status import run_status
from labctl.verify import run_verify


def _load_config_or_exit() -> Config:
    try:
        return load_config()
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2) from exc


def _use_utf8_console_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8 with lossy replacement instead of
    raising.

    Terraform's own plan/apply output legitimately contains non-ASCII
    characters (for example the box-drawing U+2500 "-" used as a section
    separator). Windows PowerShell's default console code page (cp1252) does
    not encode that, so plain `print`/`click.echo` on such text raises
    `UnicodeEncodeError` and crashes labctl (observed live running `labctl
    destroy --plan-only`, see PLAN.md Milestone 3). Called from the `cli()`
    group itself (not just `main()`) so it also applies when invoked through
    the packaged `labctl.cli:cli` console-script entry point. `reconfigure`
    failures are caught and ignored on streams that do not support it (e.g.
    when stdout is fully replaced by a test harness).
    """

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


@click.group()
@click.version_option(package_name="labctl")
def cli() -> None:
    """Operator CLI for the Azure SRE Agent demonstration lifecycle."""
    _use_utf8_console_streams()


@cli.command()
def preflight() -> None:
    """Check tools, Azure/GitHub auth, permissions, provider registration,
    region/model support, and local configuration. Read-only; nonzero exit on
    any failed check.
    """
    config = _load_config_or_exit()
    results = run_preflight(config)
    table, exit_code = summarize(results)
    click.echo(table)
    raise SystemExit(exit_code)


@cli.command()
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm applying real Azure changes. Without it, deploy only plans and reports.",
)
@click.option(
    "--plan-only",
    is_flag=True,
    default=False,
    help="Only run `terraform plan`; never apply, build, or update the Container App.",
)
@click.option(
    "--skip-build",
    is_flag=True,
    default=False,
    help="Skip `az acr build` and reuse the currently deployed image (infra-only iteration).",
)
def deploy(yes: bool, plan_only: bool, skip_build: bool) -> None:
    """Initialize Terraform, apply infrastructure, build the workload image,
    update the Container App to an immutable baseline revision, warm it, and
    verify the result.
    """
    config = _load_config_or_exit()
    result = run_deploy(config, yes=yes, plan_only=plan_only, skip_build=skip_build)
    raise SystemExit(result.exit_code)


@cli.command()
def provision() -> None:
    """Idempotently apply Azure SRE Agent data-plane configuration."""
    config = _load_config_or_exit()
    result = run_provision(config)
    raise SystemExit(result.exit_code)


@cli.command()
def verify() -> None:
    """Validate resources, identities, RBAC, telemetry, alerting, and agent
    extensions.
    """
    config = _load_config_or_exit()
    raise SystemExit(run_verify(config))


@cli.command()
def status() -> None:
    """Summarize current local and Azure state with portal deep links."""
    config = _load_config_or_exit()
    raise SystemExit(run_status(config))


@cli.group()
def demo() -> None:
    """Scenario lifecycle commands (prepare, trigger, verify, reset)."""


@demo.command("list")
def demo_list() -> None:
    """Show scenarios, prerequisites, current readiness, and expected duration."""
    config = _load_config_or_exit()
    result = run_demo_list(config)
    raise SystemExit(result.exit_code)


@demo.command("prepare")
@click.argument("scenario")
def demo_prepare(scenario: str) -> None:
    """Restore baseline, warm telemetry, and confirm no active fault."""
    config = _load_config_or_exit()
    result = run_demo_prepare(config, scenario)
    raise SystemExit(result.exit_code)


@demo.command("trigger")
@click.argument("scenario")
def demo_trigger(scenario: str) -> None:
    """Create the fault revision, shift traffic, and generate load."""
    config = _load_config_or_exit()
    result = run_demo_trigger(config, scenario)
    raise SystemExit(result.exit_code)


@demo.command("verify")
@click.argument("scenario")
def demo_verify(scenario: str) -> None:
    """Verify the expected fault or recovered state."""
    config = _load_config_or_exit()
    result = run_demo_verify(config, scenario)
    raise SystemExit(result.exit_code)


@demo.command("reset")
@click.argument("scenario")
def demo_reset(scenario: str) -> None:
    """Restore known-good traffic and verify recovery."""
    config = _load_config_or_exit()
    result = run_demo_reset(config, scenario)
    raise SystemExit(result.exit_code)


@cli.group()
def evidence() -> None:
    """Evidence collection commands."""


@evidence.command("collect")
def evidence_collect() -> None:
    """Save redacted JSON, logs, KQL results, alert state, and revision state."""
    config = _load_config_or_exit()
    result = run_evidence_collect(config)
    raise SystemExit(result.exit_code)


@cli.command()
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Confirm permanently destroying every resource this deployment owns.",
)
@click.option(
    "--plan-only",
    is_flag=True,
    default=False,
    help="Only run `terraform plan -destroy`; never destroy anything.",
)
@click.option(
    "--allow-unrecognized-resources",
    is_flag=True,
    default=False,
    help=(
        "Proceed even if a resource inside an owned resource group does not carry this "
        "deployment's ownership tags and is not a recognized child resource. Review the "
        "printed resource IDs before using this."
    ),
)
def destroy(yes: bool, plan_only: bool, allow_unrecognized_resources: bool) -> None:
    """Confirm ownership, destroy Terraform resources, and report retained resources."""
    config = _load_config_or_exit()

    def confirm_unrecognized_resource_group(expected_name: str) -> bool:
        typed = str(
            click.prompt(
                "Unrecognized resources were found. Type the affected resource group name "
                f"({expected_name}) to confirm the override",
                default="",
                show_default=False,
            )
        )
        return typed == expected_name

    result = run_destroy(
        config,
        yes=yes,
        plan_only=plan_only,
        allow_unrecognized_resources=allow_unrecognized_resources,
        confirm_unrecognized_resource_group=(
            confirm_unrecognized_resource_group if allow_unrecognized_resources else None
        ),
    )
    raise SystemExit(result.exit_code)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
