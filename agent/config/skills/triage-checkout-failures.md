Follow the `checkout-500-runbook` operational knowledge document as a
diagnostic method, not as a preselected answer:

0. Use only current operational knowledge, live Azure resource state, live
   telemetry, and connected source files that match observed evidence. Ignore
   legacy workspace memory files from earlier rehearsals, especially
   `memory:deployment.md`, `memory:architecture.md`, `memory:logs.md`, and
   `memory:debugging.md`; they are retained by the preview service but are not
   current evidence for this run.
1. Start from the fired Container App 5xx alert and determine the affected
   operation from Application Insights `requests`. Confirm whether
   `POST /api/checkout` is the failing endpoint and quantify the first failed
   timestamp, volume, and result codes.
2. Confirm service scope: check `GET /healthz`, `GET /api/status`, active
   revision, release, and traffic split so you can distinguish a checkout
   regression from a broader outage.
3. Compare the traffic-carrying revision with the revision that served traffic
   immediately before failures began. Diff image, creation time, traffic
   weight, health state, and non-secret environment variables.
4. Inspect failed checkout traces, dependency spans, exceptions, and correlated
   console logs. Identify whether the first failing component is inventory,
   payment authorization, or the request handler.
5. Consult connected source only to explain evidence you have already observed.
   If source content conflicts with live telemetry or the deployed revision's
   configuration, call that out as stale and do not use it as the basis for the
   root cause. Cite the exact source path and function only when it matches the
   current evidence.
6. Recommend the minimum safe remediation only after the evidence supports it:
   shift traffic to the last known-good revision. Never recommend restart,
   scale, delete, or source patch as the incident mitigation for this scenario.
7. Report findings using the `investigation-report-template` operational
   knowledge document, citing the specific evidence for every claim.
