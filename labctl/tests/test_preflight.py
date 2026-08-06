from __future__ import annotations

from pathlib import Path

import pytest

from labctl.azure_cli import Account
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
from labctl.preflight import (
    Status,
    check_agent_model_availability,
    check_agent_region_support,
    check_azure_login,
    check_azure_permissions,
    check_github_auth,
    check_local_config,
    check_local_state_paths,
    check_network_dns,
    check_provider_registration,
    check_provider_registrations,
    check_tool_versions,
    summarize,
)


def make_config(tmp_path: Path, **overrides: object) -> Config:
    defaults = dict(
        repo_root=tmp_path,
        source_path=tmp_path / "config.local.toml",
        azure=AzureConfig(region="swedencentral"),
        resource_groups=ResourceGroupsConfig(agent="rg-agent", workload="rg-workload"),
        tags=TagsConfig(
            repository="azure-sre-agent", environment="demo", owner="me", deployment_id="local"
        ),
        github=GithubConfig(repository="tkubica12/azure-sre-agent"),
        agent=AgentConfig(name="sre-agent-demo", monthly_aau_allocation=10000),
        workload=WorkloadConfig(),
        paths=PathsConfig(terraform_state_dir=".state", evidence_dir=".evidence"),
    )
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


ACCOUNT = Account(
    subscription_id="00000000-0000-0000-0000-000000000000",
    subscription_name="tokubica",
    tenant_id="11111111-1111-1111-1111-111111111111",
    user_name="operator@example.com",
    user_type="user",
)


def fake_runner(mapping: dict[tuple[str, ...], object], result_factory):
    """Return a runner callable that dispatches on the first two argv tokens."""

    def runner(args, **kwargs):
        key = tuple(args[:2])
        value = mapping.get(key)
        if value is None:
            return result_factory(returncode=1, stderr=f"no fake configured for {key}")
        if isinstance(value, Exception):
            raise value
        return value

    return runner


# --------------------------------------------------------------------------
# Tool versions
# --------------------------------------------------------------------------


def test_check_tool_versions_all_pass(result_factory) -> None:
    az_result = result_factory(stdout='{"azure-cli": "2.80.0"}')
    gh_result = result_factory(stdout="gh version 2.96.0 (2026-07-02)")
    tf_result = result_factory(stdout='{"terraform_version": "1.10.1"}')

    results = check_tool_versions(
        which=lambda name: f"/usr/bin/{name}",
        az_runner=lambda args, **kwargs: az_result,
        gh_runner=lambda args, **kwargs: gh_result,
        tf_runner=lambda args, **kwargs: tf_result,
    )

    by_name = {r.name: r for r in results}
    assert by_name["tool-python"].status == Status.PASS
    assert by_name["tool-az"].status == Status.PASS
    assert by_name["tool-gh"].status == Status.PASS
    assert by_name["tool-terraform"].status == Status.PASS


def test_check_tool_versions_missing_executable(result_factory) -> None:
    results = check_tool_versions(
        which=lambda name: None,
        az_runner=lambda args, **kwargs: result_factory(),
        gh_runner=lambda args, **kwargs: result_factory(),
        tf_runner=lambda args, **kwargs: result_factory(),
    )

    by_name = {r.name: r for r in results}
    assert by_name["tool-az"].status == Status.FAIL
    assert "PATH" in by_name["tool-az"].detail


def test_check_tool_versions_below_minimum_fails(result_factory) -> None:
    az_result = result_factory(stdout='{"azure-cli": "2.10.0"}')

    results = check_tool_versions(
        which=lambda name: "/usr/bin/az",
        az_runner=lambda args, **kwargs: az_result,
        gh_runner=lambda args, **kwargs: result_factory(stdout="gh version 2.96.0 (x)"),
        tf_runner=lambda args, **kwargs: result_factory(stdout='{"terraform_version": "1.10.1"}'),
    )

    by_name = {r.name: r for r in results}
    assert by_name["tool-az"].status == Status.FAIL
    assert "older than" in by_name["tool-az"].detail


# --------------------------------------------------------------------------
# Azure login / permissions / provider / region / models
# --------------------------------------------------------------------------


