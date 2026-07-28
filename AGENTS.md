# Repository instructions

## Purpose

Build a polished, repeatable demonstration of Azure SRE Agent for professional
technical audiences. This repository contains a presenter-operated environment,
not student hands-on labs.

The demonstration must use real Azure resources and real Azure SRE Agent
capabilities. Do not substitute mocks, screenshots of unverified outcomes,
simulated agent responses, or theoretical workflows for a working deployment.

Optimize for:

- a compelling end-to-end incident story;
- deployment and cleanup reliability;
- observable evidence for every claim;
- simple local operation;
- safe, repeatable failure injection and recovery.

## Demonstration rhythm

Use this presentation flow:

1. **Orient:** Explain the workload, telemetry, agent scope, permissions, and
   safety model.
2. **Observe:** Show the healthy application and baseline telemetry.
3. **Disrupt:** Inject a controlled, reversible production-like fault.
4. **Investigate:** Let Azure SRE Agent correlate resources, logs, metrics,
   alerts, source, and operational knowledge.
5. **Act:** Review and approve a real mitigation or remediation.
6. **Verify:** Prove service recovery with automated and user-visible checks.
7. **Learn:** Show the incident record, audit evidence, durable knowledge, and
   automation opportunities.

Prefer one coherent service story over disconnected feature samples. Advanced
capabilities may be separate optional scenes only when they reuse the same
deployed environment.

## Repository layout

Use this structure:

```text
infra/
  modules/
  environments/demo/
app/
labctl/
  src/labctl/
  tests/
scenarios/
  <scenario-slug>/
    runbook/
    tests/
docs/
  slides/
  guide/
  assets/
  adr/
scripts/
tests/
```

- `infra/`: Terraform for all Azure infrastructure and agent resources.
- `app/`: The small real workload deployed for the demonstration.
- `labctl/`: Python CLI for preflight, deploy, provision, verify, scenario
  control, reset, status, evidence collection, and destroy.
- `scenarios/`: Failure definitions, operator metadata, runbooks, and exact
  automated checks for each demonstration scene.
- `docs/`: Presenter-facing HTML slides, detailed guide, diagrams, and assets.
- `scripts/`: Thin bootstrap wrappers only; orchestration belongs in `labctl`.
- `tests/`: End-to-end and repository-wide validation.
- Root `README.md`: Concise quick start and navigation.
- Root `SPEC.md`: Product scope, architecture, scenarios, requirements, and
  acceptance criteria.
- Root `PLAN.md`: Milestones and current execution status.

Do not add a `student/` tree or hands-on lab material unless explicitly asked.

## Infrastructure as code

Terraform is the source of truth for Azure resources.

- Use the AzureRM provider for stable resources it supports.
- Use the AzAPI provider for Azure SRE Agent and other ARM capabilities that
  AzureRM does not support or exposes incompletely.
- Use the Microsoft Graph Terraform provider only for required Entra or Graph
  objects that cannot be expressed through ARM.
- Use Python glue only when declarative providers are unsuitable, such as
  building an image with Azure Container Registry, invoking a documented data
  plane API, uploading agent knowledge, or triggering a controlled scenario.
- Never use portal-only creation as the primary deployment path.
- Document any unavoidable one-time portal consent or interactive connector
  authorization and detect it in `labctl preflight`.
- Pin Terraform and provider versions deliberately.
- Keep Terraform state local. Configure no remote backend.
- Keep secrets local, outside Terraform variables and state whenever possible.
  Prefer Azure CLI authentication, managed identities, environment variables,
  and ignored local configuration.
- Treat Terraform plans, state, logs, generated evidence, and crash files as
  sensitive local artifacts.
- Tag every Azure resource with repository, environment, owner, and deployment
  identity metadata sufficient to prove cleanup ownership.
- Keep destructive scope limited to resources created by this repository.

Infrastructure must be idempotent or have an explicit safe retry path. A
partially failed deployment must remain inspectable and recoverable.

