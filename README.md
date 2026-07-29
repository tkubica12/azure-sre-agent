# Azure SRE Agent demonstration

A presenter-operated environment that deploys a real, instrumented
application and a real Azure SRE Agent, injects a controlled production-like
incident, lets the agent investigate and propose a remediation, and proves
recovery. See [`SPEC.md`](SPEC.md) for the full specification and
[`PLAN.md`](PLAN.md) for milestone status. Repository-wide engineering rules
live in [`AGENTS.md`](AGENTS.md).

**Status (corrected 2026-07-29 during Milestone 7 clean-room validation):**
Milestone 5 (end-to-end incident scenario) is complete. `labctl preflight`,
`deploy`, `provision`, `verify`, `status`, `destroy`, `demo
list/prepare/trigger/verify/reset`, and `evidence collect` are all fully
functional against a real Azure subscription -- every one of them was
re-exercised live, from a fully destroyed-and-rebuilt environment, during
Milestone 7 (see `PLAN.md`). This corrects two claims that were previously
true but had gone stale in this file: `demo *`/`evidence collect` no longer
report "not implemented yet" (that applied only through Milestone 4), and
`labctl deploy` now calls `labctl provision` automatically as one of its own
steps (see the corrected operational note below).

## Prerequisites

- Windows PowerShell (primary supported operator platform)
- Python 3.11+
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), logged in (`az login`) with rights to
  create resources and role assignments in the target subscription
