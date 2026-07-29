"""Thin Azure CLI helper layer.

All functions shell out to the ``az`` executable using argument arrays via
:mod:`labctl.procutil`. Nothing here caches credentials or prints secrets;
Azure CLI's own token cache is used implicitly by ``az``.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from labctl.procutil import CommandError, CommandResult, run_command

if TYPE_CHECKING:
    from labctl.config import Config

AZ_EXECUTABLE = "az"
DEFAULT_TIMEOUT = 30.0

#: Signature shared by run_az and any test double passed as `runner=`.
AzRunner = Callable[..., CommandResult]

#: `az` subcommand groups that do not accept (or do not need) a
#: `--subscription` flag: `rest` is scoped by the full resource ID/URL passed
#: to it; `ad`/`account`/`version`/`login`/`logout` operate above or outside
#: subscription scope entirely. Passing `--subscription` to these would
#: either be rejected outright or silently ignored.
_NO_SUBSCRIPTION_COMMAND_GROUPS = frozenset({"rest", "ad", "version", "login", "logout"})

#: Substrings (already lower-cased) that indicate `az ... show`-style
#: nonzero exits mean "the resource genuinely does not exist" rather than an
#: authentication, authorization, or network failure. Anything else is a
#: hard error and must never be silently treated as "not found" (see
#: AGENTS.md and SPEC.md section 11).
_NOT_FOUND_MARKERS: tuple[str, ...] = (
    "resourcegroupnotfound",
    "resourcenotfound",
    "could not be found",
    "was not found",
    "does not exist",
)

# Process-wide pinned subscription, set once via `bind_subscription` after a
# lifecycle command has verified (see `ensure_subscription_context`) that the
# configured subscription matches -- or, if unconfigured, resolved -- the
# active Azure CLI account. Every subsequent `run_az` call is pinned to it
# explicitly with `--subscription`, so the operation cannot silently drift
# onto a different subscription if the ambient Azure CLI default changes
# mid-run (see AGENTS.md B2 / SPEC.md section 8). A lock guards the module
# global since `labctl` is single-threaded in practice but tests may not be.
_subscription_lock = threading.Lock()
_bound_subscription_id: str | None = None


def bind_subscription(subscription_id: str | None) -> None:
    """Pin every subsequent `run_az` call (that supports it) to
    ``subscription_id`` via an explicit ``--subscription`` flag. Pass
    ``None`` to clear the pin (falls back to the ambient Azure CLI default;
    used by tests)."""

    global _bound_subscription_id
    with _subscription_lock:
        _bound_subscription_id = subscription_id or None


def bound_subscription() -> str | None:
    with _subscription_lock:
        return _bound_subscription_id


def is_not_found(result: CommandResult) -> bool:
    """Return ``True`` only when a nonzero `az ... show` exit's stderr
    positively indicates the resource does not exist. Any other nonzero
    exit (auth expired, network failure, permission denied, throttling) must
    be treated by callers as a real failure, never as "confirmed absent"
    (see AGENTS.md and SPEC.md section 11's destroy-ownership contract)."""

    text = result.stderr.lower()
    return any(marker in text for marker in _NOT_FOUND_MARKERS)


def _command_prefix() -> list[str]:
    """Return a shell-free Azure CLI entry point.

    The Windows installer exposes ``az.cmd``. Windows executes batch files
    through ``cmd.exe`` even with ``shell=False``, so argument metacharacters
    can escape into a second command. Invoke the installer's bundled Python
    module directly instead.
    """

    resolved = shutil.which(AZ_EXECUTABLE)
    if resolved is None:
        return [AZ_EXECUTABLE]

    launcher = Path(resolved)
    if launcher.suffix.lower() not in {".bat", ".cmd"}:
        return [resolved]

    bundled_python = launcher.parent.parent / "python.exe"
    if not bundled_python.is_file():
        raise CommandError(
            f"Azure CLI batch launcher found at {launcher}, but its native Python "
            f"entry point is missing at {bundled_python}."
        )
    return [str(bundled_python), "-IBm", "azure.cli"]


def run_az(
    args: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 1,
    cwd: str | None = None,
) -> CommandResult:
    effective_args = list(args)
    subscription_id = bound_subscription()
    command_group = effective_args[0] if effective_args else ""
    if (
        subscription_id
        and command_group not in _NO_SUBSCRIPTION_COMMAND_GROUPS
        and "--subscription" not in effective_args
    ):
        effective_args = [*effective_args, "--subscription", subscription_id]
    return run_command(
        [*_command_prefix(), *effective_args], timeout=timeout, retries=retries, cwd=cwd
    )


def version(*, runner: AzRunner = run_az) -> CommandResult:
    return runner(["version", "--output", "json"], retries=0)


def _parse_json(result: CommandResult) -> Any | None:
    if not result.ok or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True, slots=True)
class Account:
    subscription_id: str
    subscription_name: str
    tenant_id: str
    user_name: str
    user_type: str


