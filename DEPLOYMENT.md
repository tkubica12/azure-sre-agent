# Deployment and operation

Everything needed to stand this demonstration up, run it, and tear it down.
For what the demo actually shows, see [`README.md`](README.md). For the
architecture and acceptance criteria, see [`SPEC.md`](SPEC.md).

## Prerequisites

- Windows PowerShell (primary supported operator platform)
- Python 3.11+
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), logged
  in (`az login`) with rights to create resources and role assignments in the
  target subscription
- [GitHub CLI](https://cli.github.com/), logged in (`gh auth login`)
- [Terraform](https://developer.hashicorp.com/terraform/install) (version
  pinned in `infra/environments/demo/versions.tf`)
- Node.js, only if you want to run the presenter-HTML validators

A local Docker daemon is **not** required. Container images are built in the
cloud with `az acr build`.

## First run

```powershell
# 1. Install labctl in a virtual environment
cd labctl
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"

# 2. Create your local, git-ignored configuration
cd ..
Copy-Item config.example.toml config.local.toml
# edit config.local.toml: set your owner tag, resource group names, etc.

# 3. Check local tools, Azure/GitHub auth, permissions, and configuration
.\labctl\.venv\Scripts\labctl.exe preflight
```

`preflight` is read-only: it never creates an Azure resource, role assignment,
or file outside your local `.state/`/`.evidence/` directories. It prints a
PASS/WARN/FAIL line per check and exits nonzero if any check fails.

Never put secrets in `config.example.toml` or `config.local.toml`. The latter
is git-ignored; authentication comes from your Azure CLI and GitHub CLI
sessions.

## Lifecycle

```powershell
# Preview what would be created or changed (read-only)
.\labctl\.venv\Scripts\labctl.exe deploy --plan-only

# Deploy for real
.\labctl\.venv\Scripts\labctl.exe deploy --yes

# Summarize local + Azure state with portal deep links
.\labctl\.venv\Scripts\labctl.exe status

# Re-run health, telemetry, alert, revision, and agent checks
.\labctl\.venv\Scripts\labctl.exe verify

# Collect an evidence bundle (secrets redacted)
.\labctl\.venv\Scripts\labctl.exe evidence collect

# Tear everything down
.\labctl\.venv\Scripts\labctl.exe destroy --plan-only
.\labctl\.venv\Scripts\labctl.exe destroy --yes
```

`deploy` and `destroy` never mutate Azure without `--yes`; without it they run
the equivalent Terraform plan and report what would happen.

`deploy` performs the whole path: `terraform apply` for the workload and the
Azure SRE Agent, an ACR cloud build, the Container App update, agent and
connector readiness polling, application warm-up, agent data-plane content,
and verification. It is safe to re-run — unchanged application code and
unchanged infrastructure are detected and skipped.

Agent connector provisioning is asynchronous and documented to take 10-30
minutes. `deploy` tolerates Terraform's own shorter timeout and polls Azure
directly to a bounded deadline rather than failing immediately.

### Running a scene

```powershell
.\labctl\.venv\Scripts\labctl.exe demo list
.\labctl\.venv\Scripts\labctl.exe demo prepare bad-deployment
.\labctl\.venv\Scripts\labctl.exe demo trigger bad-deployment
.\labctl\.venv\Scripts\labctl.exe demo verify  bad-deployment
.\labctl\.venv\Scripts\labctl.exe demo reset   bad-deployment
```

`demo reset` is the operator safety net, not the demonstration's remediation —
the agent performs the real remediation itself. Reset is always safe to run
and is how you return to a clean baseline.

The two scenes cannot run concurrently, because both set traffic weights on
the same Container App. Reset one before triggering the other.

### Reading `demo verify` results

Read the exit code and each check's status rather than memorizing a count:

| Status | Meaning |
| --- | --- |
| `PASS` | proven |
| `WARN` | **not yet provable** — an alert still resolving, or telemetry still ingesting. Exits zero. Wait and re-run. |
| `FAIL` | real HTTP 5xx observed. The service is genuinely still broken. |

On a healthy baseline you may legitimately see either `5 passed, 0 warned` or
`4 passed, 1 warned`, depending only on whether an Azure Monitor alert has
finished resolving from an earlier trigger. That can take up to ~13 minutes
for the canary alert and is outside your control.

Recovery is proven strictly: both scenes require a fresh post-remediation
checkout batch with **zero** HTTP 5xx, which is stricter than the alert
condition that declared the incident. Application Insights sampling is
disabled for the workload, so the telemetry counts are complete rather than
estimated.

## Agent data-plane content

`labctl provision` applies the contents of `agent/` — knowledge documents, a
skill, subagents, safety hooks, common prompts, a scheduled task, the incident
platform binding, a response plan, and the GitHub source connection.

`labctl deploy` calls `provision` automatically as one of its own steps, so you
do not need to run it separately after a normal deploy. It remains safe and
idempotent to run on its own whenever `agent/` content changes.

`verify` and `status` read this content back **live** from the agent data plane
and the ARM resource — never from the last `provision` run's reported success.

GitHub source access uses your existing `gh auth token` as a Personal Access
Token, which is fully automated as long as `gh auth login` has been run
(checked by `preflight`). The official template's browser-based OAuth flow is
only needed as a fallback when a PAT is unavailable; see `PLAN.md` Milestone 4
for the detection and fallback path.

### Known platform behavior

`terraform apply` resets the agent's `incidentManagementConfiguration` to
`null` on every apply, even one that changes an unrelated property. `deploy`
reconciles it immediately afterwards. See
[`docs/adr/0001-incident-platform-reconciliation.md`](docs/adr/0001-incident-platform-reconciliation.md).

## Development

```powershell
# labctl
cd labctl
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format . --check
.\.venv\Scripts\python -m mypy src

# application
cd ..\app
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest

# repository-wide
cd ..
.\labctl\.venv\Scripts\python -m pytest tests scenarios

# Terraform, without touching Azure
terraform -chdir=infra/environments/demo fmt -check -recursive -diff
terraform -chdir=infra/environments/demo init -input=false -backend=false
terraform -chdir=infra/environments/demo validate

# presenter HTML: links, contrast, keyboard navigation, theming
python docs/tools/validate.py
node docs/tools/validate.mjs
```

`validate.mjs` needs the dependencies in `docs/tools/package.json`
(`cd docs/tools && npm install` once).

Never run raw `terraform apply` or `terraform destroy` against this
configuration. They run without `labctl`'s variable wiring and will revert the
ownership tags that `destroy` relies on to prove what it is allowed to delete.

## Cleanup and cost

> **Cost:** a deployed Azure SRE Agent bills Azure Agent Units continuously
> from creation until deletion, whether or not it is investigating anything.
> Destroy the environment when you are not rehearsing.

Terraform state stays local under `.state/` (git-ignored), alongside `labctl`'s
own non-secret deployment metadata such as the image tag, baseline revision,
and generated `.tfvars.json`.

`labctl destroy` is the normal end of every rehearsal. It:

1. verifies all four resource-group ownership tags,
2. verifies the exact resource-group IDs against Terraform state,
3. enumerates child resources and **refuses to proceed** on anything it does
   not recognize as owned by this deployment,
4. warns about the always-on agent cost,
5. applies the destroy plan you just reviewed,
6. and confirms both resource groups are actually gone before exiting 0.

Overriding the unrecognized-resource check requires typing the resource-group
name, even with `--yes`.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `az` commands fail with "Please run 'az login'" | Your CLI session expired. Run `az login`, then `az account set --subscription <id>`. |
| `deploy` stalls on connector provisioning | Expected; connectors are documented to take 10-30 minutes. `deploy` polls to a bounded deadline. |
| A scene's incident reuses an old thread | Incident threads merge within a ~3 hour window and a merged thread will not re-run the investigation. Wait, or temporarily disable merging on the response plan. |
| `demo verify` reports `WARN` on `alert-not-firing` | The alert is still resolving. Non-fatal; wait and re-run. |
| `az acr build` crashes with a colorama error on Windows | Known Azure CLI issue. Pass `--no-logs`. |

More detail, including presenter-facing fallbacks, is in the
[presenter guide](docs/guide/index.html).
