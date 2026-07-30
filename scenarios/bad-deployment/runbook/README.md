# Runbook: bad-deployment

Presenter-operated steps for the "bad deployment" incident scenario (see
`../scenario.yaml` for tunable numbers and SPEC.md sections 5 and 11 for the
scene-by-scene narrative this implements). This is control content for
running the demo, not the audience-facing slide deck or HTML guide (those
live under `docs/` and are owned separately).

## Prerequisites

- `labctl deploy --yes` has completed at least once (Milestones 1-3).
- `labctl provision` has completed at least once (Milestone 4).
- `labctl verify` reports no FAIL rows.
- You are running from the repository root in PowerShell:
  `& 'labctl\.venv\Scripts\labctl.exe' <command>`.

## Step 1 — Observe (healthy baseline)

```powershell
labctl demo list
labctl demo prepare bad-deployment
```

`prepare` confirms (and restores, if needed) 100% traffic on the known-good
baseline revision, warms `/healthz` and `/api/checkout`, and prints the exact
revision currently serving traffic. Show the presenter the Container App
portal link from `labctl status` and a successful checkout in the browser.

## Step 2 — Disrupt

```powershell
labctl demo trigger bad-deployment
```

This creates a new immutable revision from the same image with
an altered payment-gateway profile, shifts 100% of traffic to it, drives
bounded synthetic checkout load, and polls the real
`alert-pulsemart-containerapp-5xx` metric alert for a Fired transition (honest
expected window: 1-6 minutes, since the rule evaluates every 1 minute over a
trailing 5-minute window).
`trigger` prints the exact revision name, traffic change, and load statistics
it produced, and never fails silently if the alert has not fired within the
bounded deadline — it reports what it actually observed and continues.

## Step 3 — Investigate

Open the Azure SRE Agent portal (`labctl status` prints the deep link) →
Incidents, or run:

```powershell
labctl demo verify bad-deployment
```

while the fault is active. This confirms checkout is failing, traffic is on
the fault revision, and reports the most recent matching incident thread (if
any) with its status. Narrate the agent's real investigation output — do not
paraphrase from memory; read the actual thread transcript on screen.

## Step 4 — Act (agent-executed remediation, Autonomous mode)

**The agent itself performs the real rollback.** Product-owner decision,
2026-07-30 (see SPEC.md section 5 Scene 5 and PLAN.md Milestone 5 for the
full evidence trail): live testing across three independent cycles proved
that this preview build's Review-mode Approve/Deny gate does not visibly
engage before a mutating `az containerapp ingress traffic set` executes --
`GET /api/v1/approvals/{threadId}` stayed empty throughout, and the write
landed in the Azure Activity Log seconds after the tool call, with nobody
clicking anything, even on a freshly created thread confirmed
`agentMode: Review` and after removing the agent UAMI's "SRE Agent
Administrator" role. Rather than continue to describe a Review-mode gate
that does not work, the `containerapp-5xx` response plan is now honestly
configured `agentMode: Autonomous`
(`agent/automations/incident-filters/checkout-5xx.yaml`), and
`rollback-advisor` holds `RunAzCliWriteCommands` again
(`agent/config/subagents/rollback-advisor.yaml`). **Do not click an
"Approve" button expecting it to gate anything — none currently exists that
reliably does, and this scenario no longer pretends otherwise.**

Watch the incident thread (portal, or `labctl demo verify bad-deployment`)
for `rollback-advisor`'s messages: it states the exact
`az containerapp ingress traffic set` command it is about to run, executes
it for real under its own managed identity, then verifies and reports
recovery. Narrate this explicitly: the agent decided, stated its intent, and
acted — your role in this beat is to narrate, not to execute anything.

The real, demonstrable governance control is TOOL SCOPING, not a Review-mode
click:

- `incident-investigator` has no `RunAzCliWriteCommands` tool at all and is
  structurally incapable of mutating anything (`agent/config/subagents/
  incident-investigator.yaml`) — only `rollback-advisor` can write.
