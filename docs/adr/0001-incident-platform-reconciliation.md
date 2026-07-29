# 1. Reconcile the Azure SRE Agent incident platform in `labctl deploy`, not Terraform

## Context

The Azure SRE Agent's `properties.incidentManagementConfiguration` field
(which platform -- here, Azure Monitor -- delivers incidents to the agent)
cannot be set through the same `azapi_resource` PUT body that creates the
agent: the official Microsoft template sets it with a separate ARM PATCH
(`bicep/Apply-Extras.ps1`), and this repository originally did the same from
`labctl provision`, once, after `labctl deploy` created the agent.

Live testing (2026-07-29) proved that design was not repeatable: a second,
completely unrelated `terraform apply` (for example, only lowering
`monthlyAgentUnitLimit`) resets `incidentManagementConfiguration` back to
null. The `azapi_resource` provider issues a full PUT of the agent's entire
`properties` object on every apply that changes anything in `body`, and
`incidentManagementConfiguration` is not part of that `body` (it cannot be,
since ARM only accepts it through PATCH). A second `labctl deploy` therefore
silently broke alert routing with no error, which violates AGENTS.md's
"deployment and cleanup reliability" and "repeatable" requirements and
SPEC.md's claim that the demonstration reaches a "real Azure SRE Agent
workflow".

## Decision drivers

- The fix must make `labctl deploy` genuinely repeatable: running it twice
  must never regress a previously-working incident platform.
- Prefer Terraform as the single source of truth when it can actually do the
  job (AGENTS.md: "Terraform is the source of truth for Azure resources").
- Any Python-glue fallback must be idempotent, safe to run on every deploy,
  and must not race with another writer of the same field.

## Options considered

1. **Terraform owns it via `azapi_update_resource`.** This AzAPI provider
   resource is documented as managing "a subset of any existing resource's
   properties" through a separate call, decoupled from `azapi_resource`'s
   full-body PUT -- exactly what this field needs.
2. **`labctl deploy` PATCHes it directly**, unconditionally and
   idempotently, right after `terraform apply` succeeds (whether or not
   anything else changed), using the same `az rest --method patch` call
   `labctl provision` used to make once.
3. **`azapi_resource`'s `lifecycle.ignore_changes` / body merge semantics**
   to stop Terraform from ever touching `properties` wholesale. Rejected
   without a live trial: AzAPI's PUT-of-`body` behavior is a property of the
   resource type this demo already depends on for `experimentalSettings`,
   `monthlyAgentUnitLimit`, and connectors; suppressing drift on the whole
   `properties` tree would also suppress legitimate config drift detection
   for those fields, which this repository's validation gate explicitly
   checks (`labctl verify`'s `agent-configuration` check).

## What we tried and what happened

Option 1 was implemented first (an `azapi_update_resource.incident_platform`
resource depending on `azapi_resource.agent`) and exercised against the live
subscription. `terraform apply` failed with:

```text
Error: Failed to update resource
RESPONSE 400: 400 Bad Request
ERROR CODE: MismatchingResourceIdentityPrincipalId
"The principalId '<uami-principal-id>' on the resource's Identity property
is invalid and must be empty or match the existing principalId of '<null>'."
```

Despite being documented as a partial-property PATCH, `azapi_update_resource`
actually performs a **read-then-merge-then-PUT**: it reads the current
resource (including its `identity` block, whose `principalId` fields are
ARM-computed and read-only), merges the requested `body` into that read
copy, and PUTs the merged result back. The merged PUT echoed back the
agent's own identity `principalId`, which ARM rejects on write. This is a
real behavior of the resource type as deployed in this subscription/API
version (`2025-05-01-preview`), not a configuration mistake in this
repository's use of it, and it is not mentioned in the AzAPI provider's own
documentation for `azapi_update_resource`.

## Decision

**Option 2**: `labctl deploy` reconciles the incident platform itself, via a
direct ARM PATCH (`az rest --method patch`, not a Terraform resource),
immediately after `terraform apply` succeeds (see
`labctl/src/labctl/deploy.py`'s `_reconcile_incident_platform` and
`labctl/src/labctl/agent_azure.py`'s `set_incident_platform`). The call is a
GET-then-conditional-PATCH: if `properties.incidentManagementConfiguration.type`
already matches the desired platform, nothing is sent; otherwise a real PATCH
is issued and the exit code reflects whether it succeeded. This makes it:

- **Idempotent**: safe on every `labctl deploy` run, including a repeat
  deploy where nothing else changed.
- **Self-healing**: if any future Terraform change resets the field again
  (the underlying `azapi_resource` PUT behavior has not changed), the very
  next `labctl deploy` puts it back automatically -- satisfying "have deploy
  call the provisioning reconciliation automatically" from AGENTS.md's
  repeatability requirement.
- **Single-writer**: `labctl provision` no longer PATCHes this field. It
  only reads it back (with a short bounded retry, since the platform can
  still be initializing moments after a fresh PATCH) to confirm `labctl
  deploy` already configured it correctly, before it PUTs the response plan
  that depends on the platform being ready.

## Consequences

- `infra/modules/sre_agent` does not manage
  `incidentManagementConfiguration` at all; this is intentional and
  documented in `main.tf`'s comment above where the field would otherwise
  appear, so a future contributor does not re-attempt option 1 without
  reading this ADR first.
- `labctl deploy`'s step numbering grew from 8 to 9 steps to make this an
  explicit, visible phase of every deploy, not a hidden side effect.
- If Azure SRE Agent's ARM API ever adds a genuine partial-PATCH mechanism
  usable from Terraform (or `azapi_update_resource`'s read-merge-PUT
  behavior is fixed upstream to not echo back read-only identity fields),
  revisit this decision; option 1 remains architecturally preferable if it
  can be made to work.

## Validation

- Live-reproduced the `MismatchingResourceIdentityPrincipalId` failure with
  option 1 (2026-07-29) against subscription `tokubica`,
  `rg-sre-agent-demo`.
- Live-verified option 2: `labctl deploy --yes` followed immediately by a
  second `labctl deploy --yes` (idempotent no-op on the PATCH), then `labctl
  verify` confirming `incidentManagementConfiguration.type=AzMonitor` both
  times. See the top-level task's final report for the exact command output.

## Revisit triggers

- Azure SRE Agent's ARM API version changes (`2025-05-01-preview` is
  pinned; re-verify this decision against any newer stable API version).
- The AzAPI provider changes `azapi_update_resource`'s PUT-merge behavior.
- This demo adds a second incident platform (PagerDuty/ServiceNow) that
  needs a `connectionKey` secret; the PATCH-based approach in
  `labctl/src/labctl/agent_azure.py` already supports that parameter and
  should be extended there, not by revisiting Terraform ownership.
