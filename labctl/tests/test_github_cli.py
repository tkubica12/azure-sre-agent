from __future__ import annotations

from labctl.github_cli import auth_status, auth_token

SAMPLE_OUTPUT = """github.com
  \u2713 Logged in to github.com account tkubica12 (GH_TOKEN)
  - Active account: true
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'repo', 'user'
  ! Missing required token scopes: 'read:org'
  - To request missing scopes, run: gh auth refresh -h github.com

  \u2713 Logged in to github.com account tkubica12 (keyring)
  - Active account: false
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'
"""

NOT_LOGGED_IN_OUTPUT = "You are not logged into any GitHub hosts."


def test_auth_status_parses_multiple_accounts(result_factory) -> None:
    result = result_factory(stdout=SAMPLE_OUTPUT, returncode=0)

    status, _raw = auth_status(runner=lambda args, **kwargs: result)

    assert status.logged_in is True
    assert len(status.accounts) == 2

    active = status.active_account()
    assert active is not None
    assert active.account == "tkubica12"
    assert active.active is True
    assert set(active.scopes) == {"gist", "repo", "user"}
    assert active.missing_scopes == ("read:org",)

    inactive = status.accounts[1]
    assert inactive.active is False
    assert "workflow" in inactive.scopes


def test_auth_status_reports_logged_out(result_factory) -> None:
    result = result_factory(stdout="", stderr=NOT_LOGGED_IN_OUTPUT, returncode=1)

    status, raw = auth_status(runner=lambda args, **kwargs: result)

    assert status.logged_in is False
    assert status.accounts == ()
    assert raw is result


def test_auth_status_never_exposes_a_raw_token(result_factory) -> None:
    result = result_factory(stdout=SAMPLE_OUTPUT, returncode=0)

    status, _raw = auth_status(runner=lambda args, **kwargs: result)

    for account in status.accounts:
        assert not any(scope.startswith("gho_") for scope in account.scopes)


def test_auth_token_returns_the_stripped_token(result_factory) -> None:
    captured: list[list[str]] = []

    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(stdout="gho_faketoken1234567890\n", returncode=0)

    token, result = auth_token(runner=runner)

    assert result.ok
    assert token == "gho_faketoken1234567890"
    args = captured[0]
    assert args == ["auth", "token", "--hostname", "github.com"]


def test_auth_token_returns_none_when_not_logged_in(result_factory) -> None:
    token, result = auth_token(
        runner=lambda args, **_kw: result_factory(returncode=1, stderr="not logged in")
    )

    assert token is None
    assert not result.ok