## Python and `labctl`

Implement `labctl` as a typed Python CLI with a small dependency set.

Required command surface:

```text
labctl preflight
labctl deploy
labctl provision
labctl verify
labctl status
labctl demo list
labctl demo prepare <scenario>
labctl demo trigger <scenario>
labctl demo verify <scenario>
labctl demo reset <scenario>
labctl evidence collect
labctl destroy
```

Command names may gain options, but these lifecycle outcomes must remain
available and documented.

Automation must:

- support non-interactive execution where Azure APIs permit it;
- return nonzero on partial or complete failure;
- use bounded retries and explicit timeouts;
- preserve Azure correlation IDs and actionable diagnostics;
- print the exact operation scope and resources left after failure;
- avoid broad exception handling and silent fallbacks;
- avoid logging tokens, connection strings, Terraform state, or secret values;
- work on Windows PowerShell, the primary supported operator platform;
- use subprocess argument arrays rather than shell command strings;
- make repeat deployment, reset, verification, and destroy safe.

`labctl deploy` owns the complete clean deployment path. `provision` performs
post-Terraform data-plane configuration that cannot be represented reliably in
Terraform. Both operations must be safe to rerun.

## Real workload and incidents

The demo workload must be inexpensive, fast to deploy, and rich enough to
produce meaningful Azure Monitor and Application Insights evidence.

- Use synthetic data only.
- Expose a clear healthy user journey.
- Instrument logs, traces, requests, dependencies, exceptions, and custom
  dimensions needed for diagnosis.
- Implement faults as explicit, authenticated or otherwise safely constrained
  controls that cannot be triggered accidentally by ordinary users.
- Every fault must be reversible through `labctl demo reset`.
- Prefer failures that produce distinct evidence across code, configuration,
  deployment history, telemetry, and Azure resource state.
- Configure real Azure Monitor alerts and ensure the showcase path reaches the
  real Azure SRE Agent incident workflow.
- Do not claim a mitigation succeeded until application behavior and telemetry
  both confirm recovery.

## Azure SRE Agent

Verify volatile behavior against current first-party documentation and the
published ARM schema before changing deployment or configuration.

- Use `Microsoft.App/agents` through AzAPI unless a supported Terraform resource
  becomes available and provides equivalent control.
- Register and verify required resource providers.
- Deploy the agent in a currently supported region.
- Attach a user-assigned managed identity and grant only the roles required by
  the selected scenarios.
- Default destructive or write-capable scenes to Review mode so the presenter
  explicitly approves actions.
- Keep optional Autonomous-mode demonstrations isolated and clearly labeled.
- Connect the workload resource scope, Application Insights, Log Analytics,
  Azure Monitor incidents, source code, and operational knowledge needed for
  grounded investigation.
- Use stable APIs when verified in the target subscription and region. Record a
  justified, tested preview fallback if service rollout requires it.
- Surface agent endpoint, portal URL, power state, permissions, integrations,
  and health through `labctl status`, without exposing secrets.
- Record unavoidable OAuth or consent boundaries honestly. Automation must
  prepare everything around them and verify completion.

## Presenter-facing content

HTML is the source format for slides and detailed documentation. Markdown at the
repository root is for engineering control documents only.

### Visual system

- Support light and dark modes with a persistent manual toggle.
- Use black, white, grayscale, and Microsoft blue (`#0078D4`) as the accent
  family.
- Keep layouts clean, spacious, restrained, and Microsoft-inspired.
- Use no Unicode emoji.
- Meet accessible contrast, semantic HTML, keyboard navigation, visible focus,
  and reduced-motion expectations.
- Optimize slides for a full-screen 16:9 viewport and keep them responsive.
- Vendor runtime dependencies. Do not rely on CDNs or hosted assets.
- Prefer plain HTML, CSS, and JavaScript.

### Slides

