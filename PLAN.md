# Implementation plan

**Updated:** 2026-07-29 (Milestone 7 clean-room validation pass)  
**Current milestone:** 7 - Clean-room final validation (complete this session,
with one critical finding escalated to the product owner -- see Milestone 7
Finding F1: the repository's actual git history/remote does not contain the
implementation)

## Delivery strategy

Each milestone follows:

```text
research -> implement -> test -> deploy when applicable -> independent critic
-> fix material findings -> repeat
```

Live Azure validation starts as soon as the smallest deployable vertical slice
exists. It is not deferred until the end.

## Milestones

### 0. Research and specification - complete

- [x] Adapt repository-wide engineering rules in `AGENTS.md`.
- [x] Verify current first-party Azure SRE Agent documentation.
- [x] Inspect the official Terraform/AzAPI templates and data-plane workflow.
- [x] Confirm the active subscription has `Microsoft.App` registered.
- [x] Confirm Sweden Central exposes supported SRE Agent models.
- [x] Confirm effective permission includes resource and role-assignment
  operations through inherited Azure ownership.
- [x] Define the architecture, core incident, security model, automation
  contract, presentation, and acceptance criteria in `SPEC.md`.

### 1. Repository foundation - in progress

- [x] Add comprehensive `.gitignore`.
- [x] Add concise quick-start `README.md`.
- [x] Create the Python package and `labctl` console entry point.
- [x] Add typed local configuration and an ignored generated config path.
- [x] Implement subprocess, retry, redaction, Azure CLI, GitHub CLI, and
  Terraform helpers.
- [x] Implement `labctl preflight` and tests.
- [x] Create Terraform root/module layout and pinned providers.
- [ ] Add formatting, linting, typing, unit-test, Terraform, and HTML validation
  commands without unnecessary framework dependencies. Python (ruff, mypy,
  pytest) and Terraform (fmt/init/validate) commands are wired and documented
  in `README.md`; HTML validation is deferred until `docs/` exists
  (Milestone 6).

**Exit:** `labctl preflight`, Python tests, and `terraform validate` pass on the
operator machine without creating resources. Verified 2026-07-28: `labctl
preflight` ran against a live Azure subscription and GitHub session (13
passed, 2 warned, 0 failed, exit code 0); `pytest` (72 passed), `ruff check`,
`ruff format --check`, and `mypy` are clean; `terraform fmt/init/validate`
succeed in `infra/environments/demo` without any Azure write.

### 2. Workload and observability - complete

- [x] Implement the PulseMart FastAPI application and HTML status interface.
- [x] Add OpenTelemetry/Application Insights instrumentation.
- [x] Add structured logs and deterministic checkout failure behavior.
- [x] Add application tests and local container build checks where possible.
- [x] Deploy ACR, Log Analytics, Application Insights, Container Apps
  environment, identity, and Container App.
- [x] Configure Multiple revision mode and keep Terraform from reconciling
  scenario-owned revision templates and traffic weights.
- [x] Implement ACR cloud build and immutable image selection.
- [x] Configure real checkout-failure alerting.
- [x] Implement healthy smoke and telemetry checks.

**Live gate:** Deploy the workload, produce successful requests, and query
their real telemetry. **Met 2026-07-28** against subscription `tokubica`:
`labctl deploy --yes` created the workload resource group with ACR, a
workspace-based Log Analytics/Application Insights pair, a Consumption
Container Apps environment, and a Multiple-revision-mode Container App;
built the PulseMart image with `az acr build`; created baseline revision
`ca-pulsemart-demo--baseline-2d34d4f36555-0fbf79629033` at 100% traffic; and
`labctl verify` confirmed, with real Azure data: HTTP 200 on `/healthz` and
`/api/checkout`, `activeRevisionsMode=Multiple`, 100% traffic on the
baseline revision, an enabled `Requests` metric alert
(`alert-pulsemart-checkout-5xx`), real console-log rows in
`ContainerAppConsoleLogs_CL`, and real `requests`/`dependencies`/`traces`
rows in Application Insights (checkout, inventory.check, and payment.charge
spans, correctly nested under each HTTP request span). A second `labctl
deploy --yes` run was fully idempotent (ACR build and revision creation both
skipped as already present; `terraform plan` reports 12/12 no-op). Azure SRE
Agent checks correctly report WARN/"not deployed yet", as expected before
Milestone 3.

**Critic:** SRE scenario reviewer assesses telemetry usefulness and incident
realism.

### 3. Azure SRE Agent infrastructure - complete

- [x] Deploy the agent RG, identity, Log Analytics, and Application Insights.
- [x] Deploy `Microsoft.App/agents` with AzAPI.
- [x] Add App Insights, Log Analytics, and Azure Monitor connectors.
- [x] Apply the least-privilege workload-RG roles (`workload_access_level =
  "narrow"` by default: Reader + Log Analytics Reader at the resource group,
  Container Apps Contributor scoped to the Container App) to both agent
  identities and the deployer, plus subscription-scope Monitoring Contributor
  and agent-RG Monitoring Reader for alert lifecycle operations. A "broad"
  Contributor-at-resource-group escape hatch remains available and
  configurable if Milestone 5 live testing proves the narrow set
  insufficient for a real remediation action.
- [x] Expose safe portal and endpoint outputs.
- [x] Implement agent readiness and connector checks.
- [x] Validate the agent's monthly AAU allocation against a sensible
  demo-sized cap (1-5000; the official template's 10,000 is a permissive
  ceiling default, not a documented minimum) and model configuration.
- [x] Poll asynchronous connector provisioning through a bounded terminal-state
  check rather than treating the provider's expected timeout as final failure.

