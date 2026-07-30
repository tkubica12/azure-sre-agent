# Runbook: canary-regression

Presenter-operated steps for the optional canary-regression scene. This is
scenario control content; audience-facing presenter content lives outside this
tree.

## Prerequisites

- `labctl deploy --yes` and `labctl provision` have completed after the latest
  code and agent-content changes.
- `labctl verify` and `labctl demo verify bad-deployment` report zero failures.
- You are running from the repository root in PowerShell:
  `& 'labctl\.venv\Scripts\labctl.exe' <command>`.

## Step 1 — Prepare

```powershell
& 'labctl\.venv\Scripts\labctl.exe' demo prepare canary-regression
```

This restores 100% traffic to the recorded baseline revision and proves
`/healthz` plus `/api/checkout` are healthy before any canary traffic is added.

## Step 2 — Trigger

```powershell
& 'labctl\.venv\Scripts\labctl.exe' demo trigger canary-regression
```

`trigger` creates an immutable canary revision from the current baseline image
with `CHECKOUT_PRICING_PROFILE=strict-decimal`, shifts 10% of ingress traffic to
that revision and leaves 90% on the stable baseline, then sustains mixed
checkout traffic while the real `alert-pulsemart-canary-regression` scheduled
query alert evaluates.

The checkout response is intentionally ambiguous during this stage: most
requests should still return HTTP 200 because most traffic remains on the
stable revision.

## Step 3 — Investigate and act

Open the Azure SRE Agent incident thread from `labctl status`. The agent should:

1. Treat the issue as partial degradation, not total outage.
2. Query Application Insights grouped by Container App revision.
3. Show failures concentrated on the canary revision while the baseline remains
   healthy.
4. Quantify blast radius using the 10% traffic split and observed request
   counts.
5. Use `rollback-advisor` to run a targeted traffic drain:
   `az containerapp ingress traffic set --name ca-pulsemart-demo --resource-group rg-sre-agent-workload-demo --revision-weight <baseline>=100 <canary>=0`.

The scene is successful only if the agent, not the presenter, performs the
write under its managed identity.

## Step 4 — Verify recovery

```powershell
& 'labctl\.venv\Scripts\labctl.exe' demo verify canary-regression
```

This command fails while the canary still receives traffic. It passes only after
traffic is back to 100% on the baseline, a fresh checkout batch succeeds, recent
Application Insights request telemetry for the baseline revision is present,
and the matching Azure Monitor alert is no longer Fired.

## Reset

```powershell
& 'labctl\.venv\Scripts\labctl.exe' demo reset canary-regression
```

Safe to run repeatedly. It restores 100% traffic to the recorded baseline and
keeps the canary revision drained.
