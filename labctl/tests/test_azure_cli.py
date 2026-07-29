from __future__ import annotations

from pathlib import Path

import pytest

import labctl.azure_cli as azure_cli
from labctl.azure_cli import (
    account_show,
    provider_show,
    resource_type_locations,
    rest_get,
    role_assignments,
    signed_in_object_id,
)

ACCOUNT_JSON = """
{
  "id": "00000000-0000-0000-0000-000000000000",
  "name": "tokubica",
  "tenantId": "11111111-1111-1111-1111-111111111111",
  "user": {"name": "operator@example.com", "type": "user"}
}
"""


def test_run_az_uses_bundled_python_for_windows_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    cli_root = tmp_path / "CLI2"
    launcher = cli_root / "wbin" / "az.cmd"
    python = cli_root / "python.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off\n", encoding="ascii")
    python.write_bytes(b"")
    captured: list[str] = []

    monkeypatch.setattr(azure_cli.shutil, "which", lambda _name: str(launcher))

    def fake_run(args, **_kwargs):
        captured.extend(args)
        return result_factory(stdout="{}", returncode=0)

    monkeypatch.setattr(azure_cli, "run_command", fake_run)

    result = azure_cli.run_az(["account", "show"], retries=0)

    assert result.ok
    assert captured == [str(python), "-IBm", "azure.cli", "account", "show"]


def test_account_show_parses_expected_fields(result_factory) -> None:
    result = result_factory(stdout=ACCOUNT_JSON, returncode=0)

    account, raw = account_show(runner=lambda args, **kwargs: result)

    assert account is not None
    assert account.subscription_id == "00000000-0000-0000-0000-000000000000"
    assert account.subscription_name == "tokubica"
    assert account.user_name == "operator@example.com"
    assert raw is result


def test_account_show_returns_none_when_not_logged_in(result_factory) -> None:
    result = result_factory(stdout="", stderr="ERROR: Please run 'az login'", returncode=1)

    account, _raw = account_show(runner=lambda args, **kwargs: result)

    assert account is None


def test_account_show_returns_none_on_malformed_json(result_factory) -> None:
    result = result_factory(stdout="not json", returncode=0)

    account, _raw = account_show(runner=lambda args, **kwargs: result)

    assert account is None


def test_signed_in_object_id_parses_tsv(result_factory) -> None:
    result = result_factory(stdout="11111111-2222-3333-4444-555555555555\n", returncode=0)

    object_id, _raw = signed_in_object_id(runner=lambda args, **kwargs: result)

    assert object_id == "11111111-2222-3333-4444-555555555555"


def test_signed_in_object_id_none_when_command_fails(result_factory) -> None:
    result = result_factory(stdout="", returncode=1)

    object_id, _raw = signed_in_object_id(runner=lambda args, **kwargs: result)

    assert object_id is None


def test_role_assignments_parses_list(result_factory) -> None:
    result = result_factory(stdout='["Owner", "Reader"]', returncode=0)

    roles, _raw = role_assignments(
        "11111111-2222-3333-4444-555555555555",
        "/subscriptions/abc",
        runner=lambda args, **kwargs: result,
    )

    assert roles == ["Owner", "Reader"]


def test_provider_show_parses_registration_state(result_factory) -> None:
    result = result_factory(
        stdout='{"namespace": "Microsoft.App", "registrationState": "Registered"}'
    )

    data, _raw = provider_show("Microsoft.App", runner=lambda args, **kwargs: result)

    assert data is not None
    assert data["registrationState"] == "Registered"


def test_resource_type_locations_finds_matching_type(result_factory) -> None:
    result = result_factory(
        stdout="""
        {
          "resourceTypes": [
            {"resourceType": "agents", "locations": ["Sweden Central", "East US"]},
            {"resourceType": "containerApps", "locations": ["West Europe"]}
          ]
        }
        """
    )

    locations, _raw = resource_type_locations(
        "Microsoft.App", "agents", runner=lambda args, **kwargs: result
    )

    assert locations == ["Sweden Central", "East US"]


def test_resource_type_locations_missing_type_returns_none(result_factory) -> None:
    result = result_factory(stdout='{"resourceTypes": []}')

    locations, _raw = resource_type_locations(
        "Microsoft.App", "agents", runner=lambda args, **kwargs: result
    )

    assert locations is None


def test_rest_get_parses_json_body(result_factory) -> None:
    result = result_factory(stdout='{"value": [{"name": "gpt-x"}]}')

    data, _raw = rest_get(
        "/subscriptions/x/providers/Microsoft.App", runner=lambda args, **kwargs: result
    )

    assert data == {"value": [{"name": "gpt-x"}]}


def test_rest_call_patch_passes_body_and_content_type_header(result_factory) -> None:
    captured: list[list[str]] = []

    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(stdout='{"properties": {}}')

    body = '{"properties": {"incidentManagementConfiguration": {"type": "AzMonitor"}}}'
    data, result = azure_cli.rest_call(
        "patch",
        "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/a",
        body=body,
        runner=runner,
    )

    assert result.ok
    assert data == {"properties": {}}
    args = captured[0]
    assert args[args.index("--method") + 1] == "patch"
    assert args[args.index("--body") + 1] == body
    header_index = args.index("--headers")
    assert args[header_index + 1] == "Content-Type=application/json"


