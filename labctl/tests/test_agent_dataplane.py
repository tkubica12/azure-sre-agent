from __future__ import annotations

import json

import labctl.agent_dataplane as agent_dataplane
from labctl.dataplane_http import DataPlaneResponse

ENDPOINT = "https://sre-agent-demo--<hash1>.<hash2>.swedencentral.azuresre.ai"
TOKEN = "fake-token"  # noqa: S105 - test fixture, not a real credential


def _fake_request(status: int, body: str, *, error: str = ""):
    captured: dict[str, object] = {}

    def fake(url, *, method, headers=None, data=None, timeout=30.0, **_kw):
        captured.update(url=url, method=method, headers=headers, data=data, timeout=timeout)
        return DataPlaneResponse(ok=not error, status_code=status, body=body, error=error)

    return fake, captured


def test_put_extended_item_sends_the_expected_url_and_body(monkeypatch) -> None:
    fake, captured = _fake_request(202, "{}")
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    result = agent_dataplane.put_extended_item(
        ENDPOINT,
        TOKEN,
        kind="skills",
        name="triage-checkout-failures",
        properties={"description": "x"},
    )

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v2/extendedAgent/skills/triage-checkout-failures"
    assert captured["method"] == "PUT"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    body = json.loads(captured["data"])
    assert body["type"] == "Skill"
    assert body["properties"] == {"description": "x"}


def test_put_extended_item_uses_the_default_item_type_per_kind(monkeypatch) -> None:
    fake, captured = _fake_request(202, "{}")
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    agent_dataplane.put_extended_item(ENDPOINT, TOKEN, kind="hooks", name="deny", properties={})

    body = json.loads(captured["data"])
    assert body["type"] == "GlobalHook"


def test_put_extended_item_reports_failure_with_truncated_body(monkeypatch) -> None:
    fake, _captured = _fake_request(400, json.dumps({"error": {"message": "bad"}}))
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    result = agent_dataplane.put_extended_item(
        ENDPOINT, TOKEN, kind="skills", name="x", properties={}
    )

    assert not result.ok
    assert result.status_code == 400
    assert "bad" in result.detail


def test_get_extended_items_parses_the_value_wrapper(monkeypatch) -> None:
    body = '{"value": [{"name": "a"}, {"name": "b"}], "nextLink": null}'
    fake, _captured = _fake_request(200, body)
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.get_extended_items(ENDPOINT, TOKEN, kind="agents")

    assert result.ok
    assert items == [{"name": "a"}, {"name": "b"}]


def test_get_scheduled_tasks_parses_a_bare_array(monkeypatch) -> None:
    fake, _captured = _fake_request(200, '[{"name": "daily-reliability-summary"}]')
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.get_scheduled_tasks(ENDPOINT, TOKEN)

    assert result.ok
    assert items == [{"name": "daily-reliability-summary"}]


def test_get_incident_filters_parses_a_bare_array(monkeypatch) -> None:
    fake, _captured = _fake_request(200, '[{"id": "checkout-5xx"}]')
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.get_incident_filters(ENDPOINT, TOKEN)

    assert result.ok
    assert items == [{"id": "checkout-5xx"}]


def test_upload_knowledge_file_sends_multipart_with_query_string(monkeypatch) -> None:
    fake, captured = _fake_request(200, '{"message": "ok"}')
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    result = agent_dataplane.upload_knowledge_file(
        ENDPOINT, TOKEN, filename="architecture.md", content=b"# Title"
    )

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v1/AgentMemory/upload?triggerIndexing=true"
    assert "multipart/form-data" in captured["headers"]["Content-Type"]
    assert b"# Title" in captured["data"]


def test_list_knowledge_files_parses_the_files_key(monkeypatch) -> None:
    fake, _captured = _fake_request(200, '{"files": [{"name": "a.md", "isIndexed": true}]}')
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.list_knowledge_files(ENDPOINT, TOKEN)

    assert result.ok
    assert items == [{"name": "a.md", "isIndexed": True}]


def test_put_github_domain_pat_sends_the_expected_body(monkeypatch) -> None:
    fake, captured = _fake_request(200, '{"message": "ok"}')
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    result = agent_dataplane.put_github_domain_pat(ENDPOINT, TOKEN, pat="gho_secret")  # noqa: S106

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v2/github/domains/github_com"
    body = json.loads(captured["data"])
    assert body == {"AuthType": "Pat", "Pat": "gho_secret"}


def test_get_github_domains_parses_the_values_key(monkeypatch) -> None:
    fake, _captured = _fake_request(200, '{"values": [{"name": "github.com", "authType": "Pat"}]}')
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.get_github_domains(ENDPOINT, TOKEN)

    assert result.ok
    assert items == [{"name": "github.com", "authType": "Pat"}]


