# Canary-regression live transcript and evidence (2026-07-30)

Captured from the real Azure SRE Agent data-plane API
(`GET /api/v1/threads/{id}/messages`), `labctl`, and Azure Activity Log.
GUIDs, subscription and tenant IDs, principal IDs, hostnames, ACR names, and
emails are redacted.

- Incident thread: `<incident-thread-id>`
- Alert: `alert-pulsemart-canary-regression`
- Fault revision: `ca-pulsemart-demo--canary-1785376425`
- Baseline revision: `ca-pulsemart-demo--baseline-9da87cbfde0d-e0574d14afc7`
- Alert fired: `2026-07-30T01:56:25.5091412Z`
- Alert resolved: `2026-07-30T02:17:24.8131261Z`

## Timeline observed

- Trigger -> alert Fired: 133 s (`labctl demo trigger`).
- Alert Fired -> incident thread: 79 s.
- Thread -> investigation report: 338 s.
- Investigation report -> traffic-drain write: 62 s.
- Traffic-drain write -> agent resolution summary: 128 s.
- Traffic-drain write -> alert auto-resolved: 781 s.
- Total trigger -> agent traffic-drain write: 586 s.

## `labctl demo trigger canary-regression`

```text
Scenario: Canary regression: partial checkout failures by revision
[1/4] Creating fault revision 'ca-pulsemart-demo--canary-1785376425' from the baseline image.
[2/4] Setting traffic split: 'ca-pulsemart-demo--baseline-9da87cbfde0d-e0574d14afc7'=90%, 'ca-pulsemart-demo--canary-1785376425'=10%.
  sampled mixed-traffic checkout returned 200 (expected to be ambiguous with only 10% on the canary).
[3/4] Generating sustained synthetic checkout load (duration=360s, concurrency=4).
[4/4] Polling the real alert 'alert-pulsemart-canary-regression' for up to 600s.
  Alert 'alert-pulsemart-canary-regression' entered Fired state after 133s; continuing sustained traffic.
  240 requests in 358.8s: 215 succeeded, 25 failed (5xx/4xx), 0 transport errors.
```

## Verbatim agent evidence

### Alert received

```markdown
```incident-alert
{"alertId":"<guid>","alertRule":"alert-pulsemart-canary-regression","description":"PulseMart checkout failure rate is elevated during a canary release; partition failures by Container App revision before acting.","monitoredResource":"appi-pulsemart-demo","severity":"Sev2","monitorCondition":"Fired","monitorService":"Log Alerts V2","firedAt":"07/30/2026 01:56:25 +00:00","subscription":"<subscription-id>","resourceGroup":"rg-sre-agent-workload-demo","portalUrl":"https://ms.portal.azure.com/.../<redacted>"}
```
```

### Partial degradation and revision attribution

```markdown
Telemetry is clear — all errors come from the canary revision. The `az rest`
calls hit the known "Unknown error" issue. Let me try alternative approaches to
get revision details, and query per-revision failure rates from AppRequests
using `cloud_RoleInstance`.
```

```markdown
Revision data confirmed. Now I have the full picture: the canary at 10% has
`CHECKOUT_PRICING_PROFILE=strict-decimal` and is failing 100% of checkouts. Let
me find the app source code in the connected repo to confirm the failure
mechanism.
```

### Investigation report and blast radius

```markdown
## Investigation Report: PulseMart Canary Checkout Regression

### Scope Confirmation

This is a **partial canary degradation**, not a total outage. The health endpoint
(`/healthz`) remains healthy on all revisions. Only `POST /api/checkout` is
affected, and only on the canary revision.

### Per-Revision Failure Breakdown

Evidence from `ContainerAppConsoleLogs_CL` (last 30 minutes):

| Revision | Total Requests | Failed | Succeeded | Failure Rate |
|---|---|---|---|---|
| `ca-pulsemart-demo--baseline-9da87cbfde0d-e0574d14afc7` | 340 | 0 | 340 | **0%** |
| `ca-pulsemart-demo--canary-1785376425` | 38 | 38 | 0 | **100%** |

Overall observed failure rate: ~7–12% per minute, consistent with the canary's
10% traffic weight.
```