def account_show(*, runner: AzRunner = run_az) -> tuple[Account | None, CommandResult]:
    """Return the current ``az account show`` context, or ``None`` if not
    logged in / the call failed.
    """

    result = runner(["account", "show", "--output", "json"], retries=0)
    data = _parse_json(result)
    if not isinstance(data, dict):
        return None, result
    user = data.get("user") or {}
    account = Account(
        subscription_id=str(data.get("id", "")),
        subscription_name=str(data.get("name", "")),
        tenant_id=str(data.get("tenantId", "")),
        user_name=str(user.get("name", "")),
        user_type=str(user.get("type", "")),
    )
    return account, result


def ensure_subscription_context(
    config: Config, *, az_runner: AzRunner = run_az
) -> tuple[Account | None, str | None]:
    """Resolve and pin the Azure subscription/tenant this process operates
    against, called once at the start of every mutating or ownership-
    sensitive lifecycle command (`deploy`, `provision`, `verify`, `destroy`;
    see AGENTS.md and SPEC.md section 8).

    - An `az account show` failure (not logged in, expired token, network
      failure) is always fatal: returns ``(None, message)``. It is never
      silently treated as "nothing configured yet".
    - If `config.azure.subscription_id`/`tenant_id` are set (non-empty) and
      do not match the active Azure CLI account, that mismatch is fatal
      too: returns ``(None, message)``. Earlier behavior only warned here,
      which let `labctl deploy`'s Terraform apply (which does honor a
      configured override) and every other command's ambient-default Azure
      CLI calls silently target two different subscriptions.
    - On success, pins every subsequent `run_az` call in this process to the
      resolved subscription via an explicit ``--subscription`` flag (see
      :func:`bind_subscription`), so later ambient-default drift (for
      example another process on a shared machine running `az account
      set`) cannot change what this command operates against mid-run.
    """

    account, result = account_show(runner=az_runner)
    if account is None:
        return None, (
            "could not query the active Azure CLI account (authentication or network "
            f'failure -- never treated as "nothing to do"): {result.diagnostic()}'
        )

    if config.azure.subscription_id and config.azure.subscription_id != account.subscription_id:
        return None, (
            f"config.local.toml pins azure.subscription_id="
            f"{config.azure.subscription_id!r}, but the active Azure CLI subscription is "
            f"{account.subscription_id!r} ({account.subscription_name!r}). Run `az account "
            "set --subscription <id>` to match config.local.toml, or update "
            "config.local.toml, then retry. This is fatal: proceeding would apply Terraform "
            "against one subscription while other Azure CLI calls target another."
        )
    if config.azure.tenant_id and config.azure.tenant_id != account.tenant_id:
        return None, (
            f"config.local.toml pins azure.tenant_id={config.azure.tenant_id!r}, but the "
            f"active Azure CLI tenant is {account.tenant_id!r}. Run `az login --tenant "
            f"{config.azure.tenant_id}` or update config.local.toml, then retry."
        )

    bind_subscription(account.subscription_id)
    return account, None


def signed_in_object_id(*, runner: AzRunner = run_az) -> tuple[str | None, CommandResult]:
    """Return the object ID of the signed-in principal (user or service
    principal), used to look up effective role assignments.
    """

    result = runner(["ad", "signed-in-user", "show", "--query", "id", "--output", "tsv"], retries=0)
    if not result.ok:
        # Service principals do not have a signed-in-user object; fall back
        # to the account's home account ID which az also exposes via
        # `az account show`. Callers treat a missing object id as WARN, not
        # a hard failure, since role-assignment checks are best-effort.
        return None, result
    object_id = result.stdout.strip()
    return (object_id or None), result


def role_assignments(
    object_id: str,
    scope: str,
    *,
    runner: AzRunner = run_az,
) -> tuple[list[str], CommandResult]:
    """Return role definition names assigned to ``object_id`` at ``scope``
    (not including inherited assignments from higher scopes unless Azure
    itself reports them, which ``--scope`` inclusion does)."""

    result = runner(
        [
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            object_id,
            "--scope",
            scope,
            "--include-inherited",
            "--query",
            "[].roleDefinitionName",
            "--output",
            "json",
        ],
        retries=1,
    )
    data = _parse_json(result)
    if not isinstance(data, list):
        return [], result
    return [str(role) for role in data], result


def provider_show(
    namespace: str, *, runner: AzRunner = run_az
) -> tuple[dict[str, Any] | None, CommandResult]:
    result = runner(
        ["provider", "show", "--namespace", namespace, "--output", "json"],
        retries=1,
    )
    data = _parse_json(result)
    return (data if isinstance(data, dict) else None), result


def resource_group_show(
    name: str, *, runner: AzRunner = run_az
) -> tuple[dict[str, Any] | None, CommandResult]:
    """Return `az group show` output, or ``None`` if the group does not
    exist (a nonzero exit here is expected and not itself an error: callers
    use this both to check ownership tags before a destroy and to confirm
    resources are actually gone after one).
    """

    result = runner(
        ["group", "show", "--name", name, "--output", "json"],
        retries=0,
    )
    return _parse_json(result), result