def test_rest_call_get_omits_body_and_content_type(result_factory) -> None:
    captured: list[list[str]] = []

    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(stdout="{}")

    azure_cli.rest_call("get", "/subscriptions/x", runner=runner)

    assert "--body" not in captured[0]
    assert "--headers" not in captured[0]


def test_access_token_returns_none_on_failure(result_factory) -> None:
    token, result = azure_cli.access_token(
        "https://azuresre.dev",
        runner=lambda args, **_kw: result_factory(returncode=1, stderr="not logged in"),
    )

    assert token is None
    assert not result.ok


def test_access_token_strips_and_returns_the_token(result_factory) -> None:
    captured: list[list[str]] = []

    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(stdout="eyJ.fake.token\n")

    token, result = azure_cli.access_token("https://azuresre.dev", runner=runner)

    assert result.ok
    assert token == "eyJ.fake.token"
    args = captured[0]
    assert args[args.index("--resource") + 1] == "https://azuresre.dev"


# --------------------------------------------------------------------------
# B2: subscription pinning
# --------------------------------------------------------------------------


def _capture_run_command(monkeypatch: pytest.MonkeyPatch, result_factory) -> list[list[str]]:
    captured: list[list[str]] = []

    def fake_run_command(args, **_kw):
        captured.append(list(args))
        return result_factory()

    monkeypatch.setattr(azure_cli, "run_command", fake_run_command)
    return captured


def test_run_az_injects_bound_subscription(monkeypatch: pytest.MonkeyPatch, result_factory) -> None:
    captured = _capture_run_command(monkeypatch, result_factory)

    azure_cli.bind_subscription("sub-pinned")
    azure_cli.run_az(["group", "show", "--name", "rg"], retries=0)

    args = captured[0]
    assert args[-2:] == ["--subscription", "sub-pinned"]


def test_run_az_does_not_inject_subscription_for_rest_ad_or_version(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    captured = _capture_run_command(monkeypatch, result_factory)

    azure_cli.bind_subscription("sub-pinned")
    azure_cli.run_az(["rest", "--method", "get", "--url", "/x"], retries=0)
    azure_cli.run_az(["ad", "signed-in-user", "show"], retries=0)
    azure_cli.run_az(["version"], retries=0)

    assert all("--subscription" not in args for args in captured)


def test_run_az_does_not_double_inject_when_subscription_already_present(
    monkeypatch: pytest.MonkeyPatch, result_factory
) -> None:
    captured = _capture_run_command(monkeypatch, result_factory)

    azure_cli.bind_subscription("sub-pinned")
    azure_cli.run_az(["group", "show", "--name", "rg", "--subscription", "explicit"], retries=0)

    assert captured[0].count("--subscription") == 1
    assert captured[0][captured[0].index("--subscription") + 1] == "explicit"


def test_ensure_subscription_context_fatal_on_auth_failure(result_factory) -> None:
    from conftest import make_config

    config = make_config(Path("."))
    result = result_factory(returncode=1, stderr="Please run 'az login'")

    account, message = azure_cli.ensure_subscription_context(
        config, az_runner=lambda args, **_kw: result
    )

    assert account is None
    assert message is not None
    assert "authentication or network" in message


def test_ensure_subscription_context_fatal_on_subscription_mismatch(result_factory) -> None:
    from conftest import make_config

    config = make_config(Path("."))  # subscription_id="sub-1" (see conftest.make_config)
    result = result_factory(
        stdout='{"id": "different-sub", "name": "n", "tenantId": "tenant-1", '
        '"user": {"name": "u", "type": "user"}}'
    )

    account, message = azure_cli.ensure_subscription_context(
        config, az_runner=lambda args, **_kw: result
    )

    assert account is None
    assert message is not None
    assert "different-sub" in message


def test_ensure_subscription_context_pins_subscription_on_success(result_factory) -> None:
    from conftest import make_config

    config = make_config(Path("."))
    result = result_factory(
        stdout='{"id": "sub-1", "name": "n", "tenantId": "tenant-1", '
        '"user": {"name": "u", "type": "user"}}'
    )

    account, message = azure_cli.ensure_subscription_context(
        config, az_runner=lambda args, **_kw: result
    )

    assert message is None
    assert account is not None
    assert azure_cli.bound_subscription() == "sub-1"


# --------------------------------------------------------------------------
# B3: not-found classification and resource enumeration
# --------------------------------------------------------------------------


def test_is_not_found_true_for_resource_group_not_found(result_factory) -> None:
    result = result_factory(
        returncode=1, stderr="(ResourceGroupNotFound) Resource group 'rg' could not be found."
    )

    assert azure_cli.is_not_found(result)


def test_is_not_found_false_for_auth_failure(result_factory) -> None:
    result = result_factory(returncode=1, stderr="Please run 'az login' to setup account.")

    assert not azure_cli.is_not_found(result)


def test_resource_list_parses_id_type_and_tags(result_factory) -> None:
    result = result_factory(
        stdout=(
            '[{"id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/a", '
            '"type": "Microsoft.App/agents", "tags": {"owner": "me"}}]'
        )
    )

    resources, _raw = azure_cli.resource_list("rg", runner=lambda args, **_kw: result)

    assert resources is not None
    assert len(resources) == 1
    assert resources[0].type == "Microsoft.App/agents"
    assert resources[0].tags == {"owner": "me"}
