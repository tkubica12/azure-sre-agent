"""Azure SRE Agent data-plane client: skills, subagents, hooks, common
prompts, scheduled tasks, incident filters, knowledge (AgentMemory), GitHub
domain authentication, and source repositories.

Distinct from :mod:`labctl.agent_azure` (ARM control-plane calls against
``Microsoft.App/agents`` and its connectors, using an ARM management-plane
token implicitly obtained by ``az rest``) because this module talks directly
to the agent's own HTTPS endpoint (``https://<agent>.<region>.azuresre.ai``)
using a Microsoft Entra access token scoped to the ``https://azuresre.dev``
audience (see SPEC.md sections 3 and 11).

Every route and payload shape here was verified two ways: (1) against the
official ``microsoft/sre-agent`` template's ``bicep/Apply-Extras.ps1`` and
``bin/verify-agent.sh``, and (2) live, directly against the deployed
``sre-agent-demo`` agent on 2026-07-29 (see PLAN.md Milestone 4 "API/schema
adaptations" for the two adaptations that live testing required).

Every write (``put_*``) is a PUT keyed by name, so re-running
``labctl provision`` is always safe: it overwrites the same named item
rather than creating a duplicate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from labctl import azure_cli
from labctl.azure_cli import AzRunner, run_az
from labctl.dataplane_http import build_multipart_body
from labctl.dataplane_http import request as http_request
from labctl.procutil import CommandResult

#: Token audience for the agent's own HTTPS data-plane API. Distinct from
#: the ARM management-plane audience used by :mod:`labctl.agent_azure` (see
#: SPEC.md sections 3 and 11).
DATA_PLANE_AUDIENCE = "https://azuresre.dev"

DEFAULT_TIMEOUT = 30.0
#: AgentMemory uploads and repo wiring can take a little longer than a
#: simple metadata PUT.
UPLOAD_TIMEOUT = 60.0

#: Item-type strings the data-plane API requires per kind, discovered live:
#: an empty/omitted `type` is rejected with `InvalidObjectType` for hooks and
#: common prompts (see PLAN.md Milestone 4 "API/schema adaptations"), and
#: matches the official template's `assemble-agent.sh` defaults
#: (`GlobalHook`, `CommonPrompt`).
ITEM_TYPES: dict[str, str] = {
    "skills": "Skill",
    "agents": "ExtendedAgent",
    "hooks": "GlobalHook",
    "commonprompts": "CommonPrompt",
    "scheduledtasks": "ScheduledTask",
    "incidentFilters": "IncidentFilter",
}


def get_data_plane_token(
    *, runner: AzRunner = run_az, timeout: float = azure_cli.DEFAULT_TIMEOUT
) -> tuple[str | None, CommandResult]:
    """Acquire a bearer token for the ``https://azuresre.dev`` audience via
    the operator's existing ``az login`` session. Never logs the token;
    callers must never print ``result.stdout`` directly on failure -- use
    ``result.diagnostic()`` instead (see AGENTS.md).
    """

    return azure_cli.access_token(DATA_PLANE_AUDIENCE, runner=runner, timeout=timeout)


def _auth_headers(token: str, *, content_type: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


@dataclass(frozen=True, slots=True)
class DataPlaneResult:
    """Outcome of one data-plane call. Always safe to print: never contains
    the bearer token, and truncates any response body kept for
    diagnostics."""

    ok: bool
    status_code: int
    label: str
    detail: str = ""

    def diagnostic(self) -> str:
        suffix = f" - {self.detail}" if self.detail else ""
        return f"{self.label}: HTTP {self.status_code}{suffix}"


def _truncate(body: str, limit: int = 500) -> str:
    return body if len(body) <= limit else body[:limit] + "...(truncated)"


def _to_result(
    label: str, response: Any, *, ok_statuses: tuple[int, ...] = (200, 201, 202)
) -> DataPlaneResult:
    if not response.ok:
        return DataPlaneResult(False, 0, label, f"request failed: {response.error}")
    if response.status_code not in ok_statuses:
        return DataPlaneResult(False, response.status_code, label, _truncate(response.body))
    return DataPlaneResult(True, response.status_code, label)


def put_extended_item(
    endpoint: str,
    token: str,
    *,
    kind: str,
    name: str,
    properties: dict[str, Any],
    item_type: str | None = None,
    tags: tuple[str, ...] = (),
    timeout: float = DEFAULT_TIMEOUT,
) -> DataPlaneResult:
    """PUT one ``/api/v2/extendedAgent/{kind}/{name}`` item: skills,
    subagents (``kind="agents"``), hooks, commonprompts, scheduledtasks, or
    incidentFilters. Mirrors the official template's
    ``DataPlane-PutExtended`` helper.
    """

    resolved_type = item_type or ITEM_TYPES.get(kind, "")
    url = f"{endpoint}/api/v2/extendedAgent/{kind}/{quote(name, safe='')}"
    body = json.dumps(
        {"name": name, "type": resolved_type, "tags": list(tags), "properties": properties}
    )
    response = http_request(
        url,
        method="PUT",
        headers=_auth_headers(token, content_type="application/json"),
        data=body.encode("utf-8"),
        timeout=timeout,
    )
    return _to_result(f"PUT {kind}/{name}", response)


def get_extended_items(
    endpoint: str, token: str, *, kind: str, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET the ``/api/v2/extendedAgent/{kind}`` collection (skills,
    subagents (``kind="agents"``), hooks, or commonprompts). Response shape
    is ``{"value": [...], "nextLink": null}`` (live-verified)."""

    url = f"{endpoint}/api/v2/extendedAgent/{kind}"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result(f"GET {kind}", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    value = data.get("value") if isinstance(data, dict) else None
    items = [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
    return items, result


def get_scheduled_tasks(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET ``/api/v1/scheduledtasks`` (top-level route, distinct from the
    ``/api/v2/extendedAgent/scheduledtasks`` PUT route; live-verified to
    return a bare JSON array, matching the official ``verify-agent.sh``)."""

    url = f"{endpoint}/api/v1/scheduledtasks"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result("GET scheduledtasks", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    items = [v for v in data if isinstance(v, dict)] if isinstance(data, list) else []
    return items, result


def get_incident_filters(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET ``/api/v1/incidentPlayground/filters`` (response plans; top-level
    route, distinct from the ``/api/v2/extendedAgent/incidentFilters`` PUT
    route; live-verified to return a bare JSON array)."""

    url = f"{endpoint}/api/v1/incidentPlayground/filters"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result("GET incidentPlayground/filters", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    items = [v for v in data if isinstance(v, dict)] if isinstance(data, list) else []
    return items, result


def list_threads(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET ``/api/v1/threads``: every conversation/incident thread the agent
    has (scheduled-task runs, ad hoc chats, and incidents routed in by a
    response plan alike). Each item's ``status.incidentStatus.status`` and
    ``createdTimestamp``/``title`` fields are what `labctl demo verify` and
    `labctl evidence collect` use to find the incident thread this
    scenario's alert produced (see the official
    ``microsoft/sre-agent`` template's ``labs/*/scripts/watch-agent.ps1`` and
    Microsoft's published API reference at
    https://learn.microsoft.com/azure/sre-agent/api-reference, both
    live-verified against this route/response shape).
    """

    url = f"{endpoint}/api/v1/threads"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result("GET threads", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    value = data.get("value") if isinstance(data, dict) else data
    items = [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
    return items, result


def get_thread(
    endpoint: str, token: str, thread_id: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[dict[str, Any] | None, DataPlaneResult]:
    """GET ``/api/v1/threads/{threadId}``: a single thread's current status."""

    url = f"{endpoint}/api/v1/threads/{quote(thread_id, safe='')}"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result(f"GET threads/{thread_id}", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    return (data if isinstance(data, dict) else None), result


def get_thread_messages(
    endpoint: str, token: str, thread_id: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET ``/api/v1/threads/{threadId}/messages``: the real transcript
    (author role, text, and tool-execution records) for one thread. This is
    the source of the actual investigation/remediation text `labctl demo
    verify` and `labctl evidence collect` surface -- never invented or
    summarized from memory (see AGENTS.md "do not publish ... unverified").
    """

    url = f"{endpoint}/api/v1/threads/{quote(thread_id, safe='')}/messages"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result(f"GET threads/{thread_id}/messages", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    value = data.get("value") if isinstance(data, dict) else data
    items = [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
    return items, result


def list_pending_approvals(
    endpoint: str, token: str, thread_id: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET ``/api/v1/approvals/{threadId}``: pending human-approval requests
    for a thread running in Review mode (see Microsoft's published API
    reference at https://learn.microsoft.com/azure/sre-agent/api-reference,
    section "Approvals"). An empty list means nothing is currently waiting
    on human approval for this thread (not necessarily that Review mode is
    off -- it may simply not have reached a mutating tool call yet).
    """

    url = f"{endpoint}/api/v1/approvals/{quote(thread_id, safe='')}"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result(f"GET approvals/{thread_id}", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    value = data.get("value") if isinstance(data, dict) else data
    items = [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
    return items, result


def decide_approval(
    endpoint: str,
    token: str,
    thread_id: str,
    approval_id: str,
    *,
    decision: str,
    reason: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> DataPlaneResult:
    """POST ``/api/v1/approvals/{threadId}/{id}/decision``: approve or reject
    one pending action (see Microsoft's published API reference at
    https://learn.microsoft.com/azure/sre-agent/api-reference, section
    "Approvals"). ``decision`` is passed through exactly as given by the
    caller (for example ``"Approved"``/``"Rejected"``); the live-confirmed
    exact casing/body shape is recorded in PLAN.md Milestone 5 once observed
    against a real pending approval, since the reference does not publish
    the request body schema.
    """

    url = (
        f"{endpoint}/api/v1/approvals/{quote(thread_id, safe='')}"
        f"/{quote(approval_id, safe='')}/decision"
    )
    body: dict[str, Any] = {"decision": decision}
    if reason:
        body["reason"] = reason
    response = http_request(
        url,
        method="POST",
        headers=_auth_headers(token, content_type="application/json"),
        data=json.dumps(body).encode("utf-8"),
        timeout=timeout,
    )
    return _to_result(f"POST approvals/{thread_id}/{approval_id}/decision", response)


def upload_knowledge_file(
    endpoint: str,
    token: str,
    *,
    filename: str,
    content: bytes,
    mime_type: str = "text/markdown",
    trigger_indexing: bool = True,
    timeout: float = UPLOAD_TIMEOUT,
) -> DataPlaneResult:
    """POST one file to ``/api/v1/AgentMemory/upload`` (multipart), matching
    the official template's ``DataPlane-UploadMultipart`` helper."""

    body, boundary = build_multipart_body("files", filename, content, mime_type)
    trigger = "true" if trigger_indexing else "false"
    url = f"{endpoint}/api/v1/AgentMemory/upload?triggerIndexing={trigger}"
    response = http_request(
        url,
        method="POST",
        headers=_auth_headers(token, content_type=f"multipart/form-data; boundary={boundary}"),
        data=body,
        timeout=timeout,
    )
    return _to_result(f"POST AgentMemory/upload ({filename})", response, ok_statuses=(200,))


def list_knowledge_files(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET ``/api/v1/AgentMemory/files``; response shape is ``{"files":
    [...], "continuationToken": ""}`` (live-verified)."""

    url = f"{endpoint}/api/v1/AgentMemory/files"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result("GET AgentMemory/files", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    files = data.get("files") if isinstance(data, dict) else None
    items = [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []
    return items, result


def put_github_domain_pat(
    endpoint: str,
    token: str,
    *,
    pat: str,
    domain: str = "github_com",
    timeout: float = DEFAULT_TIMEOUT,
) -> DataPlaneResult:
    """PUT ``/api/v2/github/domains/{domain}`` with a Personal Access Token
    (live-verified body shape: ``{"AuthType": "Pat", "Pat": "<token>"}``).
    This is the currently supported headless path: the official template's
    OAuth browser flow is not automatable from a non-interactive CLI (see
    SPEC.md section 10 and PLAN.md Milestone 4).
    """

    body = json.dumps({"AuthType": "Pat", "Pat": pat})
    url = f"{endpoint}/api/v2/github/domains/{domain}"
    response = http_request(
        url,
        method="PUT",
        headers=_auth_headers(token, content_type="application/json"),
        data=body.encode("utf-8"),
        timeout=timeout,
    )
    return _to_result(f"PUT github/domains/{domain}", response, ok_statuses=(200,))


def get_github_domains(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET ``/api/v2/github/domains``; response shape is ``{"values":
    [...]}`` (note: "values", not "value" -- live-verified, matches the
    official ``verify-agent.sh``'s ``.values`` lookup)."""

    url = f"{endpoint}/api/v2/github/domains"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result("GET github/domains", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    values = data.get("values") if isinstance(data, dict) else None
    items = [v for v in values if isinstance(v, dict)] if isinstance(values, list) else []
    return items, result


def put_repo(
    endpoint: str,
    token: str,
    *,
    name: str,
    url: str,
    repo_type: str = "GitHub",
    description: str = "",
    timeout: float = UPLOAD_TIMEOUT,
) -> DataPlaneResult:
    """PUT ``/api/v2/repos/{name}``.

    Live-observed quirk (this preview build, verified 2026-07-29): this
    route can respond HTTP 405 even though the write is actually applied --
    confirmed by reading the repo straight back and observing a changed
    ``description`` field across repeated calls despite every response being
    405. Treat a 405 here as tentatively successful and confirm with a GET
    readback before reporting failure, rather than trusting the HTTP status
    code alone (see PLAN.md Milestone 4 "API/schema adaptations").
    """

    body = json.dumps(
        {
            "name": name,
            "type": "CodeRepo",
            "properties": {"url": url, "type": repo_type, "description": description},
        }
    )
    put_url = f"{endpoint}/api/v2/repos/{quote(name, safe='')}"
    response = http_request(
        put_url,
        method="PUT",
        headers=_auth_headers(token, content_type="application/json"),
        data=body.encode("utf-8"),
        timeout=timeout,
    )
    if response.ok and 200 <= response.status_code < 300:
        return DataPlaneResult(True, response.status_code, f"PUT repos/{name}")
    if response.ok and response.status_code == 405:
        repos, _list_result = get_repos(endpoint, token, timeout=timeout)
        matching = next((r for r in (repos or []) if r.get("name") == name), None)
        actual_url = ((matching or {}).get("properties") or {}).get("url")
        if matching is not None and actual_url == url:
            return DataPlaneResult(
                True,
                405,
                f"PUT repos/{name}",
                "server returned HTTP 405 but the write was applied (confirmed by GET "
                "readback); known quirk of this preview build, see PLAN.md Milestone 4.",
            )
        return DataPlaneResult(
            False, 405, f"PUT repos/{name}", "GET readback did not confirm the write"
        )
    return _to_result(f"PUT repos/{name}", response)


def get_repos(
    endpoint: str, token: str, *, timeout: float = DEFAULT_TIMEOUT
) -> tuple[list[dict[str, Any]] | None, DataPlaneResult]:
    """GET ``/api/v2/repos``; response shape is ``{"value": [...],
    "nextLink": null}`` (live-verified)."""

    url = f"{endpoint}/api/v2/repos"
    response = http_request(url, method="GET", headers=_auth_headers(token), timeout=timeout)
    result = _to_result("GET repos", response, ok_statuses=(200,))
    if not result.ok:
        return None, result
    data = response.json()
    value = data.get("value") if isinstance(data, dict) else None
    items = [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
    return items, result


__all__ = [
    "DATA_PLANE_AUDIENCE",
    "ITEM_TYPES",
    "DataPlaneResult",
    "get_data_plane_token",
    "put_extended_item",
    "get_extended_items",
    "get_scheduled_tasks",
    "get_incident_filters",
    "list_threads",
    "get_thread",
    "get_thread_messages",
    "list_pending_approvals",
    "decide_approval",
    "upload_knowledge_file",
    "list_knowledge_files",
    "put_github_domain_pat",
    "get_github_domains",
    "put_repo",
    "get_repos",
]
