"""Robust subprocess execution with bounded timeouts, retries, and secret
redaction for logging and diagnostics.

Every external tool invocation in labctl (``az``, ``gh``, ``terraform``) goes
through :func:`run_command` so behavior is consistent: argument-array
execution only (never ``shell=True``), explicit timeouts, bounded retries with
backoff, and redacted text for anything that gets logged or printed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

#: Patterns matching common secret shapes that must never appear in logs.
#: Each pattern's first capture group (if any) is preserved; the sensitive
#: remainder is replaced with a fixed placeholder.
_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-\._~\+/]+=*"),
    re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"),
    re.compile(r"(?i)(AccountKey|SharedAccessKey|AccessKey)=[^;\s]+"),
    # Application Insights connection strings (e.g. "InstrumentationKey=<guid>;
    # IngestionEndpoint=https://...;LiveEndpoint=https://...;ApplicationId=<guid>").
    # `\S+` intentionally swallows the whole semicolon-delimited tail up to
    # the next whitespace, since a real connection string never contains a
    # space (see AGENTS.md and SPEC.md section 9 "M5").
    re.compile(r"(?i)InstrumentationKey=\S+"),
    re.compile(r"(?i)\b(password|passwd|secret|client_secret|token|api[_-]?key)\b\s*[:=]\s*\S+"),
)
_REDACTED = "***REDACTED***"


def redact(text: str) -> str:
    """Replace known secret shapes in ``text`` with a fixed placeholder.

    This is defense in depth: individual helpers should already avoid
    requesting secrets, but any subprocess output that is logged or printed
    must pass through this function first.
    """

    redacted = text
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


class CommandError(RuntimeError):
    """Raised when a command cannot be executed at all (for example, the
    executable is not installed). This is distinct from the command running
    and returning a nonzero exit code, which callers inspect via
    ``CommandResult``.
    """


@dataclass(frozen=True, slots=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    attempts: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def redacted_stdout(self) -> str:
        return redact(self.stdout)

    def redacted_stderr(self) -> str:
        return redact(self.stderr)

    def redacted_command(self) -> str:
        return redact(" ".join(self.args))

    def diagnostic(self) -> str:
        """A one-line, secret-safe summary suitable for logging on failure."""

        status = "timed out" if self.timed_out else f"exit code {self.returncode}"
        return f"`{self.redacted_command()}` ({status}, attempts={self.attempts})"


def run_command(
    args: Sequence[str],
    *,
    timeout: float = 30.0,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    retries: int = 0,
    retry_delay: float = 2.0,
) -> CommandResult:
    """Run an external command as an argument array and capture its output.

    Args:
        args: The full argument vector, e.g. ``["az", "account", "show"]``.
            Never a shell string.
        timeout: Bounded timeout in seconds for each individual attempt.
        cwd: Working directory for the subprocess.
        env: Full environment to use. ``None`` inherits the current process
            environment unchanged.
        retries: Number of additional attempts after the first failure.
            Retries apply to nonzero exit codes and timeouts alike.
        retry_delay: Seconds to sleep between attempts (linear backoff is
            deliberately avoided here to keep preflight/verify latency
            bounded and predictable).

    Returns:
        A ``CommandResult`` describing the final attempt. It never raises for
        a nonzero exit code or a timeout; callers decide whether that is a
        failure. It raises :class:`CommandError` only when the executable
        itself cannot be launched (e.g. not installed).
    """

    if not args:
        raise CommandError("run_command requires a non-empty argument vector.")
    if timeout <= 0:
        raise CommandError(f"timeout must be positive, got {timeout}.")
    if retries < 0:
        raise CommandError(f"retries must be zero or positive, got {retries}.")

    argv = tuple(str(a) for a in args)

    # Resolve the executable through PATH (and, on Windows, PATHEXT) up front.
    resolved = shutil.which(argv[0])
    if resolved is not None:
        argv = (resolved, *argv[1:])

    # Windows silently routes .cmd/.bat targets through cmd.exe even when
    # shell=False, allowing metacharacters inside an argument to become a
    # second command. Callers must select a native executable instead (the
    # Azure CLI helper, for example, invokes Azure CLI's bundled Python).
    if Path(argv[0]).suffix.lower() in {".bat", ".cmd"}:
        raise CommandError(
            f"Refusing to execute Windows batch launcher {argv[0]!r}; "
            "use its native executable entry point instead."
        )

    # Force UTF-8 for any subprocess (in particular Azure CLI's bundled
    # Python interpreter): when stdout/stderr are pipes rather than a real
    # console, Python falls back to the Windows ANSI code page and crashes
    # on non-ASCII output (observed with `az acr build`'s streamed logs).
    # These variables are harmless to non-Python executables like
    # terraform.exe and gh.exe. Only applied when the caller has not
    # supplied an explicit environment, to respect an explicit contract.
    effective_env: dict[str, str] | None
    if env is not None:
        effective_env = dict(env)
    else:
        effective_env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            # Azure CLI wraps stdout with colorama on Windows for ANSI color
            # support. When stdout is a pipe (as it always is here, since
            # every command is captured) and remote output contains
            # non-ASCII bytes, colorama's console-color path can crash with
            # a UnicodeEncodeError against the legacy Windows code page
            # regardless of PYTHONIOENCODING (observed with `az acr build`
            # streaming remote build logs). Disabling color output entirely
            # avoids that code path.
            "AZURE_CORE_NO_COLOR": "true",
        }

    attempts = 0
    last_result: CommandResult | None = None

    while attempts <= retries:
        attempts += 1
        start = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                env=effective_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            duration = time.monotonic() - start
            last_result = CommandResult(
                args=argv,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=duration,
                timed_out=False,
                attempts=attempts,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start
            last_result = CommandResult(
                args=argv,
                returncode=-1,
                stdout=(exc.stdout or b"").decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or ""),
                stderr=(exc.stderr or b"").decode("utf-8", "replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or ""),
                duration_seconds=duration,
                timed_out=True,
                attempts=attempts,
            )
        except FileNotFoundError as exc:
            raise CommandError(
                f"Executable not found: {argv[0]!r}. Ensure it is installed and on PATH."
            ) from exc

        if last_result.ok:
            return last_result
        if attempts <= retries:
            time.sleep(retry_delay)

    assert last_result is not None  # loop always runs at least once
    return last_result


__all__ = ["redact", "CommandError", "CommandResult", "run_command"]