```markdown
The canary revision deployed at 01:54 UTC with the problematic configuration is
causing 100% of its routed requests to fail. The fix is to drain the canary back
to 0% traffic and restore full traffic to the baseline revision that's working
correctly.
```

### Handoff and remediation

```markdown
Investigation complete. Handing off to the `rollback-advisor` subagent to drain
the failing canary.
```

```text
az containerapp ingress traffic set --name ca-pulsemart-demo
  --resource-group rg-sre-agent-workload-demo
  --subscription <subscription-id>
  --revision-weight
  ca-pulsemart-demo--baseline-9da87cbfde0d-e0574d14afc7=100
  ca-pulsemart-demo--canary-1785376425=0
```

### Resolution summary

```markdown
The rollback-advisor has successfully completed the remediation.

| Phase | Status |
|---|---|
| **Detection** | Alert `alert-pulsemart-canary-regression` fired at 01:56:25 UTC |
| **Investigation** | Canary revision `ca-pulsemart-demo--canary-1785376425` identified as 100% failing (38/38 checkouts) due to `CHECKOUT_PRICING_PROFILE=strict-decimal` configuration regression |
| **Remediation** | `rollback-advisor` drained canary to 0% traffic, restored baseline `ca-pulsemart-demo--baseline-9da87cbfde0d-e0574d14afc7` to 100% |
| **Verification** | Checkout confirmed healthy — `POST /api/checkout` returning HTTP 200 |

**Impact window**: ~12 minutes (01:54:00 – 02:06 UTC). During this window, ~10%
of checkout requests (38 observed) failed with HTTP 500. The baseline revision
serving 90% of traffic was never affected.
```

## Activity Log proof

```text
eventTimestamp       caller                       operation                         status
2026-07-30T01:54:22Z <operator-email-redacted>    Microsoft.App/containerApps/write Started
2026-07-30T01:54:23Z <operator-email-redacted>    Microsoft.App/containerApps/write Accepted
2026-07-30T02:04:23Z <agent-uami-principal-id>    Microsoft.App/containerApps/write Started
2026-07-30T02:04:23Z <agent-uami-principal-id>    Microsoft.App/containerApps/write Accepted
```

The `02:04:23Z` write is the targeted canary drain and was made by the Azure SRE
Agent user-assigned managed identity, not by the presenter.

## Independent verification

Final state after `labctl demo reset canary-regression` and repeated telemetry
ingestion checks:

```text
Phase: recovered (baseline weight=100%, traffic={'ca-pulsemart-demo--baseline-9da87cbfde0d-e0574d14afc7': 100})
[PASS] checkout-canary-batch         12 requests in 2.2s: 12 succeeded, 0 failed (5xx/4xx), 0 transport errors; every checkout returned HTTP <400.
[PASS] traffic-on-baseline-revision  ca-pulsemart-demo--baseline-9da87cbfde0d-e0574d14afc7=100%.
[PASS] rollback-timestamp-observed   latest successful Container App write at 2026-07-30T02:04:23.570368Z
[PASS] failure-rate-below-threshold  0 checkout 5xx request(s) across 7 checkout request(s) since the recovery proof started; alert threshold is 3.
[PASS] alert-not-firing              no matching Fired alert instance; observed condition(s): Resolved.
5 passed, 0 warned, 0 failed.
```

## Caveat observed

The deployed image was built from the local working tree for this validation
cycle, while the connected GitHub source still reflected the last committed
branch state. The agent explicitly noticed this source mismatch and still made
the correct decision from live telemetry and revision configuration. Presenter
content should mention that source-grounding is strongest after these changes
are committed and pushed.
