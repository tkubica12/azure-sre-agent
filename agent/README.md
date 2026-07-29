# Azure SRE Agent content (Milestone 4)

Version-controlled data-plane configuration for the deployed
`Microsoft.App/agents` resource, specific to the PulseMart checkout-500
incident story (see SPEC.md sections 5 and 10). Applied idempotently by
`labctl provision` and read back by `labctl verify`/`labctl status`.

The layout mirrors the official `microsoft/sre-agent` template's
`recipes/*/config/` and `recipes/*/automations/` convention (`metadata`/
`spec` YAML, with long text content referenced by a relative path to a
sibling markdown file) so this content stays directly comparable to the
first-party recipes:

```text
agent/
  knowledge/                        # uploaded via AgentMemory (POST /api/v1/AgentMemory/upload)
    architecture.md
    checkout-500-runbook.md
    investigation-report-template.md
    remediation-report-template.md
  config/
    skills/                         # PUT /api/v2/extendedAgent/skills/{name}
      triage-checkout-failures.yaml
      triage-checkout-failures.md
    subagents/                      # PUT /api/v2/extendedAgent/agents/{name}
      incident-investigator.yaml
      incident-investigator.instructions.md
      rollback-advisor.yaml
      rollback-advisor.instructions.md
    hooks/                          # PUT /api/v2/extendedAgent/hooks/{name}
      require-approval-for-changes.yaml
      deny-destructive-deletes.yaml
    common-prompts/                 # PUT /api/v2/extendedAgent/commonprompts/{name}
      investigation-guidelines.yaml
      safety-rules.yaml
  automations/
    incident-platforms/              # ARM PATCH properties.incidentManagementConfiguration
      azure-monitor.yaml
    incident-filters/                # PUT /api/v2/extendedAgent/incidentFilters/{name} (response plan)
      checkout-5xx.yaml
    scheduled-tasks/                 # PUT /api/v2/extendedAgent/scheduledtasks/{name}
      daily-reliability-summary.yaml
  expected-config.json               # names labctl verify/status check for
```

Not represented as files here, because they are computed directly from
`config.local.toml` rather than duplicated in this directory:

- The GitHub source repository connection (`[github].repository`) and its
  Personal Access Token authentication (the operator's existing `gh auth
  token`) -- see SPEC.md section 10 and the "GitHub authorization" note in
  `README.md`/`PLAN.md` Milestone 4 for the one honest manual-consent
  boundary this implies.

Editing content: change the YAML/markdown files here, then re-run
`labctl provision` (idempotent -- it always PUTs the current file content,
overwriting whatever the agent previously had for that name).
