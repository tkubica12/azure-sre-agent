# PulseMart architecture and service ownership

This document grounds the Azure SRE Agent's investigation of the PulseMart
demo workload. It is uploaded to agent memory (`AgentMemory`) by
`labctl provision` and is one of the sources the agent is expected to cite
during Scene 2 ("Grounded exploration") and Scene 4 ("Automated incident
investigation") of the demonstration (see SPEC.md sections 5 and 10).

## Service

PulseMart is a small synthetic Python FastAPI checkout service. It exposes:

- `GET /` - an HTML status/checkout dashboard for the presenter.
- `GET /healthz` - liveness probe. Always returns HTTP 200, even while the
  checkout journey is failing (see "Blast radius" below).
- `GET /api/status` - machine-readable release and revision status. It
  deliberately does not expose private dependency configuration.
- `POST /api/checkout` - the synthetic checkout journey. This is the only
  endpoint that can fail.

There is no endpoint that lets a caller toggle failure behavior. The only
way checkout starts failing is a real Container Apps revision change made by
an authenticated operator (`labctl demo trigger bad-deployment`, Milestone
5), never a runtime request.

## Checkout call graph

`POST /api/checkout` runs two internal dependency spans, in this order:

1. `inventory.check` (simulated inventory-service dependency). This step
   always succeeds; it exists so an operator can see that a checkout failure
   is isolated to payment processing, not a broad outage.
2. `payment.charge` (simulated payment-gateway dependency). This step
   can raise `UpstreamPaymentGatewayError` when the active Container Apps
   revision carries a payment-gateway configuration regression, modeling a bad
   deployment that broke payment processing.

When `payment.charge` fails, `POST /api/checkout` returns HTTP 500 with a
JSON body `{"order_id": "...", "status": "failed", "error": "..."}` and the
`checkout` span is marked with `otel.status_code=ERROR` and the exception
recorded on it.

## Azure resources (owning resource group: `rg-sre-agent-workload-demo`)

| Resource | Name | Role |
| --- | --- | --- |
| Container App | `ca-pulsemart-demo` | Runs the PulseMart image. Multiple revision mode: the known-good and any injected-failure revision run concurrently; only traffic weights change during a scenario. |
| Container Registry | (see `labctl status`, tagged `crpulsemartdemo*`) | Built by `az acr build`; the image tag is the Git commit plus a content hash, so every deployed revision is reproducible. |
| Application Insights | `appi-pulsemart-demo` | Requests, dependencies (`inventory.check`, `payment.charge`), traces, and exceptions for every checkout call. |
| Log Analytics workspace | `law-pulsemart-demo` | Container Apps platform/console logs (`ContainerAppConsoleLogs_CL`) and the Application Insights backing workspace. |
| Metric alert | `alert-pulsemart-containerapp-5xx` | Fires when the `Requests` metric on the Container App, filtered to `statusCodeCategory=5xx`, totals at least the configured threshold (see `workload.alert_threshold_5xx` in `config.local.toml`, default 3) inside a 5-minute window. Severity 2. It is intentionally a Container App 5xx signal; use Application Insights to determine the failing operation. |

## Deployment model and blast radius

- The Container App runs in Multiple revision mode. `labctl` (not
  Terraform) creates new immutable revisions and moves traffic weights
  between them; Terraform's lifecycle rule ignores template/traffic changes
  so it never fights an agent-approved rollback.
- A revision suffix and image tag together identify exactly what code and
  configuration is running (`ca-pulsemart-demo--<suffix>`); correlate the
  active revision from `GET /api/status` or the Container App's traffic
  split against the deployed image tag before concluding a deployment caused
  an incident.
- The bad-deployment scenario is expected to affect `POST /api/checkout` while
  `GET /healthz` and `GET /api/status` stay healthy, which is the fastest way
  to distinguish "checkout is broken" from "the whole service is down".
- Recovery is always a traffic-weight change back to the known-good
  revision, never a resource deletion, a scale-to-zero action, or a config
  edit to a still-serving revision.

## Source

The application source (`app/pulsemart/main.py`, `app/pulsemart/settings.py`,
`app/pulsemart/telemetry.py`) is connected as a GitHub repository source
(`tkubica12/azure-sre-agent`). Use it to explain how the observed revision
configuration difference changes the checkout call graph instead of guessing
from telemetry alone.
