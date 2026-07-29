"""Thin Terraform CLI helper layer.

Only the subset needed through Milestone 1 is implemented: version, fmt
check, init, and validate. ``plan``/``apply``/``destroy`` are added when
`labctl deploy`/`destroy` are implemented in later milestones.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from labctl.procutil import CommandResult, run_command

TERRAFORM_EXECUTABLE = "terraform"
DEFAULT_TIMEOUT = 120.0

#: Signature shared by run_terraform and any test double passed as `runner=`.
TerraformRunner = Callable[..., CommandResult]


def run_terraform(
    args: Sequence[str],
    *,
    cwd: str | Path,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 0,
) -> CommandResult:
    return run_command([TERRAFORM_EXECUTABLE, *args], cwd=cwd, timeout=timeout, retries=retries)


def version(*, runner: TerraformRunner | None = None, cwd: str | Path = ".") -> CommandResult:
    call = runner or run_terraform
    return call(["version", "-json"], cwd=cwd, timeout=30.0)


def fmt_check(cwd: str | Path, *, runner: TerraformRunner | None = None) -> CommandResult:
    call = runner or run_terraform
    return call(["fmt", "-check", "-recursive", "-diff"], cwd=cwd, timeout=30.0)


def init(
    cwd: str | Path, *, runner: TerraformRunner | None = None, timeout: float = 300.0
) -> CommandResult:
    call = runner or run_terraform
    return call(["init", "-input=false", "-backend=false"], cwd=cwd, timeout=timeout)


def init_backend(
    cwd: str | Path, *, runner: TerraformRunner | None = None, timeout: float = 300.0
) -> CommandResult:
    """Initialize Terraform with its configured local backend (see
    versions.tf), required before plan/apply/destroy/output can read or
    write real state.
    """

    call = runner or run_terraform
    return call(["init", "-input=false"], cwd=cwd, timeout=timeout)


def validate(cwd: str | Path, *, runner: TerraformRunner | None = None) -> CommandResult:
    call = runner or run_terraform
    return call(["validate", "-json"], cwd=cwd, timeout=60.0)


def plan(
    cwd: str | Path,
    *,
    var_file: str | Path,
    out_file: str | Path,
    destroy: bool = False,
    runner: TerraformRunner | None = None,
    timeout: float = 300.0,
) -> CommandResult:
    call = runner or run_terraform
    args = ["plan", "-input=false", f"-var-file={var_file}", f"-out={out_file}"]
    if destroy:
        args.append("-destroy")
    return call(args, cwd=cwd, timeout=timeout)


def apply(
    cwd: str | Path,
    *,
    plan_file: str | Path,
    runner: TerraformRunner | None = None,
    timeout: float = 900.0,
) -> CommandResult:
    call = runner or run_terraform
    return call(
        ["apply", "-input=false", "-auto-approve", str(plan_file)], cwd=cwd, timeout=timeout
    )


def destroy(
    cwd: str | Path,
    *,
    var_file: str | Path,
    runner: TerraformRunner | None = None,
    timeout: float = 900.0,
) -> CommandResult:
    """Destroy every resource this Terraform state owns.

    Unlike ``apply``, ``terraform destroy`` accepts ``-var-file`` directly
    without a pre-computed plan, since there is no separate immutable
    artifact to review here beyond the state file itself.
    """

    call = runner or run_terraform
    return call(
        ["destroy", "-input=false", "-auto-approve", f"-var-file={var_file}"],
        cwd=cwd,
        timeout=timeout,
    )


def output_json(
    cwd: str | Path, *, runner: TerraformRunner | None = None, timeout: float = 60.0
) -> CommandResult:
    call = runner or run_terraform
    return call(["output", "-json"], cwd=cwd, timeout=timeout)


def show_plan_json(
    cwd: str | Path,
    *,
    plan_file: str | Path,
    runner: TerraformRunner | None = None,
    timeout: float = 120.0,
) -> CommandResult:
    """Render a saved plan file as JSON, used to summarize pending changes
    before an operator confirms with ``--yes``.
    """

    call = runner or run_terraform
    return call(["show", "-json", str(plan_file)], cwd=cwd, timeout=timeout)


def state_list(
    cwd: str | Path, *, runner: TerraformRunner | None = None, timeout: float = 60.0
) -> CommandResult:
    call = runner or run_terraform
    return call(["state", "list"], cwd=cwd, timeout=timeout)


__all__ = [
    "TERRAFORM_EXECUTABLE",
    "run_terraform",
    "version",
    "fmt_check",
    "init",
    "init_backend",
    "validate",
    "plan",
    "apply",
    "destroy",
    "output_json",
    "show_plan_json",
    "state_list",
]
