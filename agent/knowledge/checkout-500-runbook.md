# Runbook: PulseMart checkout returning HTTP 500

Use this runbook whenever the `alert-pulsemart-containerapp-5xx` or
`alert-pulsemart-canary-regression` Azure Monitor alert fires, or whenever
telemetry otherwise shows `POST /api/checkout` returning HTTP 500 on
`ca-pulsemart-demo`.

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
4. Record the first failed checkout timestamp, total failed requests, total
   successful requests, and failure rate. If successes and failures are mixed,
   treat the incident as a partial degradation until revision-level evidence
   proves otherwise.

## 2. Compare the active revision with the last healthy revision

1. List Container App revisions and their traffic weights (`az containerapp
   revision list`, `az containerapp ingress traffic show`, or equivalent
   read-only Azure Resource Graph queries). PulseMart runs in Multiple revision
   mode, so one or more immutable revisions can carry production traffic.
2. If multiple revisions have nonzero traffic, partition Application Insights
   `requests`, dependency spans, exceptions, and console logs by revision before
   choosing a mitigation. Use `cloud_RoleInstance`,
   `customDimensions["service.revision"]`, and
   `customDimensions["service.instance.id"]` to map telemetry to revision
   suffix/name. State the request counts, failure counts, and failure rates for
   each revision separately.
3. Quantify blast radius from both sources of evidence: the configured traffic
   weight for the suspect revision and the observed share of failed/total
   checkout requests in telemetry.
4. Identify the revision currently carrying failing traffic and its creation
   timestamp. Compare that timestamp with the first failed checkout request.
5. Identify the healthy revision that should receive traffic after mitigation.
   Treat it as the known-good candidate only if it is still provisioned,
   healthy, and its recent checkout telemetry is successful.
6. Diff the suspect and known-good revisions' observable configuration: image,
   revision suffix, traffic weight, health state, and non-secret environment
   variables. A configuration difference on the failing revision that aligns
   with the first failure timestamp is the leading deployment-regression
   hypothesis.

## 3. Confirm root cause from telemetry and source

1. In Application Insights, inspect failed checkout operations and their
   dependency spans. Determine whether `pricing.quote`, `inventory.check`,
   `payment.charge`, or the request handler failed first.
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

1. Choose the minimum traffic change that removes the failing revision from
   production:
   - If a canary or partial rollout has one failing revision and one healthy
     revision, drain only the failing canary (`<bad-revision>=0`) and restore
     the healthy revision to 100%.
   - If all production traffic is on one failing revision, shift 100% of ingress
     traffic back to the most recent known-good revision.
   Do not recommend restarting, scaling, or deleting either revision: these
   scenarios are designed to be reversible through traffic weights, not through
   resource mutation.
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
   revision and 0% on the drained suspect revision.
2. Call `POST /api/checkout` (or query recent Application Insights `requests`)
   and confirm HTTP 200 responses resume.
3. Confirm the `alert-pulsemart-containerapp-5xx` alert transitions out of
   Fired, or that recent telemetry no longer shows 5xx responses within its
   evaluation window.
4. Summarize the incident: root cause, evidence, the action taken, and the
   verified recovery signal. Use the investigation and remediation report
   templates for this summary.
