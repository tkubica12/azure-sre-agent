from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from labctl.cli import cli
from labctl.config import CONFIG_EXAMPLE_FILENAME


def _init_repo(tmp_path: Path) -> None:
    (tmp_path / CONFIG_EXAMPLE_FILENAME).write_text("# example\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# agents\n", encoding="utf-8")


def test_implemented_commands_require_config_before_touching_azure(
    monkeypatch, tmp_path: Path
) -> None:
    """Every lifecycle command must fail fast on missing local configuration
    rather than attempting any Azure or Terraform call.
    """

    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    for args in (
        ["deploy"],
        ["provision"],
        ["verify"],
        ["status"],
        ["destroy"],
        ["demo", "list"],
        ["demo", "prepare", "bad-deployment"],
        ["demo", "trigger", "bad-deployment"],
        ["demo", "verify", "bad-deployment"],
        ["demo", "reset", "bad-deployment"],
        ["evidence", "collect"],
    ):
        result = runner.invoke(cli, args)
        assert result.exit_code != 0
        assert "config.local.toml" in result.output


def test_demo_subcommands_require_a_scenario_argument(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    for sub in ("prepare", "trigger", "verify", "reset"):
        result = runner.invoke(cli, ["demo", sub])
        assert result.exit_code != 0
        assert "Missing argument" in result.output


def test_preflight_reports_actionable_error_without_local_config(
    monkeypatch, tmp_path: Path
) -> None:
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["preflight"])

    assert result.exit_code != 0
    assert "config.local.toml" in result.output


def test_cli_help_lists_full_command_surface() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in (
        "preflight",
        "deploy",
        "provision",
        "verify",
        "status",
        "demo",
        "evidence",
        "destroy",
    ):
        assert command in result.output


def test_use_utf8_console_streams_is_safe_to_call_twice() -> None:
    """Guards against the live Windows crash where non-ASCII Terraform
    output (e.g. the box-drawing U+2500 separator) raised UnicodeEncodeError
    on the default console code page (see PLAN.md Milestone 3)."""

    from labctl.cli import _use_utf8_console_streams

    _use_utf8_console_streams()
    _use_utf8_console_streams()
