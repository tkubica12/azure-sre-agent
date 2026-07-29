# Runbook: PulseMart checkout returning HTTP 500

Use this runbook whenever the `alert-pulsemart-checkout-5xx` Azure Monitor
alert fires, or whenever telemetry otherwise shows `POST /api/checkout`
returning HTTP 500 on `ca-pulsemart-demo`.

## 1. Confirm scope

1. Call `GET /healthz` on the Container App's FQDN. It must return HTTP 200.
   If it does not, this is not the checkout-500 scenario -- escalate as a
   broader outage instead of following this runbook.
2. Call `GET /api/status`. Record `revision` and `release`.
3. Query Application Insights `requests` for `ca-pulsemart-demo` over the
   last 15 minutes, filtered to `operation_Name == "POST /api/checkout"` and
   `success == false`. Confirm the failure rate and first-seen timestamp.

## 2. Correlate with the deployment

1. List Container App revisions and their traffic weights
   (`az containerapp revision list`, or the equivalent read-only Azure
   Monitor/Resource Graph query). PulseMart runs in Multiple revision mode:
   more than one revision can be provisioned at once, but only one normally
   carries production traffic.
2. Identify the revision currently carrying traffic and its creation
   timestamp. A revision created shortly before the first failed request is
   the leading suspect.
3. Check that revision's environment variables for
   `DEMO_FAILURE_MODE=checkout-500`. This is the deterministic, documented
   cause of every checkout HTTP 500 in this environment (see
   `architecture.md`) -- no other configuration or code path produces this
   failure.

## 3. Confirm root cause from telemetry and source

1. In Application Insights, inspect a failed `checkout` operation's
   dependency spans. Expect `inventory.check` to succeed and `payment.charge`
   to fail with an exception whose message contains "payment gateway
   returned an unexpected error (demo failure mode: checkout-500)".
2. Cross-reference `app/pulsemart/main.py` (`_charge_payment`) and
   `app/pulsemart/settings.py` (`FAILURE_MODE_CHECKOUT_500`) in the connected
   GitHub repository to confirm this is the only code path that raises
   `CheckoutFailure`.
3. Do not treat this as a code bug to be patched. It is an intentionally
   injected, reversible configuration fault used to demonstrate the
   investigation and rollback flow; the correct remediation is a traffic
   rollback, not a source change.

## 4. Recommend remediation

1. Identify the most recent revision that was carrying 100% production
   traffic *before* the failing revision, and confirm (via `GET /api/status`
   against a revision-pinned URL, or the revision's own environment
   variables) that it does **not** have `DEMO_FAILURE_MODE` set.
2. Recommend shifting 100% of ingress traffic back to that known-good
   revision. Do not recommend restarting, scaling, or deleting either
   revision: the fault is a configuration difference between two revisions
   that are both otherwise healthy, not a resource-health problem.
3. Execute the traffic shift yourself via the `rollback-advisor` subagent.
   This response plan runs in Autonomous mode: no approval prompt will be
   presented, so do not wait for one and do not describe the change as
   approved. State the exact command you ran, the identity that ran it, and
   the resulting traffic split.

## 5. Verify recovery

After the traffic shift is applied:

1. Confirm the Container App's traffic split shows 100% on the known-good
   revision.
2. Call `POST /api/checkout` (or query recent Application Insights
   `requests`) and confirm HTTP 200 responses resume.
3. Confirm the `alert-pulsemart-checkout-5xx` alert transitions out of
   Fired, or that recent telemetry no longer shows 5xx responses within its
   evaluation window.
4. Summarize the incident: root cause, evidence, the action taken, and the
   verified recovery signal. Use the investigation and remediation report
   templates for this summary.
