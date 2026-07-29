Follow the `checkout-500-runbook` operational knowledge document step by
step:

1. Confirm scope: check `GET /healthz` is healthy and quantify the
   `POST /api/checkout` failure rate and window from Application Insights.
2. Correlate with the deployment: identify the Container App revision
   currently carrying traffic, its creation time, and whether it has
   `DEMO_FAILURE_MODE=checkout-500` set.
3. Confirm root cause: inspect the failed `checkout` operation's
   `inventory.check` and `payment.charge` dependency spans in Application
   Insights, and cross-reference `app/pulsemart/main.py` and
   `app/pulsemart/settings.py` in the connected GitHub repository.
4. Recommend remediation: identify the most recent known-good revision and
   recommend shifting production traffic back to it. Never recommend a
   restart, scale, or delete operation for this failure mode.
5. Report findings using the `investigation-report-template` operational
   knowledge document, citing the specific evidence for every claim.