def test_check_azure_login_pass(tmp_path: Path, result_factory) -> None:
    config = make_config(tmp_path)
    account_result = result_factory(
        stdout='{"id": "00000000-0000-0000-0000-000000000000", "name": "tokubica", '
        '"tenantId": "t", "user": {"name": "u", "type": "user"}}'
    )

    result = check_azure_login(config, az_runner=lambda args, **kwargs: account_result)

    assert result.status == Status.PASS


def test_check_azure_login_fail_when_not_logged_in(tmp_path: Path, result_factory) -> None:
    config = make_config(tmp_path)
    account_result = result_factory(returncode=1, stderr="Please run az login")

    result = check_azure_login(config, az_runner=lambda args, **kwargs: account_result)

    assert result.status == Status.FAIL


def test_check_azure_login_fails_on_subscription_mismatch(tmp_path: Path, result_factory) -> None:
    config = make_config(
        tmp_path, azure=AzureConfig(region="swedencentral", subscription_id="other-sub")
    )
    account_result = result_factory(
        stdout='{"id": "00000000-0000-0000-0000-000000000000", "name": "tokubica", '
        '"tenantId": "t", "user": {"name": "u", "type": "user"}}'
    )

    result = check_azure_login(config, az_runner=lambda args, **kwargs: account_result)

    assert result.status == Status.FAIL


@pytest.mark.parametrize(
    ("roles_json", "expected_status"),
    [
        ('["Owner"]', Status.PASS),
        ('["Contributor", "User Access Administrator"]', Status.PASS),
        ('["Contributor"]', Status.WARN),
        ('["Reader"]', Status.FAIL),
        ("[]", Status.FAIL),
    ],
)
def test_check_azure_permissions_role_combinations(
    tmp_path: Path, result_factory, roles_json: str, expected_status: Status
) -> None:
    config = make_config(tmp_path)
    mapping = {
        ("account", "show"): result_factory(
            stdout='{"id":"sub-1","name":"n","tenantId":"t","user":{"name":"u","type":"user"}}'
        ),
        ("ad", "signed-in-user"): result_factory(stdout="obj-1\n"),
        ("role", "assignment"): result_factory(stdout=roles_json),
    }

    result = check_azure_permissions(config, az_runner=fake_runner(mapping, result_factory))

    assert result.status == expected_status


def test_check_azure_permissions_warns_when_object_id_unavailable(
    tmp_path: Path, result_factory
) -> None:
    config = make_config(tmp_path)
    mapping = {
        ("account", "show"): result_factory(
            stdout='{"id":"sub-1","name":"n","tenantId":"t","user":{"name":"u","type":"servicePrincipal"}}'
        ),
        ("ad", "signed-in-user"): result_factory(returncode=1, stderr="not a user principal"),
    }

    result = check_azure_permissions(config, az_runner=fake_runner(mapping, result_factory))

    assert result.status == Status.WARN


@pytest.mark.parametrize(
    "namespace",
    ["Microsoft.App", "Microsoft.ContainerRegistry", "Microsoft.OperationalInsights"],
)
@pytest.mark.parametrize(
    ("state", "expected_status"),
    [("Registered", Status.PASS), ("Registering", Status.WARN), ("NotRegistered", Status.FAIL)],
)
def test_check_provider_registration_states(
    result_factory, namespace: str, state: str, expected_status: Status
) -> None:
    result = result_factory(stdout=f'{{"registrationState": "{state}"}}')

    check_result = check_provider_registration(namespace, az_runner=lambda args, **kwargs: result)

    assert check_result.status == expected_status
    assert check_result.name == "provider-" + namespace.lower().replace(".", "-")


def test_check_provider_registration_fails_on_query_error(result_factory) -> None:
    result = result_factory(returncode=1, stderr="boom")

    check_result = check_provider_registration(
        "Microsoft.App", az_runner=lambda args, **kwargs: result
    )

    assert check_result.status == Status.FAIL
    assert check_result.name == "provider-microsoft-app"