def test_put_repo_succeeds_on_a_2xx_response(monkeypatch) -> None:
    fake, captured = _fake_request(202, "{}")
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    result = agent_dataplane.put_repo(
        ENDPOINT, TOKEN, name="azure-sre-agent", url="https://github.com/tkubica12/azure-sre-agent"
    )

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v2/repos/azure-sre-agent"


def test_put_repo_treats_405_as_success_when_readback_confirms_the_write(monkeypatch) -> None:
    def fake(url, *, method, headers=None, data=None, timeout=30.0, **_kw):
        if method == "PUT":
            return DataPlaneResponse(ok=True, status_code=405, body="")
        assert method == "GET"
        return DataPlaneResponse(
            ok=True,
            status_code=200,
            body=json.dumps(
                {
                    "value": [
                        {
                            "name": "azure-sre-agent",
                            "properties": {"url": "https://github.com/tkubica12/azure-sre-agent"},
                        }
                    ]
                }
            ),
        )

    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    result = agent_dataplane.put_repo(
        ENDPOINT, TOKEN, name="azure-sre-agent", url="https://github.com/tkubica12/azure-sre-agent"
    )

    assert result.ok
    assert result.status_code == 405
    assert "known quirk" in result.detail


def test_put_repo_fails_405_when_readback_does_not_confirm(monkeypatch) -> None:
    def fake(url, *, method, headers=None, data=None, timeout=30.0, **_kw):
        if method == "PUT":
            return DataPlaneResponse(ok=True, status_code=405, body="")
        return DataPlaneResponse(ok=True, status_code=200, body='{"value": []}')

    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    result = agent_dataplane.put_repo(
        ENDPOINT, TOKEN, name="azure-sre-agent", url="https://github.com/tkubica12/azure-sre-agent"
    )

    assert not result.ok
    assert result.status_code == 405


def test_get_repos_parses_the_value_wrapper(monkeypatch) -> None:
    fake, _captured = _fake_request(
        200, '{"value": [{"name": "azure-sre-agent", "properties": {"url": "x"}}]}'
    )
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.get_repos(ENDPOINT, TOKEN)

    assert result.ok
    assert items == [{"name": "azure-sre-agent", "properties": {"url": "x"}}]


def test_get_data_plane_token_uses_the_azuresre_dev_audience(result_factory) -> None:
    captured: list[list[str]] = []

    def runner(args, **_kwargs):
        captured.append(list(args))
        return result_factory(stdout="fake-jwt-token\n")

    token, result = agent_dataplane.get_data_plane_token(runner=runner)

    assert result.ok
    assert token == "fake-jwt-token"
    args = captured[0]
    assert args[args.index("--resource") + 1] == "https://azuresre.dev"


def test_list_threads_parses_the_value_wrapper(monkeypatch) -> None:
    body = json.dumps({"value": [{"id": "t1", "title": "checkout 5xx Sev2"}], "nextLink": None})
    fake, captured = _fake_request(200, body)
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.list_threads(ENDPOINT, TOKEN)

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v1/threads"
    assert items == [{"id": "t1", "title": "checkout 5xx Sev2"}]


def test_list_threads_reports_failure(monkeypatch) -> None:
    fake, _captured = _fake_request(500, "boom")
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.list_threads(ENDPOINT, TOKEN)

    assert items is None
    assert not result.ok


def test_get_thread_returns_a_single_object(monkeypatch) -> None:
    fake, captured = _fake_request(200, '{"id": "t1", "title": "x"}')
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    thread, result = agent_dataplane.get_thread(ENDPOINT, TOKEN, "t1")

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v1/threads/t1"
    assert thread == {"id": "t1", "title": "x"}


def test_get_thread_messages_parses_the_value_wrapper(monkeypatch) -> None:
    body = json.dumps({"value": [{"id": "m1", "text": "investigating"}]})
    fake, captured = _fake_request(200, body)
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.get_thread_messages(ENDPOINT, TOKEN, "t1")

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v1/threads/t1/messages"
    assert items == [{"id": "m1", "text": "investigating"}]


def test_list_pending_approvals_parses_a_bare_array(monkeypatch) -> None:
    fake, captured = _fake_request(200, '[{"id": "a1", "status": "Pending"}]')
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    items, result = agent_dataplane.list_pending_approvals(ENDPOINT, TOKEN, "t1")

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v1/approvals/t1"
    assert items == [{"id": "a1", "status": "Pending"}]


def test_decide_approval_sends_the_expected_url_and_body(monkeypatch) -> None:
    fake, captured = _fake_request(200, "{}")
    monkeypatch.setattr(agent_dataplane, "http_request", fake)

    result = agent_dataplane.decide_approval(
        ENDPOINT, TOKEN, "t1", "a1", decision="Approved", reason="rollback per runbook"
    )

    assert result.ok
    assert captured["url"] == f"{ENDPOINT}/api/v1/approvals/t1/a1/decision"
    assert captured["method"] == "POST"
    body = json.loads(captured["data"])
    assert body == {"decision": "Approved", "reason": "rollback per runbook"}
