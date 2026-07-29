"""Preflight checks for the Azure SRE Agent demonstration.

`labctl preflight` is the only fully implemented lifecycle command in
Milestone 1. It is read-only: no Azure resource, role assignment, or file
outside the local config/state/evidence directories is ever created here.

Every check function accepts injectable runner callables so unit tests can
substitute fakes instead of shelling out to real tools.
"""

from __future__ import annotations

import re
import shutil
import socket
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from labctl import azure_cli, github_cli, terraform_cli
from labctl.config import Config
from labctl.procutil import CommandResult

# The API version confirmed against the published ARM schema for
# Microsoft.App/SreAgent (SupportedAgentModels_ListByLocation) as of the
# research date in SPEC.md. Re-verify against
# https://github.com/Azure/azure-rest-api-specs/tree/main/specification/app/resource-manager/Microsoft.App/SreAgent
# before bumping.
SUPPORTED_AGENT_MODELS_API_VERSION = "2026-01-01"

# Roles that satisfy "can create resources" and "can assign roles"
# respectively, matching SPEC.md section 9 (High-access, Contributor-scoped
# identities plus an Owner/User Access Administrator style deployer).
_RESOURCE_CREATION_ROLES = frozenset({"Owner", "Contributor"})
_ROLE_ASSIGNMENT_ROLES = frozenset(
    {"Owner", "User Access Administrator", "Role Based Access Control Administrator"}
)

# Minimum tool versions. These are deliberately conservative floors, not the
# versions the repository is validated against (see PLAN.md environment facts).
_MIN_AZ_VERSION = (2, 60, 0)
_MIN_GH_VERSION = (2, 40, 0)
_MIN_TERRAFORM_VERSION = (1, 9, 0)
_MIN_PYTHON_VERSION = (3, 11, 0)

# Hostnames documented for the Azure SRE Agent portal and data plane. See
# SPEC.md section 11 ("The data-plane endpoint uses *.azuresre.ai ...").
_PORTAL_HOST = "sre.azure.com"
_DATA_PLANE_BASE_DOMAIN = "azuresre.ai"


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: Status
    detail: str


def _parse_version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        return None
    return tuple(int(g) for g in match.groups() if g is not None)


def _normalize_region(name: str) -> str:
    return re.sub(r"[\s_-]+", "", name).lower()


# --------------------------------------------------------------------------
# Tool versions
# --------------------------------------------------------------------------