- `rollback-advisor`'s managed identity holds "Container Apps Contributor"
  scoped to just the `ca-pulsemart-demo` Container App resource, not
  Contributor over the resource group (`infra/modules/sre_agent`'s
  `workload_access_level = "narrow"`). A write attempted against any other
  resource in `rg-sre-agent-workload-demo` fails with `AuthorizationFailed`
  regardless of what the model decides to try — see PLAN.md Milestone 5 for
  a live-captured example of this actually happening.

Immediately after the rollback, independently confirm the change was made by
the agent's own identity — never trust the agent's self-reported narrative
alone:

```powershell
labctl status
```

Then check the Azure Activity Log for `rg-sre-agent-workload-demo` yourself
(portal, or `az monitor activity-log list`) for a
`Microsoft.App/containerApps/write` entry whose `caller` is the agent
UAMI's principal ID (`labctl status` prints it), not your own account and
not `labctl`'s.

## Step 5 — Verify recovery

```powershell
labctl demo verify bad-deployment
```

Confirms checkout returns HTTP 200, traffic is back on the baseline revision,
and the failure rate is below threshold. Exit code 0 means recovery is
proven from both the user and telemetry perspective — this is the same
check regardless of who or what performed the traffic shift.

## Step 6 — Learn

```powershell
labctl evidence collect
```

Saves a redacted evidence bundle (alert state history, incident thread and
messages, revision/traffic history, telemetry snapshots) under
`.evidence/<timestamp>/` for the audit-trail beat. This bundle is now the
record of what the agent actually did, not a record of a presenter-run
mitigation — call this out explicitly.

## Reset (the operator safety net, not the demo's mitigation step)

```powershell
labctl demo reset bad-deployment
```

Restores 100% traffic to the baseline revision regardless of current state
(safe to run even if nothing is broken) and verifies recovery. **This is no
longer the demo's Act beat** — the agent already performed the real
mitigation in Step 4. `reset` remains the reliable operator safety net for
returning to a known baseline (for example if the agent's rollback attempt
fails, if you need to abandon a rehearsal early, or before ending the
session) and for repeat-run idempotency. Re-run `labctl demo trigger
bad-deployment` afterward to rehearse the scene again; every step above is
idempotent.

## Fallback paths

- If the alert does not fire within `alert.max_wait_seconds`, `demo trigger`
  still exits 0 as long as the checkout requests themselves failed (the fault
  is genuinely live); re-run `labctl demo verify bad-deployment` a few
  minutes later, or drive more load with another `labctl demo trigger
  bad-deployment` (idempotent — reuses the existing fault revision).
- If the agent's investigation or remediation message never appears, or the
  incident thread stays stuck at `investigationStatus: Complete`/`resolved`
  from an earlier rehearsal: incidents merge into the same thread for any
  alert firing within 3 hours of the previous one (`mergeWindowHours: 3` on
  the `containerapp-5xx` response plan), and a merged/reactivated thread does
  **not** re-run automated investigation once it has already completed one —
  live-verified 2026-07-29. Rehearsing this scenario more than once inside a
  3-hour window is expected to reuse the same thread and may not show fresh
  investigation/remediation narration each time; the fault/recovery
  mechanics themselves are unaffected (`labctl demo trigger`/`reset` never
  depend on the agent). If the agent has not executed the rollback within a
  few minutes of a clear investigation conclusion, run `labctl demo reset
  bad-deployment` yourself as the safety net and narrate that explicitly as
  a fallback, not as the intended path.
- To independently confirm the rollback write was made by the agent's own
  identity and not by you or by `labctl`, poll the Azure Activity Log for
  `rg-sre-agent-workload-demo` (`Microsoft.App/containerApps/write`) and
  compare the `caller` field against the agent UAMI's principal ID from
  `labctl status` — see PLAN.md Milestone 5 for why this check matters more
  than the agent's own narrative text.
- No portal "Approve" click is needed or expected for this scenario's Act
  step; the agent executes the rollback itself (see Step 4).