@dataclass(frozen=True, slots=True)
class ResourceSummary:
    id: str
    type: str
    tags: dict[str, str]


def resource_list(
    resource_group: str, *, runner: AzRunner = run_az
) -> tuple[list[ResourceSummary] | None, CommandResult]:
    """Enumerate every tracked resource directly in ``resource_group`` (its
    ID, type, and tags), used by `labctl destroy` to refuse proceeding when
    an untagged or unexpectedly-tagged resource is present (see SPEC.md
    section 11 and `labctl.destroy`). Returns ``None`` only on a genuine
    query failure, not an empty resource group (which returns ``[]``).
    """

    result = runner(
        [
            "resource",
            "list",
            "--resource-group",
            resource_group,
            "--query",
            "[].{id:id, type:type, tags:tags}",
            "--output",
            "json",
        ],
        timeout=60.0,
        retries=1,
    )
    data = _parse_json(result)
    if not isinstance(data, list):
        return None, result
    summaries = [
        ResourceSummary(
            id=str(item.get("id", "")),
            type=str(item.get("type", "")),
            tags={str(k): str(v) for k, v in (item.get("tags") or {}).items()},
        )
        for item in data
        if isinstance(item, dict)
    ]
    return summaries, result


def resource_type_locations(
    namespace: str,
    resource_type: str,
    *,
    runner: AzRunner = run_az,
) -> tuple[list[str] | None, CommandResult]:
    data, result = provider_show(namespace, runner=runner)
    if data is None:
        return None, result
    for entry in data.get("resourceTypes", []):
        if str(entry.get("resourceType", "")).lower() == resource_type.lower():
            locations = entry.get("locations") or []
            return [str(loc) for loc in locations], result
    return None, result


def rest_call(
    method: str,
    url_path: str,
    *,
    body: str | None = None,
    headers: Mapping[str, str] | None = None,
    runner: AzRunner = run_az,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Any | None, CommandResult]:
    """Call an authenticated ARM endpoint via ``az rest`` and return parsed
    JSON.

    ``body`` is passed as a plain argument-array element (never through a
    shell), which is safe against Windows' ``.cmd``-launcher quoting hazard
    documented in :func:`_command_prefix` -- passing the same JSON string
    through the ``az.cmd`` batch launcher via ``cmd.exe`` (as an interactive
    ``az`` alias would) corrupts embedded quotes; invoking Azure CLI's
    bundled Python entry point directly with an argument array, as this
    helper does, does not (verified live 2026-07-29, see PLAN.md
    Milestone 4).
    """

    args = ["rest", "--method", method, "--url", url_path, "--output", "json"]
    if body is not None:
        args += ["--body", body]
    header_items = dict(headers or {})
    if body is not None and "Content-Type" not in header_items:
        header_items["Content-Type"] = "application/json"
    for key, value in header_items.items():
        args += ["--headers", f"{key}={value}"]
    result = runner(args, timeout=timeout, retries=1)
    return _parse_json(result), result


def rest_get(
    url_path: str,
    *,
    runner: AzRunner = run_az,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Any | None, CommandResult]:
    """Call an authenticated ARM GET via ``az rest`` and return parsed JSON."""

    return rest_call("get", url_path, runner=runner, timeout=timeout)


def access_token(
    resource: str,
    *,
    runner: AzRunner = run_az,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str | None, CommandResult]:
    """Acquire a Microsoft Entra access token for ``resource`` via the
    operator's existing ``az login`` session (``az account
    get-access-token``).

    Used to obtain the Azure SRE Agent data-plane token, whose audience
    (``https://azuresre.dev``) is distinct from the ARM management-plane
    audience implicitly used by :func:`rest_call`/:func:`rest_get` (see
    SPEC.md sections 3 and 11). The returned token is never logged: callers
    must not print ``result.stdout`` directly. As defense in depth,
    :func:`labctl.procutil.redact` also matches JWT-shaped strings (Entra
    access tokens included) in any ``CommandResult.diagnostic()`` /
    ``redacted_stdout()`` output.
    """

    result = runner(
        [
            "account",
            "get-access-token",
            "--resource",
            resource,
            "--query",
            "accessToken",
            "--output",
            "tsv",
        ],
        timeout=timeout,
        retries=1,
    )
    if not result.ok:
        return None, result
    token = result.stdout.strip()
    return (token or None), result


__all__ = [
    "AZ_EXECUTABLE",
    "Account",
    "run_az",
    "version",
    "account_show",
    "ensure_subscription_context",
    "bind_subscription",
    "bound_subscription",
    "is_not_found",
    "signed_in_object_id",
    "role_assignments",
    "provider_show",
    "resource_group_show",
    "ResourceSummary",
    "resource_list",
    "resource_type_locations",
    "rest_get",
    "rest_call",
    "access_token",
]