def check_tool_versions(
    *,
    which: Callable[[str], str | None] = shutil.which,
    az_runner: azure_cli.AzRunner = azure_cli.run_az,
    gh_runner: github_cli.GhRunner = github_cli.run_gh,
    terraform_cwd: str | Path = ".",
    tf_runner: terraform_cli.TerraformRunner | None = None,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    py_version = sys.version_info[:3]
    py_version_str = ".".join(map(str, py_version))
    py_min_str = ".".join(map(str, _MIN_PYTHON_VERSION))
    if py_version >= _MIN_PYTHON_VERSION:
        results.append(
            CheckResult("tool-python", Status.PASS, f"Python {py_version_str} (>= {py_min_str})")
        )
    else:
        results.append(
            CheckResult(
                "tool-python",
                Status.FAIL,
                f"Python {py_version_str} is older than the required {py_min_str}.",
            )
        )

    results.append(
        _check_one_tool_version(
            check_name="tool-az",
            executable="az",
            which=which,
            min_version=_MIN_AZ_VERSION,
            probe=lambda: azure_cli.version(runner=az_runner),
            extract=lambda r: _extract_json_field(r, "azure-cli"),
        )
    )
    results.append(
        _check_one_tool_version(
            check_name="tool-gh",
            executable="gh",
            which=which,
            min_version=_MIN_GH_VERSION,
            probe=lambda: github_cli.version(runner=gh_runner),
            extract=lambda r: r.stdout,
        )
    )
    results.append(
        _check_one_tool_version(
            check_name="tool-terraform",
            executable="terraform",
            which=which,
            min_version=_MIN_TERRAFORM_VERSION,
            probe=lambda: terraform_cli.version(runner=tf_runner, cwd=terraform_cwd),
            extract=lambda r: r.stdout,
        )
    )
    return results


def _extract_json_field(result: CommandResult, field: str) -> str:
    import json

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout
    value = data.get(field)
    return str(value) if value is not None else result.stdout


def _check_one_tool_version(
    *,
    check_name: str,
    executable: str,
    which: Callable[[str], str | None],
    min_version: tuple[int, int, int],
    probe: Callable[[], CommandResult],
    extract: Callable[[CommandResult], str],
) -> CheckResult:
    path = which(executable)
    if not path:
        return CheckResult(check_name, Status.FAIL, f"{executable} was not found on PATH.")

    result = probe()
    if not result.ok:
        return CheckResult(
            check_name,
            Status.FAIL,
            f"Failed to run `{executable} --version`-equivalent: {result.diagnostic()}",
        )

    version_text = extract(result)
    parsed = _parse_version(version_text)
    min_str = ".".join(map(str, min_version))
    if parsed is None:
        return CheckResult(
            check_name,
            Status.WARN,
            f"Found {executable} at {path} but could not parse its version from output.",
        )
    parsed_str = ".".join(map(str, parsed))
    if parsed >= min_version:
        return CheckResult(
            check_name,
            Status.PASS,
            f"{executable} {parsed_str} at {path} (>= {min_str})",
        )
    return CheckResult(
        check_name,
        Status.FAIL,
        f"{executable} {parsed_str} at {path} is older than the required {min_str}.",
    )


# --------------------------------------------------------------------------
# Azure login, permissions, provider registration, region/model support
# --------------------------------------------------------------------------


def check_azure_login(
    config: Config, *, az_runner: azure_cli.AzRunner = azure_cli.run_az
) -> CheckResult:
    account, message = azure_cli.ensure_subscription_context(config, az_runner=az_runner)
    if account is None:
        return CheckResult("azure-login", Status.FAIL, message or "unknown Azure CLI failure.")
    detail = (
        f"Logged in as {account.user_name or '<unknown>'} ({account.user_type or 'user'}); "
        f"subscription '{account.subscription_name}' ({account.subscription_id}); tenant "
        f"{account.tenant_id}."
    )
    return CheckResult("azure-login", Status.PASS, detail)


def check_azure_permissions(
    config: Config, *, az_runner: azure_cli.AzRunner = azure_cli.run_az
) -> CheckResult:
    account, account_result = azure_cli.account_show(runner=az_runner)
    if account is None:
        return CheckResult(
            "azure-permissions",
            Status.FAIL,
            f"Cannot evaluate permissions without an Azure login: {account_result.diagnostic()}",
        )

    object_id, id_result = azure_cli.signed_in_object_id(runner=az_runner)
    if object_id is None:
        return CheckResult(
            "azure-permissions",
            Status.WARN,
            "Could not resolve the signed-in principal's object ID (likely a service "
            f"principal). Verify resource and role-assignment permissions manually: "
            f"{id_result.diagnostic()}",
        )

    scope = f"/subscriptions/{account.subscription_id}"
    roles, roles_result = azure_cli.role_assignments(object_id, scope, runner=az_runner)
    if not roles_result.ok:
        return CheckResult(
            "azure-permissions",
            Status.WARN,
            f"Could not list role assignments at {scope}: {roles_result.diagnostic()}",
        )

    role_set = set(roles)
    can_create = bool(role_set & _RESOURCE_CREATION_ROLES)
    can_assign = bool(role_set & _ROLE_ASSIGNMENT_ROLES)
    roles_display = ", ".join(sorted(role_set)) or "none"

    if can_create and can_assign:
        return CheckResult(
            "azure-permissions",
            Status.PASS,
            f"Effective roles at {scope}: {roles_display} "
            "(covers resource creation and role assignment).",
        )
    if can_create or can_assign:
        missing = "role assignment" if can_create else "resource creation"
        return CheckResult(
            "azure-permissions",
            Status.WARN,
            f"Effective roles at {scope}: {roles_display}. Missing a role granting {missing} "
            "(e.g. Owner) needed for the full deploy/destroy lifecycle.",
        )
    return CheckResult(
        "azure-permissions",
        Status.FAIL,
        f"Effective roles at {scope}: {roles_display}. Need Owner, or Contributor plus "
        "User Access Administrator / Role Based Access Control Administrator, to deploy "
        "resources and grant agent role assignments.",
    )


def check_provider_registration(*, az_runner: azure_cli.AzRunner = azure_cli.run_az) -> CheckResult:
    data, result = azure_cli.provider_show("Microsoft.App", runner=az_runner)
    if data is None:
        return CheckResult(
            "provider-microsoft-app",
            Status.FAIL,
            f"Could not query the Microsoft.App resource provider: {result.diagnostic()}",
        )
    state = str(data.get("registrationState", "Unknown"))
    if state == "Registered":
        return CheckResult("provider-microsoft-app", Status.PASS, "Microsoft.App is Registered.")
    if state == "Registering":
        return CheckResult(
            "provider-microsoft-app",
            Status.WARN,
            "Microsoft.App registration is in progress (Registering). Re-run preflight shortly.",
        )
    return CheckResult(
        "provider-microsoft-app",
        Status.FAIL,
        f"Microsoft.App is not registered (state: {state}). Run "
        "`az provider register --namespace Microsoft.App`.",
    )


def check_agent_region_support(
    config: Config, *, az_runner: azure_cli.AzRunner = azure_cli.run_az
) -> CheckResult:
    locations, result = azure_cli.resource_type_locations(
        "Microsoft.App", "agents", runner=az_runner
    )
    if locations is None:
        return CheckResult(
            "agent-region-support",
            Status.WARN,
            f"Could not read Microsoft.App/agents supported locations: {result.diagnostic()}. "
            "Confirm manually: https://learn.microsoft.com/azure/sre-agent/supported-regions",
        )
    normalized = {_normalize_region(loc) for loc in locations}
    if _normalize_region(config.azure.region) in normalized:
        return CheckResult(
            "agent-region-support",
            Status.PASS,
            f"'{config.azure.region}' is a supported Microsoft.App/agents location "
            "in this subscription.",
        )
    return CheckResult(
        "agent-region-support",
        Status.FAIL,
        f"'{config.azure.region}' is not among the Microsoft.App/agents locations reported for "
        f"this subscription: {sorted(locations)}.",
    )


def check_agent_model_availability(
    config: Config, *, az_runner: azure_cli.AzRunner = azure_cli.run_az
) -> CheckResult:
    account, account_result = azure_cli.account_show(runner=az_runner)
    if account is None:
        return CheckResult(
            "agent-model-availability",
            Status.WARN,
            "Cannot query supported agent models without an Azure login: "
            f"{account_result.diagnostic()}",
        )
    url = (
        f"/subscriptions/{account.subscription_id}/providers/Microsoft.App/locations/"
        f"{config.azure.region}/supportedAgentModels?api-version={SUPPORTED_AGENT_MODELS_API_VERSION}"
    )
    data, result = azure_cli.rest_get(url, runner=az_runner)
    if data is None:
        return CheckResult(
            "agent-model-availability",
            Status.WARN,
            "Could not verify available Azure SRE Agent models via ARM "
            f"(SupportedAgentModels_ListByLocation, "
            f"api-version={SUPPORTED_AGENT_MODELS_API_VERSION}): "
            f"{result.diagnostic()}. Confirm manually: "
            "https://learn.microsoft.com/azure/sre-agent/supported-regions",
        )
    models = data.get("value", []) if isinstance(data, dict) else []
    if not models:
        return CheckResult(
            "agent-model-availability",
            Status.WARN,
            f"ARM reported zero supported agent models for '{config.azure.region}'.",
        )
    names = [str(m.get("name", m.get("id", "?"))) for m in models]
    return CheckResult(
        "agent-model-availability",
        Status.PASS,
        f"{len(names)} supported agent model(s) in '{config.azure.region}': {', '.join(names)}",
    )


# --------------------------------------------------------------------------
# GitHub authentication
# --------------------------------------------------------------------------

_REQUIRED_GITHUB_SCOPES = frozenset({"repo"})


def check_github_auth(*, gh_runner: github_cli.GhRunner = github_cli.run_gh) -> CheckResult:
    status, result = github_cli.auth_status(runner=gh_runner)
    if not status.logged_in:
        return CheckResult(
            "github-auth",
            Status.FAIL,
            f"Not logged in to GitHub CLI (run `gh auth login`): {result.diagnostic()}",
        )
    account = status.active_account()
    if account is None:
        return CheckResult("github-auth", Status.WARN, "GitHub CLI reported no active account.")

    scopes = set(account.scopes)
    missing_required = _REQUIRED_GITHUB_SCOPES - scopes
    scopes_display = ", ".join(sorted(scopes)) or "none"
    detail = f"Logged in to {account.host} as {account.account}; scopes: {scopes_display}."
    if missing_required:
        return CheckResult(
            "github-auth",
            Status.FAIL,
            f"{detail} Missing required scope(s): {', '.join(sorted(missing_required))}. "
            "Run `gh auth refresh -h github.com -s repo`.",
        )
    if account.missing_scopes:
        return CheckResult(
            "github-auth",
            Status.WARN,
            f"{detail} gh reports additional recommended scope(s) missing: "
            f"{', '.join(sorted(account.missing_scopes))}.",
        )
    return CheckResult("github-auth", Status.PASS, detail)


# --------------------------------------------------------------------------
# Local configuration and state paths
# --------------------------------------------------------------------------


def check_local_config(config: Config) -> CheckResult:
    return CheckResult(
        "local-config",
        Status.PASS,
        f"Loaded {config.source_path} (region={config.azure.region}, "
        f"agent_rg={config.resource_groups.agent}, workload_rg={config.resource_groups.workload}).",
    )


def _check_writable_directory(name: str, path: Path) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".labctl-preflight-", delete=True):
            pass
    except OSError as exc:
        return CheckResult(name, Status.FAIL, f"{path} is not writable: {exc}")
    return CheckResult(name, Status.PASS, f"{path} exists and is writable.")