- [GitHub CLI](https://cli.github.com/), logged in (`gh auth login`)
- [Terraform](https://developer.hashicorp.com/terraform/install) (see pinned
  version in `infra/environments/demo/versions.tf`)

## Quick start

```powershell
# 1. Install labctl in a virtual environment
cd labctl
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"

# 2. Create your local, git-ignored configuration
cd ..
Copy-Item config.example.toml config.local.toml
# edit config.local.toml: set your owner tag, resource group names, etc.

# 3. Check your local tools, Azure/GitHub auth, permissions, and configuration
.\labctl\.venv\Scripts\labctl.exe preflight
```

`preflight` is read-only: it never creates an Azure resource, role
assignment, or file outside your local `.state/`/`.evidence/` directories. It
prints a PASS/WARN/FAIL line per check and exits nonzero if any check fails.

## Deploying the workload and the Azure SRE Agent

```powershell
# Preview what would be created/changed (read-only)
.\labctl\.venv\Scripts\labctl.exe deploy --plan-only

# Deploy for real: Terraform apply (workload + Azure SRE Agent), ACR cloud
# build, Container App update, agent/connector readiness polling, warm-up,
# and verification. Safe to re-run; unchanged app code and unchanged
# infrastructure are detected and skipped.
.\labctl\.venv\Scripts\labctl.exe deploy --yes

# Apply the agent's data-plane content: knowledge, a skill, subagents,
# safety hooks, common prompts, a scheduled task, the incident platform, a
# response plan, and the GitHub source connection. Idempotent; safe to
# re-run any time `agent/` content changes.
.\labctl\.venv\Scripts\labctl.exe provision

# Summarize local + Azure state with portal deep links, including the agent
.\labctl\.venv\Scripts\labctl.exe status

# Re-run just the health/telemetry/alert/revision/agent checks
.\labctl\.venv\Scripts\labctl.exe verify

# Tear everything down (checks resource-group ownership tags first; warns
# that a deployed agent incurs always-on Azure Agent Unit cost until deleted)
.\labctl\.venv\Scripts\labctl.exe destroy --plan-only
.\labctl\.venv\Scripts\labctl.exe destroy --yes
```

`deploy` and `destroy` never mutate Azure without `--yes`; without it they
run the equivalent Terraform plan and report what would happen. `verify`
checks endpoint health, the checkout journey, Container Apps revision mode
and traffic, the Azure Monitor alert rule, real telemetry arrival in both Log
Analytics and Application Insights (with bounded retries, since ingestion can
lag by a minute or two), and the Azure SRE Agent itself: provisioning state,
identities, RBAC on the workload resource group, `SRE Agent Administrator` at
the agent scope, connector provisioning state, and model/mode/access-level
configuration. Agent connector provisioning is asynchronous and documented to
take 10-30 minutes; `deploy` tolerates Terraform's own shorter timeout and
polls Azure directly to a bounded deadline instead of failing immediately.
Agent data-plane content (knowledge, skills, subagents, hooks, common
prompts, scheduled tasks, the incident platform, response plan, and GitHub
source connection) is applied by `labctl provision` and read back live by
`verify`/`status` -- both query the real agent data plane and ARM resource,
never the last `provision` run's reported success.

`labctl provision` requires one honest, one-time manual step: GitHub source
access uses your existing `gh auth token` as a Personal Access Token (PAT),
which is fully automated as long as `gh auth login` has already been run
(checked by `labctl preflight`). There is no unavoidable interactive OAuth
consent step in this configuration -- the official template's browser-based
GitHub OAuth flow is only needed as a fallback if a PAT is not available; see
`PLAN.md` Milestone 4 for the exact detection and fallback path.

**Operational note, corrected 2026-07-29 (Milestone 7 clean-room re-validation):**
`terraform apply` still resets the agent's `incidentManagementConfiguration`
(incident platform) to `null` on every apply, even one that only changes an
unrelated agent property -- that underlying platform behavior is unchanged.
But `labctl deploy` has, since Milestone 5, called `labctl provision`
automatically as one of its own steps (`[4/10]` reconciles the incident
platform immediately after `terraform apply`, and `[9/10]` re-applies the
rest of the agent data-plane content), so you do not need to run
`labctl provision` separately after a normal `labctl deploy --yes` -- it is
still safe and idempotent to do so if you ever want to re-apply `agent/`
content on its own without a full deploy. Live-reconfirmed 2026-07-29 against
a fully destroyed-and-rebuilt environment: a plain `labctl deploy --yes`
left `agent-incident-platform` and `agent-response-plans` both PASS in the
same run's own embedded verify, with no separate `labctl provision` invocation
required. See `docs/adr/0001-incident-platform-reconciliation.md` and
`PLAN.md` Milestone 5 for the full history of this finding.

Other lifecycle commands (`demo list|prepare|trigger|verify|reset`,
`evidence collect`) are fully implemented and were exercised live end-to-end
against a rebuilt environment during Milestone 7 (see `PLAN.md`).

## Repository layout

```text
infra/          Terraform for all Azure infrastructure and agent resources
app/            The small real workload deployed for the demonstration
agent/          Azure SRE Agent data-plane content applied by `labctl
                provision` (knowledge, skills, subagents, hooks, common
                prompts, scheduled tasks, incident platform/response plan)
labctl/         Python CLI: preflight, deploy, provision, verify, scenario
                control, reset, status, evidence collection, and destroy
scenarios/      Failure definitions, runbooks, and automated checks per scene
docs/           Presenter-facing HTML slides, guide, diagrams, and assets
scripts/        Thin bootstrap wrappers only (orchestration lives in labctl)
tests/          End-to-end and repository-wide validation
```

- [`AGENTS.md`](AGENTS.md) — engineering rules for this repository.
- [`SPEC.md`](SPEC.md) — architecture, scenarios, security model, acceptance
  criteria.
- [`PLAN.md`](PLAN.md) — milestones and current execution status.
- [`agent/README.md`](agent/README.md) — the Azure SRE Agent data-plane
  content `labctl provision` applies, and how to edit it.
- [`config.example.toml`](config.example.toml) — copy to `config.local.toml`
  (git-ignored) to configure your environment; never put secrets in either
  file.

## Development

Run from `labctl/` with the virtual environment created above:

```powershell
.\.venv\Scripts\python -m pytest       # unit tests
.\.venv\Scripts\python -m ruff check . # lint
.\.venv\Scripts\python -m ruff format . --check
.\.venv\Scripts\python -m mypy src     # type check
```

Run the same checks for the PulseMart application from `app/`:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format . --check
.\.venv\Scripts\python -m mypy pulsemart
```

Run from the repository root to validate Terraform without touching Azure:

```powershell
terraform -chdir=infra/environments/demo fmt -check -recursive -diff
terraform -chdir=infra/environments/demo init -input=false -backend=false
terraform -chdir=infra/environments/demo validate
```

HTML validation for `docs/` (link checking, accessibility contrast, keyboard
navigation, and responsive/theme behavior) is implemented and passes as of
Milestone 6/7 (182 + 31 checks, live-reconfirmed 2026-07-29). Run from the
repository root:

```powershell
python docs/tools/validate.py
node docs/tools/validate.mjs
```

`validate.mjs` requires Node.js and the dependencies in `docs/tools/
package.json` (`cd docs/tools && npm install` once, the same as any other
Node project).

## Cleanup

Terraform state stays local under `.state/` (git-ignored), alongside
`labctl`'s own non-secret deployment metadata (image tag, baseline revision,
generated `.tfvars.json`). `labctl destroy` is the normal end of every
rehearsal: it checks resource-group ownership tags, warns that a deployed
Azure SRE Agent incurs always-on Azure Agent Unit cost until deleted, runs
`terraform destroy` (removing the agent and the workload together), and
confirms both resource groups are actually gone before exiting 0.