**Live gate:** Create the real agent in Sweden Central with RBAC and connectors
genuinely provisioned (not proof of agent-driven read access -- the queries
below run under the operator's own Azure CLI identity via `labctl
verify`/`status`, not the agent's; proving the agent itself can read the
workload is deferred to the Milestone 5 incident scene, where its own
investigation is the evidence -- see M7 review finding). **Met 2026-07-29**
against subscription `tokubica`: `labctl
deploy --yes` created `rg-sre-agent-demo` contents (`sre-agent-demo-uami`,
`law-sre-agent-demo`, `appi-sre-agent-demo`, and the `Microsoft.App/agents`
resource `sre-agent-demo`) alongside the already-deployed workload, applied
all 8 RBAC role assignments from SPEC.md section 9, created and provisioned
all 3 connectors (`app-insights`, `log-analytics`, `azure-monitor`) to
`Succeeded`, and `labctl verify`/`status` confirmed, with real Azure data:
`provisioningState=Succeeded`, `runningState`/`powerState=Running`,
`identity.type=SystemAssigned, UserAssigned` with the UAMI attached,
`defaultModel={Anthropic, Automatic}`, `accessLevel=High`, `mode=Review`,
`monthlyAgentUnitLimit=10000`, both identities holding Reader/Log Analytics
Reader/Contributor on the workload RG, the UAMI and deployer holding SRE
Agent Administrator on the agent resource, and all 3 connectors
`Succeeded`. A second `labctl deploy --yes` run was fully idempotent
(`terraform plan` reported 27/27 no-op). `labctl destroy --plan-only` was
exercised for real against the live state (without destroying anything) and
correctly lists every agent-owned resource alongside the workload's.

**2026-07-29 review follow-up:** an independent review found `labctl deploy`
was not actually repeatable end-to-end (a second `terraform apply` reset
`properties.incidentManagementConfiguration` to null because it was only set
by a one-time `labctl provision` ARM PATCH -- see B1), workload RBAC granted
blanket Contributor on the whole workload resource group instead of least
privilege (M2), alert-lifecycle RBAC (Monitoring Contributor/Reader) was
missing (M1), and several other gaps (B2/B3/M3/M4/M5/M6/M8). All are now
fixed: `labctl deploy` reconciles `incidentManagementConfiguration` with a
direct, idempotent ARM PATCH right after `terraform apply` (not a Terraform
resource -- a Terraform-native `azapi_update_resource` attempt failed live
with `MismatchingResourceIdentityPrincipalId`; see
docs/adr/0001-incident-platform-reconciliation.md), so it survives every
subsequent apply; workload RBAC
defaults to Reader + Log Analytics Reader + Container Apps Contributor
scoped to the Container App (`workload_access_level = "narrow"`, with
`"broad"` kept as a configurable escape hatch); Monitoring Contributor
(subscription scope) and Monitoring Reader (agent RG) are granted to satisfy
alert acknowledge/close. See SPEC.md sections 9 and 11 for the corrected
contract and the top-level task's final report for live evidence.

**Critic:** Azure architecture and security reviewers assess API usage,
identity, RBAC, cost, and destructive scope.

**API/schema adaptations made from the official template, based on live
validation:**

- The agent's real data-plane endpoint (`properties.agentEndpoint`) includes
  deployment-specific hash suffixes (e.g.
  `sre-agent-demo--<hash1>.<hash2>.swedencentral.azuresre.ai`), not the
  simple `<name>.<region>.azuresre.ai` pattern originally assumed. Fixed by
  adding `response_export_values = ["properties.agentEndpoint", ...]` to the
  `azapi_resource "agent"` resource and reading the real value back instead
  of guessing it.
- Live validation confirmed `Anthropic`/`Automatic` is both `default: true`
  and `preferred: true` in the subscription's `supportedAgentModels`
  response for `swedencentral`, matching the official template's default and
  `labctl preflight`'s existing `agent-model-availability` check.
- `SRE Agent Administrator` (`e79298df-d852-4c6d-84f9-5d13249d1e55`) is a
  real built-in role in this subscription (verified via `az role definition
  list`), so Terraform uses `role_definition_name` directly rather than
  constructing the role definition resource ID by hand.
- Connector provisioning completed well inside Terraform's own 10-minute
  per-resource timeout on both live runs (no connector ever needed the
  independent ARM-polling fallback to actually engage); the tolerant-timeout
  code path in `labctl deploy` is implemented and unit-tested but has not yet
  been exercised by a real slow connector.
- Discovered and fixed a latent, unrelated crash while validating `labctl
  destroy --plan-only` for real: Terraform's own plan output contains the
  box-drawing character U+2500, which is not encodable on Windows
  PowerShell's default `cp1252` console code page and crashed `labctl` with
  `UnicodeEncodeError`. Fixed by reconfiguring stdout/stderr to UTF-8 with
  lossy replacement at the top of the `cli()` command group (see
  `labctl/src/labctl/cli.py`).

### 4. Agent data-plane provisioning - complete

- [x] Implement `https://azuresre.dev` token acquisition without token logging.
- [x] Add idempotent data-plane client and retry policy.
- [x] Upload architecture, runbook, and remediation knowledge.
- [x] Apply common prompts, skills, subagents, and safety hooks.
- [x] Configure Azure Monitor as the incident platform.
- [x] Create the dedicated response plan.
- [x] Create the scheduled reliability summary.
- [x] Configure GitHub domain authentication from the existing GitHub CLI token.
- [x] Connect this repository. Indexing/clone status (`cloneStatus` on the
  live repo object) is read-only informational today, not yet a hard
  `verify` gate: cloning is asynchronous and was still `NotStarted` shortly
  after `labctl provision` in live testing. Polling it to a terminal state
  is deferred to Milestone 5, once a real investigation actually needs the
  cloned source.
- [x] Implement provision diff/status reporting.

**Live gate:** Every configured extension is visible through the live API and
passes `labctl verify`. **Met 2026-07-29** against subscription `tokubica`,
agent `sre-agent-demo`: `labctl provision` applied, over the agent's real
data-plane endpoint, the skill `triage-checkout-failures`, subagents
`incident-investigator` and `rollback-advisor`, hooks
`deny-destructive-deletes` and `require-approval-for-changes`, common prompts
`investigation-guidelines` and `safety-rules`, the scheduled task
`daily-reliability-summary`, four knowledge documents via `AgentMemory`
upload, the `AzMonitor` incident platform (ARM PATCH), the `checkout-5xx`
response plan, GitHub PAT authentication (`github.com` domain,
`isHealthy=true` on a later check), and the `azure-sre-agent` source
repository connection. `labctl verify` then read every one of those back
live and reported 24/24 PASS, 0 WARN, 0 FAIL, including all 7 new
data-plane-content checks (`agent-data-plane-token`,
`agent-incident-platform`, `agent-knowledge`, `agent-skills`,
`agent-subagents`, `agent-hooks`, `agent-common-prompts`,
`agent-scheduled-tasks`, `agent-response-plans`, `agent-github-repo`).
`labctl status` shows the same live-read content table plus the last local
`provision` run timestamp. A second `labctl provision` run was fully
idempotent: every PUT succeeded again with the same names (no duplicates --
independently confirmed by reading `/api/v1/scheduledtasks`,
`/api/v1/incidentPlayground/filters`, and `/api/v2/repos` straight from the
agent both before and after the second run), and the ARM incident-platform
PATCH was skipped both times after the first (already `AzMonitor`).

**Critic:** Clean-room reviewer checks idempotency, hidden authentication, and
failure diagnostics.

**Update 2026-07-29 (later the same day): `experimentalSettings` enabled and
re-validated.** The coordinator added
`experimentalSettings = { EnableWorkspaceTools = true, EnableHttpTriggers =
true, EnableV2AgentLoop = true }` to `infra/modules/sre_agent/main.tf`
(matching the official template; the live agent previously had
`experimentalSettings: null`). Applied for real with `labctl deploy --yes`
(not raw `terraform apply`, to keep ownership tags and every other variable
under `labctl`'s control) -- `terraform plan` showed exactly "26 to no-op, 1
to update" beforehand, and `terraform apply` updated only the agent
resource; `labctl verify`/`status` confirmed `experimentalSettings` live
afterward (`EnableWorkspaceTools`, `EnableHttpTriggers`, and
`EnableV2AgentLoop` all `true`). This produced two further live findings,
both fixed and re-verified the same session:

- **`terraform apply` resets `incidentManagementConfiguration` to `null`,
  even when the only intended change is unrelated
  (`experimentalSettings`).** The `azapi_resource` for the agent evidently
  issues an authoritative PUT of `properties` on every apply, and
  `incidentManagementConfiguration` is set only via `labctl provision`'s ARM
  `PATCH` (`agent_azure.set_incident_platform`), outside Terraform's own
  `body`. Directly observed: right after the `experimentalSettings` apply,
  `labctl verify` failed `agent-incident-platform` (`type=None, expected
  'AzMonitor'`) and `agent-response-plans` (the `checkout-5xx` filter,
  which requires the platform to be configured, had also been silently
  dropped by the platform alongside it). This is exactly the failure mode
  SPEC.md section 11's "`deploy` ... then call provision and verify"
  ordering exists to prevent, and is now first-hand evidence -- not just a
  spec reading -- that `labctl deploy` calling `labctl provision`
  automatically (still an open item under Milestone 5's first task) is a
  correctness requirement, not a convenience. Fixed for this session by
  re-running `labctl provision` (idempotent), which restored both; `labctl
  verify` returned to 24/24 PASS immediately after.
- **`EnableV2AgentLoop` puts the agent into "workspace mode", which rejects
  *any new* agent-to-agent handoff outright.** Re-running `labctl provision`
  after the `experimentalSettings` change failed on
  `subagents/incident-investigator` with `HTTP 400`: `"New agent-to-agent
  handoffs are not supported in workspace mode. Existing handoffs may only
  be retained or removed. Deliver cross-agent capabilities through skills
  and Task-based subagents instead."` Root cause was `labctl provision`'s
  own two-pass subagent apply (added earlier this milestone to fix a
  *different*, now-superseded ordering problem -- see the "Subagent handoff
  ordering" adaptation below): its first pass unconditionally PUT every
  subagent with `handoffs=[]` before re-PUT-ing the real value, which -- on
  a subagent that already had a real handoff from a prior `provision` run --
  counts as *removing* an existing handoff; the second pass then tried to
  re-add it, which workspace mode rejects as "new". This actually wiped
  `incident-investigator`'s `rollback-advisor` handoff live, and a direct
  manual retry (bypassing labctl entirely) confirmed the restriction is
  unconditional: PUT-ing the exact same `{name, target}` pair that
  definitely existed seconds earlier still failed with the same "new
  handoffs" error. Fixed by (1) removing the two-pass bootstrap from
  `labctl provision` (a single PUT per subagent, carrying `handoffs` exactly
  as declared in `agent/`), and (2) setting
  `agent/config/subagents/incident-investigator.yaml`'s `handoffs: []`
  permanently, with its instructions text updated to have the subagent
  *recommend* engaging `rollback-advisor` next in its written findings
  instead of relying on a platform handoff. Re-ran `labctl provision`
  (succeeded, both subagents `ok`) and `labctl verify` (24/24 PASS again).
  **This is the one piece of SPEC.md section 10 content that changed as a
  direct result of the coordinator's flag change**: the demo narrative still
  has two cooperating subagents, but their cooperation is now carried by
  instructions/skills, not the deprecated `handoffs` field, matching the
  platform's own stated migration path.
- **Hooks: confirmed byte-for-byte identical PUT/GET behavior before and
  after the flag change.** `GET /api/v2/extendedAgent/hooks` returned the
  exact same shape post-change as pre-change for both
  `deny-destructive-deletes` and `require-approval-for-changes`
  (`eventType`, `activationMode="always"`, `hook.{type,prompt,matcher}`);
  `permissionDecision`/`enabled` are still accepted on PUT and still not
  echoed back on GET, exactly as before (see the pre-existing "Hooks
  silently ignore `permissionDecision` and `enabled`" adaptation below --
  unaffected by this flag). What could **not** be verified this session is
  whether `EnableV2AgentLoop` changes *runtime enforcement* -- i.e. whether
  the agent actually pauses and requests human approval when it attempts a
  matching tool call during a real investigation. That requires a live
  incident with the agent actually attempting a traffic-changing operation,
  which is Milestone 5 (`bad-deployment`) scope and out of bounds for this
  milestone; it is called out here explicitly rather than assumed either
  way.

**GitHub authorization (the one boundary SPEC.md section 10/AGENTS.md ask to
be recorded honestly):** In this environment, GitHub source access needed
**no interactive OAuth/browser consent at all**. The operator's existing
`gh auth login` session (already required and checked by
`labctl preflight`'s `github-auth` check, which fails if the `repo` scope is
missing) provides a token via `gh auth token`; `labctl provision` POSTs that
token as a PAT to `PUT /api/v2/github/domains/github_com`
(`{"AuthType": "Pat", "Pat": "<token>"}`), which the official template's own
`Apply-Extras.ps1` documents as the headless alternative to its browser-based
OAuth flow. `labctl verify`'s `agent-github-repo` check confirms this
succeeded by reading `/api/v2/github/domains` back and requiring a
`github.com` entry to exist, in addition to confirming the repo itself and
its URL. If a future operator's `gh` session lacks the `repo` scope,
`labctl preflight` fails with an actionable `gh auth refresh -h github.com -s
repo` message before `provision` would even be attempted; there is currently
no code path in this repository that falls back to the interactive OAuth
browser flow, since the PAT path fully covers the demo's needs.

**API/schema adaptations made from the official template, based on live
validation against `sre-agent-demo` (subscription `tokubica`, region
`swedencentral`, build observed 2026-07-29):**

- **Subagent handoff ordering (superseded -- see the `experimentalSettings`
  update above).** Before this agent's `experimentalSettings
  .EnableV2AgentLoop` was enabled, `PUT /api/v2/extendedAgent/agents/{name}`
  validated that every name in `handoffs` already existed and rejected the
  PUT with HTTP 400 (`"Handoff agent 'rollback-advisor' does not exist."`)
  otherwise. Since `incident-investigator` hands off to `rollback-advisor`,
  PUT-ing subagents in file order (alphabetical) failed on the first live
  run; this was fixed at the time with a two-pass apply in `labctl
  provision` (PUT every subagent with empty `handoffs` first, then re-PUT
  each with its real `handoffs`). Once `EnableV2AgentLoop` was enabled later
  the same day, that same two-pass approach became actively harmful (its
  first pass looked like *removing* an existing handoff, and workspace mode
  rejects re-adding it as "new") -- see the `experimentalSettings` update
  above for the fix actually in place now: `labctl provision` PUTs each
  subagent once with `handoffs` exactly as declared, and this content
  declares no handoffs at all.
- **`incidentFilters` rejects `deepInvestigationEnabled`.** The official
  recipe's `azmon-sev01.yaml` sets `deepInvestigationEnabled: false`, but
  this preview build's `IncidentFilterView` has no such member: including it
  made the *entire* request fail to bind (`"could not be mapped to any .NET
  member"`, plus a misleading secondary `"request field is required"`
  error from the same failed bind). Fixed by omitting the field from the
  outgoing PUT body; `agent_content.IncidentFilterContent` still models it
  (so `agent/automations/incident-filters/checkout-5xx.yaml` stays
  comparable to the official recipe), `labctl provision` just does not send
  it. `maxAutomatedInvestigationAttempts` (an int, unlike the boolean
  `deepInvestigationEnabled`) is accepted normally.
- **`PUT /api/v2/repos/{name}` can return HTTP 405 while still applying the
  write.** Live-observed directly: calling it twice in a row with a changed
  `description` both times returned HTTP 405 both times, yet
  `GET /api/v2/repos` showed the second call's `description` had taken
  effect. `agent_dataplane.put_repo` now treats a 405 from this specific
  route as tentatively successful and confirms with an immediate GET
  readback (matching name and URL) before deciding pass/fail, rather than
  trusting the HTTP status code alone.
- **Hooks silently ignore `permissionDecision` and `enabled`.** `PUT
  /api/v2/extendedAgent/hooks/{name}` accepts a body containing
  `permissionDecision`/`enabled` (as the official recipe's own
  `deny-prod-deletes.yaml`/`require-approval-for-restarts.yaml` do) without
  error, but a subsequent GET shows neither field persisted --
  `properties` only ever contains `eventType`, `activationMode` (always
  `"always"`), `description`, and `hook` (`type`/`prompt`/`matcher`/etc.).
  This is not a labctl bug: the official recipe's own hooks rely on the
  same mechanism, so the actual safety control is the natural-language
  `hook.prompt` text the agent evaluates at tool-call time (e.g. "deny the
  action" / "require human approval before proceeding"), not a
  machine-enforced `permissionDecision` flag. `labctl provision` still
  sends both fields for forward-compatibility and recipe fidelity; `labctl
  verify`'s `agent-hooks` check only confirms the hook exists by name (it
  does not assert on `permissionDecision`, since the API does not return
  it).
- **`GET /api/v1/Github/auth/status` (and its `/api/v2` and lowercase-`g`
  variants) return the static frontend `index.html`, not JSON**, on this
  build -- i.e. the route does not exist server-side and falls through to
  the SPA's catch-all. `labctl` never relies on it; `agent-github-repo`
  confirms GitHub authentication via `GET /api/v2/github/domains`
  (`{"values": [{"name": "github.com", "authType": "Pat", ...}]}`) instead,
  which is the route the official template's own `Apply-Extras.ps1` uses
  for the equivalent check.
- **GET routes are inconsistent about the wrapper key and API version**,
  confirmed by direct live testing of every route this milestone uses:
  `GET /api/v2/extendedAgent/{skills,agents,hooks,commonprompts}` all wrap
  results as `{"value": [...], "nextLink": null}`; `GET
  /api/v1/scheduledtasks` and `GET /api/v1/incidentPlayground/filters` (note:
  distinct top-level `v1` routes, not `v2/extendedAgent/...`) return a bare
  JSON array; `GET /api/v2/github/domains` wraps as `{"values": [...]}`
  (plural, no `"value"` key); `GET /api/v2/repos` wraps as `{"value":
  [...]}`; `GET /api/v1/AgentMemory/files` wraps as `{"files": [...],
  "continuationToken": ""}`. `labctl.agent_dataplane` hard-codes the
  confirmed shape per route rather than guessing a single convention.
- Response-plan items key their name under `"id"`, not `"name"`
  (`GET /api/v1/incidentPlayground/filters` returned
  `{"id": "checkout-5xx", "name": "", ...}` live); `verify.py`'s
  `check_agent_response_plans` accepts either key for forward compatibility.
- **A leftover manual test artifact remains on the live agent**: a
  `probe-knowledge.md` AgentMemory file uploaded while validating the
  multipart upload route by hand before any code existed. No delete route
  for individual `AgentMemory` files was found in the official template's
  own scripts or by direct API probing (`DELETE` on several plausible paths
  all returned HTTP 405); it is harmless (a few bytes of unrelated test
  content) and does not affect `verify`, which only checks for the presence
  of the four real knowledge files, not the absence of extras. It can be
  removed later through the portal's Knowledge tab if desired.

### 5. End-to-end incident scenario - complete

> **Note (historical):** the note that used to live here about `labctl
> deploy` not calling `labctl provision` automatically no longer applies --
> `deploy` now calls `provision` as step [9/10] (idempotent; a provision
> failure escalates `deploy`'s exit code but does not stop warm-up/verify).
> See `labctl/src/labctl/deploy.py` `run_deploy`.

- [x] Wire `labctl deploy` to call `labctl provision` (idempotent) after the
  Container App update, matching SPEC.md section 11's documented sequence.
- [x] Implement prepare, trigger, verify, and reset for `bad-deployment`.
- [x] Shift traffic to a real failing revision.
- [x] Generate bounded synthetic checkout load.
- [x] Wait for and capture the fired alert.
- [x] Verify Azure SRE Agent incident pickup.
- [x] Rehearse the grounded investigation prompt and expected evidence.
- [x] Approve a real traffic rollback through the agent.
- [x] Verify application and telemetry recovery.
- [x] Repeat the scenario from reset state.
- [x] Implement redacted evidence collection.

**Live gate:** The exact presentation path succeeded twice, live, against the
real deployed environment on 2026-07-29 (see the live-verified facts below).
Both runs: real revision created -> real traffic shift -> real synthetic
5xx load -> real `alert-pulsemart-checkout-5xx` Fired transition -> real
Azure SRE Agent incident thread with a grounded investigation and cited
evidence -> a real traffic-rollback `az containerapp ingress traffic set`
executed by the agent -> `labctl demo verify`-confirmed recovery ->
`labctl demo reset`.

**Critic:** Not yet run as a separate reviewer pass; see "Known risks" below
for the material findings this milestone's own live testing already
surfaced (approval-gate reliability, agent self-report trustworthiness) that
a teacher/SRE critic pass should independently confirm before Milestone 6/7.

#### Addendum, 2026-07-30: Act-beat rework (agent-executed Autonomous remediation)

**Product-owner decision, implemented and live-proven this session:** restore
`rollback-advisor`'s `RunAzCliWriteCommands` tool and set `checkout-5xx`'s
`agentMode: Autonomous`, so the agent itself performs the real rollback,
framed honestly as Autonomous-mode remediation rather than a Review-mode
Approve/Deny gate that (per this milestone's own prior findings, unchanged)
does not engage in this preview build. Tool scoping plus the narrow,
Container-App-scoped RBAC grant become the demonstration's stated and
verified governance control. See SPEC.md section 5 Scene 5, section 9, and
`agent/config/subagents/rollback-advisor.yaml`/`.instructions.md` for the
corrected configuration and narrative; `scenarios/bad-deployment/runbook/
README.md` Step 4 for the corrected presenter script.

**What changed:**

- `agent/config/subagents/rollback-advisor.yaml`: `RunAzCliWriteCommands`
  restored to `tools:`. `incident-investigator` is unchanged (still holds no
  write tool at all -- the tool-scoping guarantee this whole story rests on).
- `agent/automations/incident-filters/checkout-5xx.yaml`: `agentMode: Review`
  -> `agentMode: Autonomous`.
- `labctl verify`'s `check_agent_subagents` now asserts the *live* tool set
  per subagent (not just that the subagent name exists), and
  `check_agent_response_plans` now asserts the *live* `agentMode` value, not
  just that the response plan exists. Both fail loudly on drift; see
  `labctl/src/labctl/verify.py` and its new tests in
  `labctl/tests/test_verify.py`.
- `infra/modules/sre_agent`'s `grant_uami_agent_administrator` docstring and
  the `uami_agent_admin` resource comment (both in `variables.tf`/`main.tf`)
  were corrected: an earlier draft claimed removing the UAMI's "SRE Agent
  Administrator" grant "restored a real, visible pending approval" -- this
  contradicted this same file's own later finding (self-approval "tested and
  found insufficient alone") and the actual second-round live test. Fixed to
  match reality: removing the grant did NOT, by itself, restore a working
  approval gate; it remains `false` by default as ordinary least-privilege
  practice, not as a claimed fix. `labctl/src/labctl/verify.py`'s
  `check_agent_admin_rbac` docstring corrected identically.
- `scenarios/bad-deployment/scenario.yaml`, `runbook/README.md`, and a new
  `scenarios/bad-deployment/tests/test_act_beat_narrative.py` updated/added
  so the Act beat's prose and the shipped agent configuration cannot
  silently drift back to the old, disproven "presenter runs `labctl demo
  reset` as the mitigation" narrative without a test failing.
- `SPEC.md` sections 1, 5 (Scene 5 renamed), 8, 9, 10, 12-13, 15: every claim
  of a working Review-mode Approve/Deny gate removed; Autonomous mode and
  tool-scoping/RBAC stated as the honest, verified control. `PLAN.md` (this
  file): "Known risks" table and environment facts below updated to match.

**Re-verified per this milestone's task 6 (RBAC question):** with
`grant_uami_agent_administrator` still `false` (unchanged; confirmed via
`az role assignment list --scope <agent-resource-id>` before and after both
live runs below) and `workload_access_level` still `"narrow"` (Container
Apps Contributor scoped to just the `ca-pulsemart-demo` resource, not the
resource group), the agent **still** performed the real rollback
successfully in both live runs below, with no
`AuthorizationFailed`/`LinkedAuthorizationFailed` error either time.
`labctl verify`'s `agent-rbac-admin` and `agent-rbac-workload` checks assert
this exact state and stayed PASS throughout.

**Live proof: two full end-to-end cycles, 2026-07-29 (this session).** Both
runs required forcing a genuinely fresh incident thread (a one-off
`mergeEnabled: false` PUT on the `checkout-5xx` filter before each trigger,
reverted to the platform default `true` afterward by the next
`labctl provision` run, exactly as this milestone's earlier merge-window
finding documented) because an unrelated, already-`resolved` thread from
~70 minutes earlier would otherwise have absorbed the new alert without
re-running investigation -- reconfirming that earlier finding rather than
contradicting it.

| Beat | Run 1 | Run 2 | Median (2 runs) | Worst case |
| --- | ---: | ---: | ---: | ---: |
| Trigger start -> real alert Fired | 260 s (4m20s) | 260 s (4m20s) | 260 s | 260 s |
| Alert Fired -> incident thread created | 52 s | 67 s | 60 s | 67 s |
| Thread created -> investigation report posted | 181 s (3m01s) | 178 s (2m58s) | 180 s | 181 s |
| Investigation report -> agent executes the real rollback | 56 s | 92 s | 74 s | 92 s |
| Rollback executed -> agent's own resolution summary posted | 191 s (3m11s) | 198 s (3m18s) | 195 s | 198 s |
| **Total: trigger start -> agent-reported resolution** | **741 s (12m21s)** | **795 s (13m15s)** | **768 s (12m48s)** | **795 s (13m15s)** |

Independent `labctl demo verify bad-deployment` (which never depends on or
waits for the agent's own narrative) confirmed `Phase: recovered` at
`15:14:46Z` (run 1) and `15:35:20Z` (run 2) -- in run 2, the independent
check actually completed 2 seconds *before* the agent posted its own
resolution summary. These are two data points, not a statistically
meaningful sample; treat the median as an approximate guide for the
presenter guide's timing budget, not a guaranteed number -- see the
alert-fire-latency variance already documented below (~4-8+ minutes
observed across this and the prior milestone's runs).

**The load-bearing evidence -- the agent's own identity performed the
write, not the operator or `labctl`:** for both runs, `az monitor
activity-log list --resource-group rg-sre-agent-workload-demo` shows a real
`Microsoft.App/containerApps/write` event 4-5 seconds after each
`RunAzCliWriteCommands` tool-call timestamp, with `caller` equal to
`a6eb4f26-xxxx-xxxx-xxxx-xxxxxxxxxxxx` -- confirmed via
`AgentContext.uami_principal_id` (from `labctl`'s own Terraform outputs) to
be the agent's own user-assigned managed identity, not the operator's signed-
in account and not the Azure CLI first-party app ID `labctl` uses for its own
calls. Full verbatim investigation reports, the exact executed commands, and
resolution summaries for both runs are captured in
`scenarios/bad-deployment/evidence/act-beat-transcript-2026-07-29.md`
(subscription/tenant/workspace GUIDs redacted; every other identifier is
real).

**Tool-scoping/RBAC-constraint evidence, live-captured this session (not
just `labctl verify`'s static assertion):** an ad hoc chat thread was opened
directly against the same live agent asking it to attempt an out-of-scope
write (`az group update --name rg-sre-agent-workload-demo --set
tags.rbac-scope-test=true` -- deliberately outside the Container-App-only
remit, and a harmless, reversible tag even if it had somehow succeeded). The
agent refused at the instruction layer without ever calling the tool (0 tool
calls made), and refused again when explicitly asked to bypass that
refusal "for this one authorized test." This is evidence the model respects
its own written scope in this instance -- it is NOT independent evidence of
the RBAC layer, since the write was never actually attempted. The RBAC
guarantee is instead verified structurally and reproducibly: `az role
assignment list --scope <container-app-id>` shows the agent UAMI's only
write-capable grant is "Container Apps Contributor" scoped to exactly that
one resource, and `az role definition list --name "Container Apps
Contributor"` shows that built-in role's entire `actions` list is
`Microsoft.App/*`/`Microsoft.Insights/alertRules/*`
(+ read-only `Microsoft.Authorization/*/read`), with no `Microsoft.Resources/*`
action anywhere -- so the probed `az group update ... tags...` command
could never have succeeded under this role regardless of scope. Full detail
in the evidence transcript referenced above.

**Environment left deployed, healthy, and reset** after both live cycles:
`labctl verify` returned 28/28 PASS (including the two new tool-scoping/
agentMode assertions), and `labctl demo reset bad-deployment` confirmed
`Phase: recovered` with 100% traffic on the baseline revision.

### 6. HTML slides and presenter guide

- [ ] Implement the self-contained visual system.
- [ ] Create the 16:9 slide deck and presenter notes.
- [ ] Create the detailed HTML operator guide.
- [ ] Add architecture and incident-flow diagrams.
- [ ] Add commands, timing, transitions, expected states, and fallback paths.
- [ ] Add current security, governance, pricing, and limitation content.
- [ ] Add keyboard, responsive, reduced-motion, light/dark, link, and
  accessibility checks.
- [ ] Capture only verified live screenshots where they improve delivery.

**Critic:** Presentation reviewer assesses factual accuracy, narrative,
readability, timing, and operability.

### 7. Clean-room final validation - complete (with one product-owner-level finding outstanding)

- [x] Destroy any development deployment.
- [x] Run preflight from the documented state.
- [x] Run a clean full deploy.
- [x] Run all healthy, incident, remediation, reset, and evidence checks.
- [x] Run repeat deploy and repeat scenario.
- [x] Rehearse the HTML presentation at 16:9 (automated: `docs/tools/validate.py`
  and `validate.mjs` cover responsive/16:9, contrast, keyboard-only slide
  navigation, deep links, and reduced-motion/theme persistence in a headless
  browser; no interactive human rehearsal was performed in this non-interactive
  session).
- [x] Run repository secret scanning.
- [x] Destroy all Azure resources (done once, live, to prove the path -- see
  below; environment was then rebuilt and is intentionally left deployed, see
  "Final state").
- [x] Query Azure to prove no owned resources remain (done after the real
  destroy, before rebuilding).
- [x] Resolve every blocking or material reviewer finding found live in this
  pass (one is a product-owner decision, not something `labctl`/Terraform can
  fix -- see finding F1 below).

**Exit:** Live-verified 2026-07-29/30 (this session) against subscription
`tokubica`, tenant `11111111-1111-1111-1111-111111111111`, region
`swedencentral`. This was a genuine adversarial clean-room pass: the operator
followed only what the documentation said, discovered every gap below by
actually hitting it (not by inside knowledge), and fixed what a `labctl`/
Terraform change could fix. One finding (F1) is a repository-state problem no
amount of `labctl`/Terraform change can fix and is escalated to the product
owner.

#### Finding F1 (critical, escalated -- not fixable by this session): the repository's actual git history does not contain the implementation

`git ls-tree --name-only HEAD` (HEAD = `2d34d4f`, exactly matching
`origin/main` per `git branch -vv`) returns only `AGENTS.md`, `LICENSE`, and
`README.md`. Every other file this milestone depended on --
`SPEC.md`, `PLAN.md`, `config.example.toml`, `.gitignore`, `agent/`, `app/`,
`docs/`, `infra/`, `labctl/`, `scenarios/`, `tests/` -- is untracked/
uncommitted working-tree state in this one local checkout (`git status
--porcelain` shows them all as `??`, and `git log --oneline` shows only two
commits, `1b11444 Initial commit` and `2d34d4f Save uncommitted changes`,
neither of which actually committed them). **A real `git clone
https://github.com/tkubica12/azure-sre-agent.git` today would produce a
three-file repository with no `labctl`, no Terraform, and no way to run any
command in this README.** This is the single most severe hidden-local-state
finding a clean-room operator can report: everything in Milestones 0-6 is
real and working, but only inside this one working directory -- it has never
actually reached the remote the README/`config.example.toml` point GitHub
integration and the agent's own source connection at
(`tkubica12/azure-sre-agent`). Per this session's explicit instructions not
to commit, this is escalated rather than fixed here: **the product owner must
commit and push the working tree before any other operator/environment can
reproduce this demo by cloning the repository**, and before the agent's own
GitHub source connection (which reads from `origin/main`) can see any of the
source it currently cites by path in its investigation reports (live-observed
this session: the agent's investigation correctly noted the connected repo
sparse-checkout only contains `AGENTS.md`/`LICENSE`/`README.md` and had to
fall back to operational knowledge instead of reading `app/pulsemart/
main.py` -- see the timing-drift discussion below; this finding is very
likely the root cause of that specific slowdown).

#### Full destroy -> rebuild cycle, with one real infrastructure defect found and fixed

**Destroy (from the pre-existing deployed environment):** `labctl destroy
--plan-only` correctly scoped the operation to exactly the 5 resources in
`rg-sre-agent-demo` and 9 in `rg-sre-agent-workload-demo` (0 unrecognized,
all four ownership tags matched, resource-group ARM IDs matched Terraform
state). The real `labctl destroy --yes` then **failed after 35 minutes**:

> `Error: deleting Resource Group "rg-sre-agent-demo": the Resource Group
> still contains Resources` -- `microsoft.alertsmanagement/
> smartDetectorAlertRules/Failure Anomalies - appi-*`.

**Root cause (new, live-discovered defect):** Application Insights
automatically provisions a "Failure Anomalies" smart detector alert rule
outside of Terraform whenever a Component is created. Terraform never models
this resource, so the AzureRM provider's default
`prevent_deletion_if_contains_resources = true` blocked resource-group
deletion after every other Terraform-owned resource was already gone --
turning what should be a ~4-minute destroy into a 35-minute failure.
**Fixed** in `infra/environments/demo/versions.tf`: added a `features {
resource_group { prevent_deletion_if_contains_resources = false } }` block to
the `azurerm` provider, matching HashiCorp's own documented remedy for this
exact scenario. This is safe specifically because `labctl destroy`'s own
ownership/enumeration check (unchanged) already refuses to proceed if any
child resource is unrecognized -- the AzureRM provider is only ever allowed to
delete a resource group `labctl` has already independently verified is fully
owned. Re-run after the fix: **4 minutes, 0 errors.**

A related, secondary defect surfaced on the very next retry: because the
first (failed) attempt had already deleted every resource except the smart
detector rule, `labctl destroy`'s ownership re-check correctly refused to
proceed a second time (rule carries no ownership tags of its own and is not
a Terraform-recognized child) -- this is `labctl` behaving exactly as
designed, not a bug, but it does mean an operator who hits the smart-detector
defect (now fixed) must pass `--allow-unrecognized-resources` once to clear
the resulting orphan, after manually confirming (as this session did) that
the flagged resource is the now-parentless smart detector rule and nothing
else. Total real Azure time across the failed run + orphan cleanup + the
final successful destroy: 35m15s + 35s (refused) + 4m05s = **~40 minutes**
end to end for a destroy that should normally take ~4 minutes; all of the
excess was the one defect above, now fixed for future runs.

**Post-destroy proof of complete cleanup (queried directly against Azure,
not inferred from `labctl`'s own report):** `az group exists` false for both
resource groups; `az resource list --resource-type Microsoft.App/agents`
across the whole subscription returned empty (no orphaned agent anywhere);
`az resource list --tag repository=azure-sre-agent` across the whole
subscription returned empty (no orphaned tagged resource anywhere, in any
other resource group); `az role assignment list --scope /subscriptions/
<id>` at subscription scope showed no role assignment with an empty/
unresolvable `principalName` (i.e., no assignment pointing at a deleted
principal); the only subscription-level diagnostic setting present
(`MCAPSGov-LogsToLAWS`) is a pre-existing tenant/organizational governance
setting unrelated to this repository, confirmed by name and confirmed absent
from every pre-destroy resource inventory this session captured. **No orphans
of any kind attributable to this repository were found.**

**Clean redeploy from zero:** local `.state/`, `.evidence/`, and
`infra/environments/demo/.terraform` were moved out of the repository
entirely (not deleted, to allow before/after comparison) to simulate a
genuinely fresh clone; `.terraform.lock.hcl` (git-tracked) and
`config.local.toml` (git-ignored, documented as operator-authored via
`Copy-Item config.example.toml config.local.toml`, and confirmed sufficient
as-is: every field in `config.example.toml` is self-documenting) were left in
place. `labctl preflight`: **13 passed, 2 warned, 0 failed** (identical to
Milestone 1's originally documented baseline -- the two warnings, `gh` missing
the optional `read:org` scope and the data-plane `azuresre.ai` hostname not
resolving from this network until an agent actually exists, are both
expected and already documented). `labctl deploy --yes`: **18m59s** total
(Terraform apply of 29 resources, ACR cloud build, Container App update,
agent + all three connectors reaching `Succeeded`, `labctl provision`
running automatically as step `[9/10]`, warm-up, and embedded verify) --
**26 passed, 2 warned, 0 failed** (the two warnings were expected Log
Analytics/App Insights ingestion lag, both resolved by the time a
standalone `labctl verify` ran minutes later: **28 passed, 0 warned, 0
failed**, matching the pre-existing environment's baseline exactly).
`labctl status` reported full agent/workload state with working portal deep
links. No retries, no timeouts, no manual intervention were needed anywhere
in this redeploy (the connector-provisioning documented 10-30 minute window
did not materialize this run -- all three connectors were already `Succeeded`
by the time `deploy` polled them).

#### Full incident scene on the rebuilt environment

`labctl demo list` -> `prepare` -> `trigger` -> (real alert, real agent
investigation, real agent-executed rollback) -> `verify` -> `reset`, all
against the newly created agent (`sre-agent-demo`, new UAMI principal
`71f249f6-xxxx-xxxx-xxxx-xxxxxxxxxxxx`, confirmed different from the
previous environment's `a6eb4f26-xxxx-xxxx-xxxx-xxxxxxxxxxxx`). `labctl demo
verify bad-deployment` independently confirmed `Phase: recovered` (3/3
checks passed) without ever depending on the agent's own narrative, and
`labctl demo reset bad-deployment` restored 100% baseline traffic and
healthy checkout.

**The load-bearing evidence still holds on a rebuilt environment:** `az
monitor activity-log list --resource-group rg-sre-agent-workload-demo`
shows `Microsoft.App/containerApps/write` at `2026-07-29T18:21:21Z` with
`caller=71f249f6-xxxx-xxxx-xxxx-xxxxxxxxxxxx` -- the *new* agent's own UAMI
(confirmed via `az identity show -g rg-sre-agent-demo -n
sre-agent-demo-uami --query principalId`), not the operator's
`operator@example.com` account (which appears on every other write in the
same activity-log window) and not the previous environment's agent identity.
An earlier `Microsoft.AlertsManagement/alerts/changestate/action` by the same
new principal at `18:13:53Z` (`Succeeded`) is the agent's own alert
acknowledgment, a separate, smaller piece of the same evidence chain. Both
identity checks needed to be *discovered fresh* against the rebuilt
environment, not assumed from the old session -- exactly as instructed.

Full grounded investigation report and resolution transcript were captured
directly from the agent data-plane thread API (`GET /api/v1/threads/{id}/
messages`) rather than summarized from memory, and are preserved in this
session's evidence bundle (`labctl evidence collect` output plus the raw
per-message JSON dump); the investigation genuinely correlated Container App
revision/traffic state, `ContainerAppConsoleLogs_CL` console-log ERROR
entries, the alert payload, and operational knowledge (`checkout-500-
runbook.md`/`architecture.md`) into a specific, correct root-cause hypothesis
and remediation recommendation, then handed off to `rollback-advisor`, which
executed the real `az containerapp ingress traffic set` write.

#### Timing: material drift versus the two-run median, root-caused

| Beat | This run (rebuilt env) | Prior median (2 runs) | Prior worst case | Drift |
| --- | ---: | ---: | ---: | --- |
| Trigger start -> alert Fired | 310 s (5m10s) | 260 s | 260 s | +50s (+19%) |
| Alert Fired -> incident thread created | 47 s | 60 s | 67 s | faster |
| Thread created -> investigation report posted | 383 s (6m23s) | 180 s | 181 s | **+202s (+112%), material** |
| Investigation report -> agent executes the real rollback | 64 s | 74 s | 92 s | within prior range |
| Rollback executed -> agent's own resolution summary posted | 250 s (4m10s) | 195 s | 198 s | **+52-55s (+27%), material** |
| **Total: trigger start -> agent-reported resolution** | **1055 s (17m35s)** | **768 s (12m48s)** | **795 s (13m15s)** | **+260-287s (+34-37%), material** |

All timestamps for this run are real ARM/agent-data-plane timestamps (the
alert's own `firedAt` field, the thread's `startMessage.timeStamp`, and each
message's `timeStamp`), not estimates -- captured by directly polling `GET
/api/v1/threads/{id}` and `GET /api/v1/threads/{id}/messages` (the same
routes `labctl demo verify`/`evidence collect` use) via `labctl`'s own
`agent_dataplane` module, cross-checked against `az monitor activity-log
list` for the real write. **Root causes for the two material beats, both
directly visible in the transcript, not speculative:**

1. **Investigation took 383s instead of ~180s** because several tool calls
   failed or dead-ended before the agent produced its report: three `az
   containerapp` CLI calls failed with "Unknown error occurred" (recovered
   via Azure Resource Graph + `az rest` instead); the agent initially queried
   Log Analytics using the App Insights app ID instead of the workspace ID
   (self-corrected); a `QueryAppInsightsUsingAppId` tool the agent expected
   from the triage skill was not available; and -- most likely the dominant
   cause, and directly tied to Finding F1 above -- the agent's connected
   GitHub source repo is a sparse checkout containing only `AGENTS.md`/
   `LICENSE`/`README.md` (because those are the only files actually committed
   to `origin/main`), so every attempt to read `app/pulsemart/main.py`/
   `settings.py` for source-level root-cause confirmation failed, including a
   `gh api` call that hit `401 Bad credentials` and two `git fetch`/`git show`
   attempts against `origin/main` that returned empty trees. The agent
   correctly recovered by relying on operational knowledge documents instead
   and produced a still-accurate, well-evidenced report, but this consumed
   real turns and wall-clock time this run's docs did not need to spend
   before Finding F1 is fixed.
2. **Rollback -> resolution took 250s instead of ~195s** because the
   `rollback-advisor` subagent hit its own turn limit/timeout mid-verification
   (its own message: "The rollback-advisor reached its turn limit") after the
   real `az containerapp ingress traffic set` write had already succeeded;
   the parent agent then had to independently re-verify the traffic state via
   direct `az rest` calls before it would post its final resolution summary.
   The underlying mitigation itself was not delayed (real write recorded at
   `18:21:21Z`, ~64s after the investigation report, consistent with the
   prior median) -- only the agent's own narration of success took longer.

**Presenter-guide impact:** the previously documented ~12m48s median/~13m15s
worst case should be treated as optimistic, not a guaranteed number, per this
milestone's own prior caveat -- this run's 17m35s is a third data point
showing real variance up to ~+37% over the prior worst case, driven by
investigation-path friction (worse once Finding F1 is fixed) and an
occasional subagent turn-limit hiccup during the resolution beat (unrelated
to Finding F1). No presenter-guide timing content exists yet to correct
(Milestone 6 has not published a timing budget page), so this is recorded
here for whoever writes that content next.

#### Idempotency and incident-platform survival (the historical defect this session specifically re-checked)

A second `labctl deploy --yes` against the now fully-deployed, already-
exercised environment: `terraform plan` reported **"no changes"**;
`incidentManagementConfiguration.type already AzMonitor` (the historical
defect from `docs/adr/0001-incident-platform-reconciliation.md` did **not**
regress); ACR build and Container App update were both skipped as already
present; `labctl provision` re-applied all data-plane content idempotently;
embedded verify reported **27 passed, 1 warned** (only the same expected App
Insights ingestion-lag warning), 0 failed. Total run time: 9m24s (shorter
than the first deploy, consistent with skipping the ACR build and Container
App update).

#### Evidence collection

`labctl evidence collect` wrote a redacted bundle to `.evidence/
20260729T182847Z/` (revisions, traffic, alert rule/instances, App Insights
requests/exceptions, Log Analytics console logs, scenario/deployment state,
the real incident thread and its full message transcript, and a manifest).
Scanned the bundle for `InstrumentationKey=`, `AccountKey=`, GitHub PAT
patterns (`ghp_*`/`github_pat_*`), bearer/JWT-shaped tokens, and raw
`Authorization` header values: **zero matches**. The bundle does contain a
`REDACTED` marker in two files (the incident-thread transcript and the
console-log dump), confirming `evidence._redact_recursive` actively engaged
on real content this run (the agent's own `cat .git/git-credentials`
probe output, among other things) rather than finding nothing to redact.

#### Static validation suite (all green)

- `labctl`: `pytest` 309 passed; `ruff check` all checks passed; `ruff format
  --check` 52 files already formatted; `mypy src` no issues in 27 files.
- `app`: `pytest` 9 passed (1 unrelated `httpx`/starlette deprecation
  warning, not this repository's code); `ruff check`/`format --check` clean
  (6 files); `mypy pulsemart` no issues in 4 files.
- Terraform (`infra/environments/demo`): `fmt -check -recursive -diff` clean
  (including the `versions.tf` fix below); `init -backend=false` and
  `validate` both succeed with no Azure write.
- Docs: `python docs/tools/validate.py` **182 passed, 0 failed** (link
  targets, no-emoji, unique IDs, CSS contrast light+dark, focus-visible,
  reduced-motion, responsive breakpoints, viewport meta, keyboard-key
  handling, ARIA fragment sync, no external network calls, well-formed SVG).
  `node docs/tools/validate.mjs` **31 passed, 0 failed** (deck navigation via
  every documented key, deep links, fragment ARIA/announcement, theme
  toggle/persistence/no-flash, no network access during any of the above).
  This corrects README's previous claim that HTML validation "is added
  alongside the presenter material in a later milestone" -- it already
  exists and passes; README is fixed accordingly.

#### What was fixed this session

- `infra/environments/demo/versions.tf`: added `features { resource_group {
  prevent_deletion_if_contains_resources = false } }` to the `azurerm`
  provider, fixing the live-discovered destroy defect above (App
  Insights-auto-created smart detector alert rules blocking resource-group
  deletion). Safe because `labctl destroy`'s own ownership/enumeration
  check is unaffected and still runs first.
- `README.md`: corrected three stale claims caught live by following the
  documentation as a newcomer would: (1) the top-of-file status line said
  "Milestone 4" and claimed `demo *`/`evidence collect` report "not
  implemented yet", both true only through Milestone 4 and false since
  Milestone 5; (2) the "Important operational note" claimed `labctl deploy`
  does not call `labctl provision` automatically, contradicted by both this
  session's own live run and `PLAN.md`'s own Milestone 5 historical note
  (`deploy` has called `provision` as step `[9/10]` since Milestone 5); (3)
  the Development section claimed HTML validation for `docs/` "is added
  alongside the presenter material in a later milestone," when it already
  exists, passes, and was exercised live this session -- the real commands
  are now documented instead.
- `poll_incident.py` and other scratch investigation tooling created during
  this session were deleted before finishing; nothing was left behind in
  the repository beyond the fixes listed above.

#### What is still broken / escalated, not fixed by this session

- **Finding F1 above (critical, escalated to the product owner):** the
  repository's actual `origin/main` contains only three files. This is not a
  `labctl`/Terraform defect and cannot be fixed by this session without
  committing (explicitly out of scope for this run) -- it must be committed
  and pushed before any other operator can reproduce this demo by cloning,
  and it is the most likely root cause of this run's investigation-beat
  timing drift (the agent's own GitHub source connection can only ever see
  what is actually on `origin/main`).
- The Review-mode Approve/Deny gate still does not engage in this preview
  build (unchanged from Milestone 5's own finding; `agentMode: Autonomous`
  plus tool-scoping/RBAC remain the honest, operative control, re-confirmed
  again this session by the real rollback executing without any pending
  approval ever appearing).
- `az containerapp` CLI calls occasionally return "Unknown error occurred"
  when invoked *by the agent itself* inside its own sandboxed tool
  environment (observed live this session, self-recovered via Resource
  Graph/`az rest`); this is a preview-build agent-tooling quirk, not
  reproducible from the operator's own `az` CLI (every operator-issued `az`/
  `labctl` command in this session succeeded), and is not something this
  repository's code can fix.
- Milestone 6's checklist above is still shown unchecked even though
  substantial, passing `docs/` content (slides, guide, ADR, assets, tools)
  already exists on disk -- this session did not audit or update Milestone
  6's own checklist/exit criteria, since that is a different milestone's
  scope; flagged here only because it is directly relevant to Finding F1
  (none of it is on `origin/main` either).

#### Final state left at the end of this session

Per this run's explicit instructions, the environment was left **deployed,
healthy, and reset** rather than destroyed: `labctl verify` = 28 passed, 0
warned, 0 failed; `labctl demo verify bad-deployment` = `Phase: recovered`,
3/3 passed; 100% traffic on the baseline revision; no active fault. The one
Terraform fix (`versions.tf`) and the three README corrections are the only
source changes made; both are currently uncommitted working-tree changes,
same as everything else in this repository per Finding F1, and were
deliberately not committed per this run's constraints.

## Current environment facts

- Azure CLI authentication is active.
- Effective Azure permissions are sufficient for resource and RBAC deployment.
- `Microsoft.App` is registered.
- Sweden Central supports Azure SRE Agent in the active subscription.
- Terraform 1.10.1 and Python 3.13 are installed.
- The Docker daemon is unavailable; ACR cloud builds are therefore required.
- GitHub CLI authentication has `repo` scope and the repository is public.
- On this Windows operator machine, `az acr build`'s streamed remote-log
  output can crash Azure CLI's colorama console wrapper with a
  `UnicodeEncodeError` against the legacy Windows code page (independent of
  `PYTHONIOENCODING`/`AZURE_CORE_NO_COLOR`); `labctl` calls `az acr build
  --no-logs` to avoid the crash while still waiting for the real build
  result (see `labctl/src/labctl/workload_azure.py`).
- Azure Monitor OpenTelemetry's automatic FastAPI instrumentation did not
  attach when the app is served via `uvicorn module:factory --factory`
  (observed live: request spans never reached Application Insights even
  though custom spans/logs/dependencies did). PulseMart disables the
  automatic FastAPI instrumentation and calls
  `FastAPIInstrumentor.instrument_app(app)` explicitly instead (see
  `app/pulsemart/main.py` and `app/pulsemart/telemetry.py`); live-verified to
  produce correctly nested request/dependency spans in Application Insights.
- `labctl`'s own stdout/stderr (not a subprocess it launches) can also crash
  with `UnicodeEncodeError` on Windows PowerShell's default `cp1252` console
  code page: Terraform's own plan/apply output legitimately contains
  non-ASCII characters (observed live: the box-drawing U+2500 separator in
  `terraform plan -destroy` output). `labctl`'s `cli()` command group now
  reconfigures stdout/stderr to UTF-8 with lossy replacement before running
  any command (see `labctl/src/labctl/cli.py`).
- Live-verified against subscription `tokubica`/region `swedencentral`: the
  Azure SRE Agent's real data-plane endpoint
  (`properties.agentEndpoint`) includes deployment-specific hash suffixes
  (e.g. `sre-agent-demo--<hash1>.<hash2>.swedencentral.azuresre.ai`), not
  a predictable `<name>.<region>.azuresre.ai` pattern; `infra/modules/sre_agent`
  exports the real ARM value instead of guessing it.
- Live-verified: `Microsoft.App/agents` and its connectors provisioned to
  `Succeeded` well inside Terraform's 10-minute per-connector timeout on
  both a clean deploy and a repeat deploy; the documented 10-30 minute
  asynchronous window (SPEC.md section 11) did not manifest in this
  subscription/region, so the tolerant-timeout / independent-ARM-polling
  fallback in `labctl deploy` remains unit-tested but not yet live-exercised
  by an actually slow connector.
- Live-verified 2026-07-29 (Milestone 4): `az account get-access-token
  --resource https://azuresre.dev` succeeds directly from an interactively
  `az login`-authenticated Windows session -- no separate consent or scope
  grant was needed beyond the existing login. `labctl` acquires this token
  through the existing `run_az`/bundled-Python-entry-point path (see
  `labctl/src/labctl/azure_cli.py`), so the same Windows `.cmd`-launcher
  quoting hazard mitigation that already protects `az rest` calls also
  protects the ARM `PATCH` this milestone adds
  (`agent_azure.set_incident_platform`); a plain inline JSON `--body`
  argument confirmed broken through the `az.cmd` batch launcher directly
  (`ERROR: ... 'Unexpected character encountered while parsing value: A.'`
  from mangled quoting) and confirmed working through the bundled
  `python.exe -IBm azure.cli` entry point `labctl` actually uses.
- `pyyaml` was added as a new `labctl` runtime dependency (plus
  `types-PyYAML` for `mypy`) to parse `agent/`'s `metadata`/`spec` YAML
  content, matching the official `microsoft/sre-agent` template's own
  recipe format; this is the only new dependency Milestone 4 introduced
  (see AGENTS.md "small dependency set").
- See Milestone 4 above for the full list of live-verified data-plane
  API/schema adaptations (subagent handoff ordering, `incidentFilters`'
  rejected `deepInvestigationEnabled` field, the `repos` PUT's HTTP 405
  quirk, hooks silently dropping `permissionDecision`/`enabled`, the
  nonexistent `Github/auth/status` route, and per-route GET wrapper-key
  inconsistency), and the "`experimentalSettings` enabled and re-validated"
  update for the two live findings from enabling `EnableV2AgentLoop`
  (`terraform apply` resets `incidentManagementConfiguration` to `null` on
  every apply, and "workspace mode" rejects any new agent-to-agent
  `handoffs`).
- Confirmed live 2026-07-29 (`az role definition list`): `Container Apps
  Contributor` **is** a real built-in Azure role in this subscription. An
  earlier note in this file/`SPEC.md` incorrectly stated it did not exist;
  RBAC design itself is out of this milestone's scope (tracked separately
  by the coordinator), this is recorded here only so the correction is not
  accidentally reverted by a future edit.
- Live-verified 2026-07-29 (Milestone 5, two full end-to-end runs): Azure
  Container Apps enforces a real, undocumented-in-isolation constraint that
  the container app name + `--` + revision suffix must not exceed **54**
  characters combined (`ContainerAppInvalidRevisionName`), which is
  materially shorter than the revision-suffix argument's own 63-character
  limit documented alone. `labctl demo trigger`'s
  `scenario._fault_revision_suffix` computes the real available budget from
  the actual container app name and falls back to a short `<prefix>-<epoch>`
  form when the full `<prefix>-<image-tag>-<epoch>` form would not fit.
- Live-verified 2026-07-29: `Microsoft.AlertsManagement/alerts`
  (`api-version=2019-05-05-preview`) is the correct API for reading a real
  fired/resolved alert *instance* (distinct from the static metric-alert
  *rule* `az monitor metrics alert show` reads). The `alertRuleName` query
  parameter is rejected outright; the accepted `alertRule` parameter filters
  on the rule's full ARM resource ID, not its bare name, and silently
  matched zero alerts when passed just the name. `targetResource` (the
  monitored resource's own full ID) reliably filters instead; see
  `labctl.workload_azure.list_fired_alerts`.
- Live-verified 2026-07-29: with zero data-plane configuration beyond what
  Milestone 4 already provisions, a real Azure Monitor alert Fired
  transition automatically produced a real Azure SRE Agent incident thread
  (`source: "Incident"`, `incidentSource.incidentType: "AzMonitor"`) with a
  genuine, tool-grounded investigation -- the `azure-monitor` connector,
  `incidentManagementConfiguration.type=AzMonitor`, and the
  `checkout-5xx` response plan together were sufficient; no webhook, action
  group Automation Runbook/Function, or other bridge was needed. Repeated on
  a second, independent fault-trigger run: the second real alert instance
  merged into the same thread (`mergeEnabled: true`, `mergeWindowHours: 3`
  on the response plan) rather than opening a second thread -- a presenter
  rehearsing this scenario twice within one 3-hour window sees continued
  activity on the same incident thread, not a fresh one.
- Live-verified 2026-07-29: the `incident-investigator` subagent, grounded
  by the `triage-checkout-failures` skill and uploaded knowledge, correctly
  identified the exact fault revision, timeline, and root cause from
  Container App revision state, platform metrics, and
  `ContainerAppConsoleLogs_CL` console logs, cross-referenced the connected
  (private) GitHub repository's documented behavior against
  `architecture.md` when a direct GitHub API/raw-content read was denied
  (private repo, no injected credential in the sandboxed terminal), and
  produced a complete cited investigation report -- all matching SPEC.md
  section 5 Scene 4's requirements. Application Insights workspace-based
  queries (`AppRequests`/`AppDependencies`/`AppExceptions`) returned zero
  rows for several minutes after real traffic (observed, repeatedly, across
  both live runs); the agent correctly treated this as ingestion lag rather
  than a missing-telemetry problem and fell back to platform metrics and
  console logs, which is the same tolerant pattern
  `labctl.verify.check_app_insights_telemetry`/`check_log_analytics_telemetry`
  already use (bounded retries, WARN not FAIL).
- Live-verified 2026-07-29: the narrowed workload RBAC set (Reader + Log
  Analytics Reader at the workload resource group, Container Apps
  Contributor scoped to the Container App, Monitoring Contributor at
  subscription scope, Monitoring Reader on the agent RG) is **sufficient**
  for the agent to perform the real remediation. Across both live runs, the
  agent (via a Task-delegated `rollback-advisor`-equivalent execution, since
  `experimentalSettings.EnableV2AgentLoop`'s "workspace mode" rejects new
  agent-to-agent `handoffs`; see Milestone 4) ran a real
  `az containerapp ingress traffic set --revision-weight
  <baseline>=100 <fault>=0` and it succeeded with no
  `AuthorizationFailed`/`LinkedAuthorizationFailed` error either time. The
  `broad` access-level escape hatch was not needed and remains untouched.
- **Material finding, live-verified 2026-07-29 (four real write-tool
  executions across two incident cycles plus two targeted follow-up
  tests):** the intended human-approval gate for mutating actions did not
  verifiably engage. `GET /api/v1/approvals/{threadId}` returned an empty
  list immediately before, during, and after every real
  `RunAzCliWriteCommands` execution the agent performed, regardless of (a)
  the agent-wide `actionConfiguration.mode: Review` default (unchanged
  throughout), (b) the `checkout-5xx` response plan's own `agentMode`
  field (tested as both the original `Autonomous` and, after this
  milestone changed it, `Review` -- see
  `agent/automations/incident-filters/checkout-5xx.yaml`), and (c) fixing
  `require-approval-for-changes`'s `matcher` from a hypothetical granular
  tool-name pattern (`^(restart_|scale_|...)`) to the agent's real,
  generic write tool name (`^RunAzCliWriteCommands$`; see
  `agent/config/hooks/require-approval-for-changes.yaml`) and re-running
  `labctl provision`. In every case the write executed immediately. Two
  independently working guardrails were confirmed instead: the
  `incident-investigator` subagent's own tool scope (no
  `RunAzCliWriteCommands`) correctly makes it *refuse* a direct mutation
  request in its own turn ("Traffic mutations are exclusively the
  rollback-advisor's responsibility"), and PLAN.md Milestone 4's
  already-documented finding that this preview data-plane API silently
  drops a PUT hook's `permissionDecision`/`enabled` fields is the most
  likely root cause: there may currently be no way to configure a
  `PreToolUse` prompt hook's decision to actually block via this route.
  **The agent's own generated narrative text is not reliable evidence
  either way**: after the matcher fix, the agent's final report explicitly
  claimed "the write command went through the `require-approval-for-changes`
  hook" and "approval obtained" for a run where the independent
  `/api/v1/approvals` check showed nothing pending at any point --
  `labctl`/presenters must verify approval gating via that API (or the
  portal's own pending-approval UI) directly, never by trusting the
  agent's self-report. This is the single most important unresolved
  finding from this milestone; see "Known risks" below.
- **Follow-up investigation, 2026-07-29 (same day, continuation of the
  above): the root cause is now resolved with hard evidence, and the
  demonstration's safety story has been redesigned around what is actually
  provable.** Summary (see git history/session record for exact commands,
  API bodies, and timestamps):
  - **H1 (self-approval via UAMI "SRE Agent Administrator") tested and
    found insufficient alone.** `infra/modules/sre_agent`'s
    `uami_agent_admin` role assignment (the agent UAMI holding "SRE Agent
    Administrator" on its own agent resource -- present since this
    repository first matched the official template's general recipe) is a
    plausible self-approval vector, since "only SRE Agent Administrators
    can approve actions". Microsoft's own `deployment-compliance` reference
    lab (a purpose-built approval-gate demo) grants that role only to the
    deploying human, and its `agent-core.bicep` comments the UAMI variant
    of the grant as "needed for Logic App webhook bridge to call HTTP
    triggers" -- a capability this repository never used. The grant was
    made conditional on a new `grant_uami_agent_administrator` variable
    (default `false`) and removed live via `labctl deploy` (confirmed via
    `terraform plan`: exactly 1 resource to delete; `labctl verify`'s
    `agent-rbac-admin` check now asserts the UAMI does *not* have the role).
    **Result: removing it did NOT restore a working approval gate.** A
    second full incident cycle, run specifically to test this fix, still
    executed the mutating `az containerapp ingress traffic set` write with
    zero `/api/v1/approvals/{threadId}` entries ever appearing.
  - **New finding: merged/reactivated incident threads pin `agentMode` at
    thread-creation time.** Incidents merge into the same thread for any
    alert firing within `mergeWindowHours` (3h) of the previous one
    (`mergeEnabled`/`mergeWindowHours` on the incident filter -- fields the
    data-plane schema accepts but `agent_content`/`labctl provision` did not
    previously model). The first test above happened to reuse a thread
    created hours earlier while the response plan's `agentMode` was still
    the pre-fix value; the thread's own `agentMode` field never updated
    even after `labctl provision` re-PUT the filter with `agentMode:
    Review`. Confirmed by temporarily PUTing `mergeEnabled: false` (a
    one-off data-plane call, not a repository change -- `labctl provision`
    resets it back to `true` on the next run, since it never sends that
    field) to force a brand-new thread; the new thread's `agentMode` field
    read `"Review"` as expected. **A second, definitive test on this
    verified-fresh Review-mode thread** (with the UAMI's admin role also
    still removed) again showed the write execute for real -- Activity Log
    entry ~5 seconds after the tool-call message, caller = the agent UAMI,
    `/api/v1/approvals/{threadId}` empty and every message's
    `hookExecution`/`approval` fields `null` the entire time. This
    definitively rules out both "stale thread" and "self-approval" as the
    explanation and confirms the underlying platform limitation is real and
    not an artifact of this repository's configuration.
  - **New finding: the hook-persistence defect (PLAN.md Milestone 4) is
    broader than previously known.** A probe PUT of a `Stop`-event,
    `activationMode: onDemand` hook (the exact shape Microsoft's
    `deployment-compliance` reference lab uses for its own approval-gate
    hook) was accepted and correctly persisted `eventType`, `activationMode`
    (note the API's real enum values are `always`/`onDemand`, not the
    lab's own README casing `on-demand`), and `hook.timeout` -- but silently
    dropped `hook.failMode` and `hook.maxRejections` (both came back `null`
    on GET), the same class of defect already found for `PreToolUse`'s
    `permissionDecision`/`enabled` fields. No hook shape this repository can
    configure via the current data-plane API has a verified-working blocking
    mode. The probe hook was deleted after the test; no `Stop`-type hook is
    part of the shipped `agent/` content.
  - **Decision and fix actually shipped:** since neither the platform's
    Review-mode UI nor any hook shape reliably blocks a write, and prompt-only
    instructions telling subagents to "wait for approval" were also
    demonstrably not followed (the exact behavior this milestone already
    flagged), the only mechanism this milestone found to be 100% reliable is
    **tool-scoping**: `agent/config/subagents/rollback-advisor.yaml` no
    longer has `RunAzCliWriteCommands` in its `tools` list. Live-verified
    2026-07-29 (third full incident cycle, after this change and after
    re-provisioning): the agent investigated, engaged `rollback-advisor`,
    which called only `RunAzCliReadCommands`, and the thread's final message
    explicitly stated the exact `az containerapp ingress traffic set`
    command for "a human presenter" to run -- **no write-tool call was
    attempted, and the Activity Log confirms zero new agent-caller writes**.
    `labctl demo verify bad-deployment` at that point still showed
    `Phase: fault` (traffic still 100% on the fault revision, checkout still
    500) -- the deny/no-op proof. The presenter then ran `labctl demo reset
    bad-deployment`; the Activity Log shows the resulting
    `Microsoft.App/containerApps/write` under the presenter's own Azure CLI
    identity (`claims.appid` = the well-known Azure CLI first-party app ID),
    seconds later, and `labctl demo verify bad-deployment` immediately
    showed `Phase: recovered` -- the approve proof. This is the full
    approve/deny evidence pair the safety story now rests on; see SPEC.md
    section 5 Scene 5, section 9, and the `bad-deployment` runbook's Step 4
    for the corrected narrative. `agent/config/hooks/*.yaml` and
    `infra/modules/sre_agent`'s `grant_uami_agent_administrator` variable
    are both kept and documented as-is (removing the self-approval grant is
    still correct least-privilege practice; the hooks remain as documented
    intent that will start working automatically if Microsoft fixes the
    underlying persistence defect), but neither is claimed as the operative
    safety gate anywhere in this repository anymore.
- Live-verified 2026-07-29: an evidence-collection defect existed and was
  fixed within this milestone: `labctl evidence collect`'s
  `containerapp-revisions.json` and the agent's own captured thread
  transcript both contained a real, live Application Insights connection
  string (`InstrumentationKey=...`) in cleartext -- from stale revisions
  created before this repository's `secretref:`-only convention, and from
  the agent's own tool-execution output describing an `az monitor
  app-insights component show` result. `labctl.procutil.redact`'s existing
  patterns were never applied to evidence JSON. `labctl/src/labctl/
  evidence.py` now recursively redacts every string leaf before writing any
  evidence file (see `_redact_recursive`); re-collecting evidence
  afterward confirmed zero secret-pattern matches across the bundle.

## Known risks

| Risk | Mitigation |
| --- | --- |
| Preview API/data-plane drift | Pin the tested version, follow the official template contract, and fail with exact endpoint diagnostics |
| Alert and incident pickup latency | Use deterministic traffic, bounded waits, visible phase status, and a rehearsed timing buffer (live-verified 2026-07-29: real time-to-Fired varied from ~4 min to over 8 min across two runs; `labctl demo trigger` reports what it actually observed rather than assuming a fixed number) |
| Agent response variability | Ground with narrow resource scope, structured telemetry, runbook, source, subagent, and evidence-based prompts |
| OAuth or token scope mismatch | Detect in preflight (`github-auth` check requires the `repo` scope), use the existing GitHub CLI token as a PAT for the data-plane's headless auth path (live-verified 2026-07-29: no interactive OAuth consent was actually required in this environment) |
| Always-on agent cost | Use one agent, show cost state, and make destroy the normal final command |
| **Azure SRE Agent's own Review-mode approval UI and `PreToolUse`/`Stop` hooks do not reliably gate a mutating write in this preview API build** (live-verified 2026-07-29 across three independent test cycles, including a self-approval-RBAC fix and a verified-fresh Review-mode thread; see Milestone 5 findings above) | **Governed at the tool-scoping/RBAC level, not the platform level (product-owner decision, 2026-07-30):** since no Review-mode gate reliably engages, the demonstration is honestly configured `agentMode: Autonomous` and `rollback-advisor` holds `RunAzCliWriteCommands` again -- it executes the real rollback itself. The operative controls are (1) `incident-investigator` structurally cannot write at all, and (2) `rollback-advisor`'s managed identity is scoped to "Container Apps Contributor" on only the one Container App resource, not the resource group. The agent-level `actionMode: Review` and the `PreToolUse` hooks remain configured as documented intent (harmless, and will engage automatically if Microsoft fixes the underlying platform defect) but must never be presented or relied on as the operative gate. **Presenters must still independently check the Azure Activity Log's `caller` field (or `labctl demo verify`) rather than trusting the agent's self-reported narrative about what it did or didn't do** -- live-reconfirmed 2026-07-30 across two more end-to-end cycles: both real rollback writes show `caller=a6eb4f26-xxxx-xxxx-xxxx-xxxxxxxxxxxx` (the agent's own UAMI), not the operator's identity |
| Merged/reactivated incident threads pin `agentMode` (and can stall at `investigationStatus: Complete`) from thread-creation time, not from the response plan's current configuration (live-verified 2026-07-29; see Milestone 5 findings above) | Documented in the `bad-deployment` runbook's "Fallback paths": rehearsing more than once inside the 3-hour `mergeWindowHours` window may reuse a thread that does not re-run automated investigation narration; the fault/recovery mechanics (`labctl demo trigger`/`reset`) are unaffected either way, since they never depend on the agent |
| Terraform drift from scenario changes | Ignore scenario-owned app template and traffic fields in Terraform; let labctl record and restore the baseline |
| `terraform apply`/`labctl deploy` silently resets agent data-plane-only ARM properties (`incidentManagementConfiguration`, live-confirmed 2026-07-29) | `labctl deploy` now calls `labctl provision` automatically (idempotent) as of Milestone 5; `labctl verify`'s `agent-incident-platform`/`agent-response-plans` checks catch a regression immediately either way |
| Evidence bundles can capture live secrets from raw Azure CLI/agent-transcript output (live-verified 2026-07-29; see Milestone 5 findings above) | `labctl.evidence._redact_recursive` redacts every string leaf before any evidence file is written; re-verify with a fresh secret scan after any change to what `evidence collect` captures |
| No live test has exercised an actual delete/destructive attempt against `deny-destructive-deletes` (deliberately -- an unreversible action is not a safe experiment against live demo resources), and the identically-shaped `require-approval-for-changes` hook is now confirmed unreliable, so this hook has no positive evidence of actually blocking anything either | `incident-investigator` is granted no tool broader than `RunAzCliReadCommands`; `rollback-advisor` (as of the 2026-07-30 product-owner decision) does hold `RunAzCliWriteCommands`, but its managed identity's only write-capable RBAC grant is "Container Apps Contributor" scoped to just the `ca-pulsemart-demo` Container App resource, not the resource group. That role's action list is entirely `Microsoft.App/*`/`Microsoft.Insights/alertRules/*` (live-confirmed via `az role definition list`, 2026-07-30) with no `Microsoft.Resources/*` action, so this identity structurally cannot delete the ACR, Log Analytics workspace, alert rule, or resource group regardless of what any subagent attempts -- deletion of the Container App itself remains technically possible at the RBAC layer (the role's `Microsoft.App/containerApps/*/delete` action) and is not proven blocked by any live test; treat as unresolved, not closed |

## Progress tracking

This file tracks engineering milestones. Operational task status is also kept in
the session task database during implementation. Update milestone state only at
material boundaries.
