# Template: PulseMart remediation and recovery report

Complete this report only after a remediation action has been executed and
recovery has been independently verified (see `checkout-500-runbook.md`
section 5). Do not report recovery based on the action having been applied
alone -- both application behavior and telemetry must confirm it.

## Action taken

- **Action:** exact operation performed (e.g. "Shifted 100% ingress traffic
  on `ca-pulsemart-demo` from revision `<failing>` to revision
  `<known-good>`").
- **Execution mode:** Autonomous. This response plan executes without an
  approval prompt. Never record an approval here, and never state that one
  was obtained -- if you did not observe a human approve something, it did
  not happen.
- **Executed by:** the identity that actually performed the write (the
  agent's user-assigned managed identity), so the action can be matched to
  the Azure Activity Log.
- **Executed at:** `<timestamp>`.

## Recovery verification

- **Application-visible check:** result of calling `POST /api/checkout` (or
  equivalent) after the action, with the observed status code.
- **Traffic state:** confirmed traffic split after the action (must show
  100% on the known-good revision, or the intended target split).
- **Telemetry check:** most recent Application Insights `requests` for
  `POST /api/checkout` showing `success == true`, with timestamp.
- **Alert state:** whether `alert-pulsemart-checkout-5xx` has resolved, or
  the most recent evaluation window with no qualifying 5xx responses.

## Outcome

State plainly whether recovery is confirmed. If any of the checks above did
not pass, do not report the incident as resolved -- describe what remains
failing and what the next recommended step is.

## Follow-up / durable knowledge

Note anything worth carrying forward for next time: a new pattern to add to
`checkout-500-runbook.md`, a scheduled check that would have caught this
sooner, or an automation opportunity (see the `daily-reliability-summary`
scheduled task).
