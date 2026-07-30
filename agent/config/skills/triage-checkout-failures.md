Follow the `checkout-500-runbook` operational knowledge document as a
diagnostic method, not as a preselected answer:

0. Use only current operational knowledge, live Azure resource state, live
   telemetry, and connected source files that match observed evidence. Ignore
   legacy workspace memory files from earlier rehearsals, especially
   `memory:deployment.md`, `memory:architecture.md`, `memory:logs.md`, and
   `memory:debugging.md`; they are retained by the preview service but are not
   current evidence for this run.
1. Start from the fired Azure Monitor alert and determine the affected operation
   from Application Insights `requests`. Confirm whether `POST /api/checkout`
   is the failing endpoint and quantify the first failed timestamp, successful
   request count, failed request count, failure rate, and result codes.
2. Confirm service scope: check `GET /healthz`, `GET /api/status`, active
   revisions, release, and traffic split so you can distinguish a total checkout
   outage from a partial canary degradation.
3. Partition telemetry by Container App revision before naming a root cause.
   Group `requests`, dependency spans, exceptions, and console logs by
   `cloud_RoleInstance`, `customDimensions["service.revision"]`, and
   `customDimensions["service.instance.id"]`. State per-revision totals,
   failures, and failure rates; do not average away a bad canary behind a
   healthy baseline.
4. Compare each traffic-carrying revision with the healthy revision. Diff image,
   creation time, traffic weight, health state, and non-secret environment
   variables.
5. Inspect failed checkout traces, dependency spans, exceptions, and correlated
   console logs. Identify whether the first failing component is pricing,
   inventory, payment authorization, or the request handler.
6. Consult connected source only to explain evidence you have already observed.
   If source content conflicts with live telemetry or the deployed revision's
   configuration, call that out as stale and do not use it as the basis for the
   root cause. Cite the exact source path and function only when it matches the
   current evidence.
7. Recommend the minimum safe remediation only after the evidence supports it:
   drain a failing canary to 0% when the stable revision is healthy, or shift
   all traffic to the last known-good revision when the failing revision has
   100% traffic. Never recommend restart, scale, delete, or source patch as the
   incident mitigation for this scenario.
8. Report findings using the `investigation-report-template` operational
   knowledge document, citing the specific evidence for every claim.
