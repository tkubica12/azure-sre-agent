from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from labctl.procutil import CommandError, redact, run_command


@pytest.mark.parametrize(
    "raw",
    [
        "Authorization: Bearer abcDEF123.456-789_ABC",
        "token: gho_1234567890ABCDEFGHIJ1234567890abcd",
        "using github_pat_11ABCDEFGHIJKLMNOPQRSTUVWX_1234567890abcdefghijklmnop",
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=abcd1234==;EndpointSuffix=core.windows.net",
        "password=hunter2",
        "client_secret: super-secret-value",
        "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://x.in.applicationinsights.azure.com/",
    ],
)
def test_redact_masks_known_secret_shapes(raw: str) -> None:
    redacted = redact(raw)
    assert "***REDACTED***" in redacted
    assert "hunter2" not in redacted
    assert "super-secret-value" not in redacted
    assert "00000000-0000-0000-0000-000000000000" not in redacted


def test_redact_masks_application_insights_connection_string_env_var() -> None:
    """M5: an APPLICATIONINSIGHTS_CONNECTION_STRING diagnostic (e.g. from a
    `containerapp update --replace-env-vars` failure) must never leak the
    instrumentation key or ingestion endpoint."""

    raw = (
        "APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=abcdef12-3456-7890-abcd-"
        "ef1234567890;IngestionEndpoint=https://swedencentral-1.in.applicationinsights.azure.com/"
    )

    redacted = redact(raw)

    assert "abcdef12-3456-7890-abcd-ef1234567890" not in redacted
    assert "***REDACTED***" in redacted


def test_redact_leaves_ordinary_text_untouched() -> None:
    text = "az account show returned subscription 00000000-0000-0000-0000-000000000000"
    assert redact(text) == text


def test_run_command_captures_stdout_and_exit_code() -> None:
    result = run_command([sys.executable, "-c", "print('hello')"])

    assert result.ok
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"
    assert result.attempts == 1


def test_run_command_nonzero_exit_does_not_raise() -> None:
    result = run_command([sys.executable, "-c", "import sys; sys.exit(3)"])

    assert not result.ok
    assert result.returncode == 3
    assert result.timed_out is False


def test_run_command_timeout_is_reported_not_raised() -> None:
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=0.2,
    )

    assert result.timed_out is True
    assert not result.ok


def test_run_command_missing_executable_raises_command_error() -> None:
    with pytest.raises(CommandError, match="not found"):
        run_command(["this-executable-does-not-exist-12345"])


def test_run_command_rejects_windows_batch_launcher(tmp_path: Path) -> None:
    launcher = tmp_path / "unsafe.cmd"
    launcher.write_text("@echo off\n", encoding="ascii")

    with pytest.raises(CommandError, match="Refusing to execute Windows batch launcher"):
        run_command([str(launcher), 'value" & echo injected'])


def test_run_command_rejects_empty_args() -> None:
    with pytest.raises(CommandError):
        run_command([])


def test_run_command_retries_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}
    real_run = subprocess.run

    def flaky_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        if calls["count"] < 2:
            return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="boom")
        return real_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", flaky_run)

    result = run_command([sys.executable, "-c", "print('ok')"], retries=2, retry_delay=0)

    assert result.ok
    assert calls["count"] == 2


def test_command_result_diagnostic_and_redaction_helpers() -> None:
    result = run_command([sys.executable, "-c", "print('token=abc123secretvalue')"])

    assert "abc123secretvalue" not in result.redacted_stdout()
    assert "abc123secretvalue" in result.stdout
    diagnostic = result.diagnostic()
    assert "exit code 0" in diagnostic


def test_run_command_accepts_cwd(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=tmp_path,
    )

    assert result.ok
    assert Path(result.stdout.strip()) == tmp_path.resolve()
