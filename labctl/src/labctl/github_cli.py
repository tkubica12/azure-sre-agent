"""Thin GitHub CLI helper layer.

Shells out to ``gh`` using argument arrays. ``gh auth status`` already masks
token values by default (we never pass ``--show-token``); parsed results here
never include a raw token.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from labctl.procutil import CommandResult, run_command

GH_EXECUTABLE = "gh"
DEFAULT_TIMEOUT = 15.0

#: Signature shared by run_gh and any test double passed as `runner=`.
GhRunner = Callable[..., CommandResult]

_LOGIN_RE = re.compile(r"Logged in to (?P<host>\S+) account (?P<account>\S+)")
_ACTIVE_RE = re.compile(r"Active account:\s*(?P<value>true|false)", re.IGNORECASE)
_SCOPES_RE = re.compile(r"Token scopes:\s*(?P<scopes>.+)")
_MISSING_RE = re.compile(r"Missing required token scopes:\s*(?P<scopes>.+)")
_QUOTED_RE = re.compile(r"'([^']+)'")


def run_gh(
    args: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 0,
    cwd: str | None = None,
) -> CommandResult:
    return run_command([GH_EXECUTABLE, *args], timeout=timeout, retries=retries, cwd=cwd)


def version(*, runner: GhRunner = run_gh) -> CommandResult:
    return runner(["--version"])


def auth_token(
    *, hostname: str = "github.com", runner: GhRunner = run_gh
) -> tuple[str | None, CommandResult]:
    """Return the active ``gh`` CLI token for ``hostname`` (``gh auth
    token``), or ``None`` if not logged in.

    Used to configure the Azure SRE Agent's GitHub source connection with
    the operator's existing GitHub CLI session (see SPEC.md section 10:
    "GitHub connection uses the existing GitHub CLI token in memory"). The
    token is never logged: callers must not print ``result.stdout``
    directly. As defense in depth, :func:`labctl.procutil.redact` also
    matches common GitHub token shapes (``gho_``, ``ghp_``,
    ``github_pat_...``) in any ``CommandResult.diagnostic()`` /
    ``redacted_stdout()`` output.
    """

    result = runner(["auth", "token", "--hostname", hostname])
    if not result.ok:
        return None, result
    token = result.stdout.strip()
    return (token or None), result


@dataclass(frozen=True, slots=True)
class GithubAuthAccount:
    host: str
    account: str
    active: bool
    scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GithubAuthStatus:
    logged_in: bool
    accounts: tuple[GithubAuthAccount, ...]

    def active_account(self) -> GithubAuthAccount | None:
        for account in self.accounts:
            if account.active:
                return account
        return self.accounts[0] if self.accounts else None


def _parse_auth_status(text: str) -> tuple[GithubAuthAccount, ...]:
    accounts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        login_match = _LOGIN_RE.search(line)
        if login_match:
            current = {
                "host": login_match.group("host"),
                "account": login_match.group("account"),
                "active": False,
                "scopes": (),
                "missing_scopes": (),
            }
            accounts.append(current)
            continue
        if current is None:
            continue
        active_match = _ACTIVE_RE.search(line)
        if active_match:
            current["active"] = active_match.group("value").lower() == "true"
            continue
        scopes_match = _SCOPES_RE.search(line)
        if scopes_match:
            current["scopes"] = tuple(_QUOTED_RE.findall(scopes_match.group("scopes")))
            continue
        missing_match = _MISSING_RE.search(line)
        if missing_match:
            current["missing_scopes"] = tuple(_QUOTED_RE.findall(missing_match.group("scopes")))
            continue
    return tuple(GithubAuthAccount(**account) for account in accounts)


def auth_status(
    *,
    hostname: str = "github.com",
    runner: GhRunner = run_gh,
) -> tuple[GithubAuthStatus, CommandResult]:
    result = runner(["auth", "status", "--hostname", hostname])
    accounts = _parse_auth_status(result.stdout + "\n" + result.stderr)
    logged_in = result.ok and any(True for _ in accounts)
    return GithubAuthStatus(logged_in=logged_in, accounts=accounts), result


__all__ = [
    "GH_EXECUTABLE",
    "GithubAuthAccount",
    "GithubAuthStatus",
    "run_gh",
    "version",
    "auth_token",
    "auth_status",
]