def test_check_provider_registrations_covers_all_required_providers(result_factory) -> None:
    def fake_runner(args, **kwargs):
        namespace = args[args.index("--namespace") + 1] if "--namespace" in args else None
        state = {
            "Microsoft.App": "Registered",
            "Microsoft.ContainerRegistry": "Registering",
            "Microsoft.OperationalInsights": "NotRegistered",
        }.get(namespace, "Unknown")
        return result_factory(stdout=f'{{"registrationState": "{state}"}}')

    results = check_provider_registrations(az_runner=fake_runner)

    by_name = {r.name: r.status for r in results}
    assert by_name == {
        "provider-microsoft-app": Status.PASS,
        "provider-microsoft-containerregistry": Status.WARN,
        "provider-microsoft-operationalinsights": Status.FAIL,
    }


def test_check_agent_region_support_pass(tmp_path: Path, result_factory) -> None:
    config = make_config(tmp_path)
    result = result_factory(
        stdout='{"resourceTypes": [{"resourceType": "agents", "locations": ["Sweden Central"]}]}'
    )

    check_result = check_agent_region_support(config, az_runner=lambda args, **kwargs: result)

    assert check_result.status == Status.PASS


def test_check_agent_region_support_fail_when_unsupported(tmp_path: Path, result_factory) -> None:
    config = make_config(tmp_path)
    result = result_factory(
        stdout='{"resourceTypes": [{"resourceType": "agents", "locations": ["East US"]}]}'
    )

    check_result = check_agent_region_support(config, az_runner=lambda args, **kwargs: result)

    assert check_result.status == Status.FAIL


def test_check_agent_model_availability_pass(tmp_path: Path, result_factory) -> None:
    config = make_config(tmp_path)
    mapping = {
        ("account", "show"): result_factory(
            stdout='{"id":"sub-1","name":"n","tenantId":"t","user":{"name":"u","type":"user"}}'
        ),
        ("rest", "--method"): result_factory(stdout='{"value": [{"name": "gpt-x"}]}'),
    }

    check_result = check_agent_model_availability(
        config, az_runner=fake_runner(mapping, result_factory)
    )

    assert check_result.status == Status.PASS
    assert "gpt-x" in check_result.detail


def test_check_agent_model_availability_warns_when_api_call_fails(
    tmp_path: Path, result_factory
) -> None:
    config = make_config(tmp_path)
    mapping = {
        ("account", "show"): result_factory(
            stdout='{"id":"sub-1","name":"n","tenantId":"t","user":{"name":"u","type":"user"}}'
        ),
        ("rest", "--method"): result_factory(returncode=1, stderr="not found"),
    }

    check_result = check_agent_model_availability(
        config, az_runner=fake_runner(mapping, result_factory)
    )

    assert check_result.status == Status.WARN


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------


def test_check_github_auth_pass(result_factory) -> None:
    output = (
        "  \u2713 Logged in to github.com account tkubica12 (GH_TOKEN)\n"
        "  - Active account: true\n"
        "  - Token scopes: 'repo', 'gist'\n"
    )
    result = result_factory(stdout=output, returncode=0)

    check_result = check_github_auth(gh_runner=lambda args, **kwargs: result)

    assert check_result.status == Status.PASS
    assert "gho_" not in check_result.detail


def test_check_github_auth_fails_when_repo_scope_missing(result_factory) -> None:
    output = (
        "  \u2713 Logged in to github.com account tkubica12 (GH_TOKEN)\n"
        "  - Active account: true\n"
        "  - Token scopes: 'gist'\n"
    )
    result = result_factory(stdout=output, returncode=0)

    check_result = check_github_auth(gh_runner=lambda args, **kwargs: result)

    assert check_result.status == Status.FAIL
    assert "repo" in check_result.detail


def test_check_github_auth_fails_when_logged_out(result_factory) -> None:
    result = result_factory(stdout="", stderr="not logged in", returncode=1)

    check_result = check_github_auth(gh_runner=lambda args, **kwargs: result)

    assert check_result.status == Status.FAIL


# --------------------------------------------------------------------------
# Local config / state paths / network
# --------------------------------------------------------------------------