def check_local_state_paths(config: Config) -> list[CheckResult]:
    return [
        _check_writable_directory("local-state-path", config.terraform_state_path()),
        _check_writable_directory("local-evidence-path", config.evidence_path()),
    ]


# --------------------------------------------------------------------------
# Network / DNS
# --------------------------------------------------------------------------

_ResolverT = Callable[[str, int], list[Any]]


def _resolve_host(name: str, host: str, resolver: _ResolverT) -> CheckResult:
    try:
        resolver(host, 443)
    except socket.gaierror as exc:
        return CheckResult(
            name,
            Status.WARN,
            f"Could not resolve '{host}': {exc}. Verify network/DNS access before deploying.",
        )
    return CheckResult(name, Status.PASS, f"Resolved '{host}'.")


def check_network_dns(config: Config, *, resolver: _ResolverT | None = None) -> list[CheckResult]:
    resolve = resolver or (lambda host, port: socket.getaddrinfo(host, port))
    results = [_resolve_host("network-dns-portal", _PORTAL_HOST, resolve)]
    data_plane_host = config.agent.data_plane_endpoint or _DATA_PLANE_BASE_DOMAIN
    results.append(_resolve_host("network-dns-data-plane", data_plane_host, resolve))
    return results


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run_preflight(config: Config) -> list[CheckResult]:
    """Run every preflight check and return the flat list of results.

    This function performs read-only operations only: CLI version/auth
    checks, ARM read calls, DNS resolution, and creating (but not writing
    meaningful content into) the local state/evidence directories.
    """

    results: list[CheckResult] = []
    results.extend(check_tool_versions(terraform_cwd=config.repo_root))
    results.append(check_azure_login(config))
    results.append(check_azure_permissions(config))
    results.append(check_provider_registration())
    results.append(check_agent_region_support(config))
    results.append(check_agent_model_availability(config))
    results.append(check_github_auth())
    results.append(check_local_config(config))
    results.extend(check_local_state_paths(config))
    results.extend(check_network_dns(config))
    return results


def summarize(results: list[CheckResult]) -> tuple[str, int]:
    """Render a human-readable summary table and compute the process exit code."""

    counts = {Status.PASS: 0, Status.WARN: 0, Status.FAIL: 0}
    lines = []
    name_width = max((len(r.name) for r in results), default=4)
    for r in results:
        counts[r.status] += 1
        lines.append(f"[{r.status.value:<4}] {r.name.ljust(name_width)}  {r.detail}")

    summary = (
        f"\n{counts[Status.PASS]} passed, {counts[Status.WARN]} warned, "
        f"{counts[Status.FAIL]} failed."
    )
    exit_code = 1 if counts[Status.FAIL] else 0
    return "\n".join(lines) + summary, exit_code


__all__ = [
    "SUPPORTED_AGENT_MODELS_API_VERSION",
    "Status",
    "CheckResult",
    "check_tool_versions",
    "check_azure_login",
    "check_azure_permissions",
    "check_provider_registration",
    "check_agent_region_support",
    "check_agent_model_availability",
    "check_github_auth",
    "check_local_config",
    "check_local_state_paths",
    "check_network_dns",
    "run_preflight",
    "summarize",
]