- Use slides as visual speaking aids, not dense documentation.
- Keep one main idea per slide and use progressive disclosure.
- Support Arrow keys, Space, Page Up/Page Down, Home, End, and `F` for full
  screen.
- Provide slide progress, stable deep links, presenter notes, and unobtrusive
  controls.
- Link technical detail to stable sections of the HTML guide.

### Guide

- Write directly to the presenter using imperative steps.
- Include timing, talking points, expected visible states, transitions,
  approval cues, fallback paths, and cleanup.
- Provide copyable commands and expected results.
- Cross-link architecture, security, cost, troubleshooting, and source.
- Keep product claims current, dated where volatile, and linked to first-party
  sources.
- Do not publish fake output, placeholders, drafting notes, or unverified
  screenshots.

## Architecture decisions

Create an ADR for significant choices in architecture, security, deployment,
failure design, or content delivery.

- Store ADRs in `docs/adr/`.
- Name them `NNNN-kebab-case-title.md`.
- Record context, drivers, options, decision, consequences, validation, and
  explicit revisit triggers.
- Do not create ADRs for routine implementation details.

## Validation

Use the smallest reliable checks during development, then run the full
clean-room lifecycle before declaring the demo complete.

Required validation includes:

- Python formatting, linting, type checking, and tests using tools already
  declared by the project;
- Terraform formatting, initialization, validation, and plan inspection;
- secret scanning and verification of ignored local artifacts;
- HTML validation, internal-link checking, accessibility checks, responsive
  checks, and keyboard-only slide navigation;
- clean deployment from documented prerequisites;
- smoke tests for the healthy workload;
- exact trigger, alert, investigation, mitigation, recovery, and reset path for
  each scenario;
- repeat deployment and repeat reset;
- evidence collection;
- destructive-scope review followed by complete cleanup;
- confirmation that Azure resources are actually removed after destroy.

Build success is not proof of a working demo. Verify the visible application,
Azure telemetry, Azure Monitor alert, Azure SRE Agent investigation, approved
action, and recovered application.

## Engineering loop and review gates

Use independent subagents at meaningful boundaries. The implementation loop is:

1. **Research:** Verify current product behavior, APIs, constraints, and
   first-party guidance.
2. **Develop:** Implement one milestone with tests and operational evidence.
3. **Deploy:** Exercise it against a real Azure subscription from a clean or
   explicitly characterized state.
4. **Critic:** Give an independent reviewer the actual files, commands, logs,
   and visible outcome.
5. **Iterate:** Fix every blocking or material finding and repeat the relevant
   deployment and review.

Required reviewers:

- **Azure architecture reviewer:** resource design, API usage, observability,
  cost, regional support, and product accuracy.
- **SRE scenario critic:** incident realism, diagnostic quality, remediation,
  recovery proof, and demonstration value.
- **Clean-room operator:** documented prerequisites, hidden state, idempotency,
  retries, reset, and cleanup.
- **Security and destructive-safety reviewer:** secrets, state, logs, identity,
  least privilege, consent, ownership tags, and deletion scope.
- **Presentation critic:** narrative, timing, slide readability, accessibility,
  operator cues, and factual grounding.

Reviewers must inspect real artifacts and evidence rather than summaries.
Repeat reviews until no blocking or material findings remain.

## Definition of done

The demonstration is complete only when:

- `labctl` deploys the full environment from the documented starting point;
- Terraform and post-provisioning are repeatable;
- the healthy workload and all selected scenarios pass automated checks;
- a real Azure Monitor signal reaches a real Azure SRE Agent workflow;
- the agent produces a grounded investigation and a real approved action or
  remediation;
- recovery is verified from both the user and telemetry perspectives;
- slides and guide are polished, accessible, cross-linked, and rehearsable;
- local state and secrets are ignored and absent from version control;
- destroy removes every owned Azure resource and reports any retained item;
- all required independent reviews have no blocking or material findings.
