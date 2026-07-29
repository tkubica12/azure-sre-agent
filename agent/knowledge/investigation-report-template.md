# Template: PulseMart incident investigation report

Use this structure when reporting findings for a PulseMart checkout
incident (see `checkout-500-runbook.md`). Keep every claim tied to a
specific piece of evidence; do not state a root cause that is not backed by
at least one of Application Insights, Log Analytics, Azure Monitor, or the
connected GitHub source.

## Summary

- **Incident:** one sentence describing user-visible impact (e.g. "Checkout
  requests to PulseMart are failing with HTTP 500").
- **Detected by:** the alert or signal that started the investigation
  (e.g. `alert-pulsemart-checkout-5xx`, fired at `<timestamp>`).
- **Affected scope:** which endpoint(s), which Container App revision(s),
  what fraction of traffic.

## Timeline

- First failed request observed: `<timestamp>`, source (Application
  Insights query used).
- Suspect revision created: `<timestamp>`, revision name.
- Alert fired: `<timestamp>`.

## Evidence

List each piece of evidence with its source:

- Application Insights: failure rate, operation name, exception message and
  stack (if any), dependency span outcome (`inventory.check`,
  `payment.charge`).
- Log Analytics: any correlated `ContainerAppConsoleLogs_CL` rows.
- Azure resource state: active revision(s) and traffic split, relevant
  environment variables (e.g. `DEMO_FAILURE_MODE`).
- Source: the exact code path in `app/pulsemart/main.py` /
  `app/pulsemart/settings.py` that produces the observed failure.

## Root cause hypothesis

State the hypothesis in one or two sentences, referencing the evidence
above by item number or timestamp. Note your confidence level and what,
if anything, would raise or lower it.

## Recommended remediation

- The specific, minimal action recommended (traffic shift target revision,
  expected effect).
- Why this action is expected to resolve the incident without introducing a
  new one.
- Confirmation that the recommended action is not a delete, and does not
  target a resource containing "prod"/"prd" in its name (see
  `deny-destructive-deletes` hook).
- State the execution mode plainly: this response plan runs in Autonomous
  mode, so the action will be executed by the agent's own managed identity
  without a human approval step. Do not state that approval is required or
  that approval was obtained.
