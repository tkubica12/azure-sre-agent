# Runbook: PulseMart checkout returning HTTP 500

Use this runbook whenever the `alert-pulsemart-containerapp-5xx` Azure Monitor
alert fires, or whenever telemetry otherwise shows `POST /api/checkout`
returning HTTP 500 on `ca-pulsemart-demo`.

## 1. Confirm the affected operation

1. Call `GET /healthz` on the Container App's FQDN. It should return HTTP 200.
   If it does not, escalate as a broader service outage instead of assuming a
   checkout-only incident.
2. Call `GET /api/status`. Record `revision` and `release`; do not expect this
   endpoint to disclose the cause.
3. Query Application Insights `requests` for `ca-pulsemart-demo` over the last
   15 minutes. Group by operation name and result code so the fired Container
   App 5xx alert is tied to the actual failing endpoint. Continue this runbook
   only if `POST /api/checkout` is the failing operation.
4. Record the first failed checkout timestamp, total failed requests, and
   failure rate.

## 2. Compare the active revision with the last healthy revision

1. List Container App revisions and their traffic weights (`az containerapp
   revision list`, or the equivalent read-only Azure Resource Graph query).
   PulseMart runs in Multiple revision mode: more than one revision can be
   provisioned at once, but only one normally carries production traffic.
2. Identify the revision currently carrying traffic and its creation timestamp.
   Compare that timestamp with the first failed checkout request.
3. Identify the revision that carried production traffic immediately before the
   failures began. Treat it as the last known-good candidate only if it is still
   provisioned, healthy, and has the same workload image/release expected for
   this scenario.
4. Diff the two revisions' observable configuration: image, revision suffix,
   traffic weight, health state, and non-secret environment variables. A
   configuration difference on the traffic-carrying revision that aligns with
   the first failure timestamp is the leading deployment-regression hypothesis.

## 3. Confirm root cause from telemetry and source

1. In Application Insights, inspect failed checkout operations and their
   dependency spans. Determine whether `inventory.check`, `payment.charge`, or
   the request handler failed first.
2. Inspect exception telemetry and correlated `ContainerAppConsoleLogs_CL`
   records. Quote the observed exception type/message exactly.
3. Cross-reference the connected GitHub source for `app/pulsemart/main.py` and
   `app/pulsemart/settings.py`. Use source to explain how the configuration
   difference found in step 2 changes the checkout payment path. Do not infer a
   source patch unless telemetry and source both show that rollback cannot
   restore the service.
4. State confidence. High confidence requires: failing endpoint identified from
   telemetry, active revision and first failure timestamps correlated, revision
   configuration difference identified, and source confirming that difference
   can produce the observed payment error.

## 4. Recommend remediation

1. Recommend shifting 100% of ingress traffic back to the most recent
   known-good revision. Do not recommend restarting, scaling, or deleting
   either revision: this scenario is designed to be reversible through traffic
   weights, not through resource mutation.
2. Do not patch source or edit environment variables in-place during the
   incident. A new source fix can be tracked later only after service recovery
   is proven.
3. Execute the traffic shift yourself via the `rollback-advisor` subagent. This
   response plan runs in Autonomous mode: no approval prompt will be presented,
   so do not wait for one and do not describe the change as approved. State the
   exact command you ran, the identity that ran it, and the resulting traffic
   split.

## 5. Verify recovery

After the traffic shift is applied:

1. Confirm the Container App's traffic split shows 100% on the known-good
   revision.
2. Call `POST /api/checkout` (or query recent Application Insights `requests`)
   and confirm HTTP 200 responses resume.
3. Confirm the `alert-pulsemart-containerapp-5xx` alert transitions out of
   Fired, or that recent telemetry no longer shows 5xx responses within its
   evaluation window.
4. Summarize the incident: root cause, evidence, the action taken, and the
   verified recovery signal. Use the investigation and remediation report
   templates for this summary.