def test_check_local_config_pass(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    result = check_local_config(config)

    assert result.status == Status.PASS


def test_check_local_state_paths_creates_writable_dirs(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    results = check_local_state_paths(config)

    assert all(r.status == Status.PASS for r in results)
    assert (tmp_path / ".state").is_dir()
    assert (tmp_path / ".evidence").is_dir()


def test_check_network_dns_pass_and_warn(tmp_path: Path) -> None:
    import socket

    config = make_config(tmp_path)

    def gaierror_resolver(host: str, port: int):
        if host == "sre.azure.com":
            return [("resolved",)]
        raise socket.gaierror("simulated resolution failure")

    results = check_network_dns(config, resolver=gaierror_resolver)
    by_name = {r.name: r for r in results}

    assert by_name["network-dns-portal"].status == Status.PASS
    assert by_name["network-dns-data-plane"].status == Status.WARN


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def test_summarize_reports_nonzero_exit_on_failure() -> None:
    from labctl.preflight import CheckResult

    results = [
        CheckResult("a", Status.PASS, "ok"),
        CheckResult("b", Status.WARN, "meh"),
        CheckResult("c", Status.FAIL, "bad"),
    ]

    table, exit_code = summarize(results)

    assert exit_code == 1
    assert "1 passed, 1 warned, 1 failed" in table


def test_summarize_reports_zero_exit_without_failures() -> None:
    from labctl.preflight import CheckResult

    results = [CheckResult("a", Status.PASS, "ok"), CheckResult("b", Status.WARN, "meh")]

    _table, exit_code = summarize(results)

    assert exit_code == 0


def test_run_preflight_returns_a_result_for_every_check_area(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke test of the orchestration function: every individual check is
    stubbed so this test only proves run_preflight wires all checks together
    and returns their combined results, without re-testing each check's
    internal logic (covered by the dedicated tests above).
    """

    import labctl.preflight as preflight_module

    config = make_config(tmp_path)

    def stub(name: str):
        return preflight_module.CheckResult(name, Status.PASS, "stubbed")

    monkeypatch.setattr(
        preflight_module, "check_tool_versions", lambda **kwargs: [stub("tool-stub")]
    )
    monkeypatch.setattr(
        preflight_module, "check_azure_login", lambda cfg, **kwargs: stub("azure-login")
    )
    monkeypatch.setattr(
        preflight_module, "check_azure_permissions", lambda cfg, **kwargs: stub("azure-permissions")
    )
    monkeypatch.setattr(
        preflight_module,
        "check_provider_registrations",
        lambda **kwargs: [
            stub("provider-microsoft-app"),
            stub("provider-microsoft-containerregistry"),
            stub("provider-microsoft-operationalinsights"),
        ],
    )
    monkeypatch.setattr(
        preflight_module,
        "check_agent_region_support",
        lambda cfg, **kwargs: stub("agent-region-support"),
    )
    monkeypatch.setattr(
        preflight_module,
        "check_agent_model_availability",
        lambda cfg, **kwargs: stub("agent-model-availability"),
    )
    monkeypatch.setattr(preflight_module, "check_github_auth", lambda **kwargs: stub("github-auth"))
    monkeypatch.setattr(preflight_module, "check_local_config", lambda cfg: stub("local-config"))
    monkeypatch.setattr(
        preflight_module,
        "check_local_state_paths",
        lambda cfg: [stub("local-state-path"), stub("local-evidence-path")],
    )
    monkeypatch.setattr(
        preflight_module,
        "check_network_dns",
        lambda cfg, **kwargs: [stub("network-dns-portal"), stub("network-dns-data-plane")],
    )

    results = preflight_module.run_preflight(config)

    names = {r.name for r in results}
    assert names == {
        "tool-stub",
        "azure-login",
        "azure-permissions",
        "provider-microsoft-app",
        "provider-microsoft-containerregistry",
        "provider-microsoft-operationalinsights",
        "agent-region-support",
        "agent-model-availability",
        "github-auth",
        "local-config",
        "local-state-path",
        "local-evidence-path",
        "network-dns-portal",
        "network-dns-data-plane",
    }
    assert all(r.status == Status.PASS for r in results)
