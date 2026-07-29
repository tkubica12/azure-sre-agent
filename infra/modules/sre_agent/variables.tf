variable "name" {
  description = "Name of the Azure SRE Agent resource (Microsoft.App/agents)."
  type        = string

  validation {
    # Matches the official Microsoft Terraform template's validation
    # (https://github.com/microsoft/sre-agent/tree/main/sreagent-templates/terraform).
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$", var.name))
    error_message = "name must be lowercase alphanumeric with hyphens, 2-63 characters."
  }
}

variable "resource_group_name" {
  description = "Name of the resource group that owns the agent and its identities."
  type        = string
}

variable "resource_group_id" {
  description = "Full resource ID of the resource group that owns the agent, used as the azapi_resource parent_id."
  type        = string
}

variable "location" {
  description = "Azure region for the agent and its identities. Must be a region where Azure SRE Agent is currently supported (see SPEC.md section 3)."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

variable "workload_resource_group_id" {
  description = "Full resource ID of the workload resource group the agent investigates and can act on (see SPEC.md section 9)."
  type        = string
}

variable "workload_app_insights_id" {
  description = "Full resource ID of the workload's Application Insights resource, connected so the agent can query workload telemetry directly."
  type        = string
}

variable "workload_app_insights_app_id" {
  description = "Application ID (not resource ID) of the workload's Application Insights resource, used in the connector's extendedProperties."
  type        = string
}

variable "workload_log_analytics_id" {
  description = "Full resource ID of the workload's Log Analytics workspace, connected so the agent can query workload logs directly."
  type        = string
}

variable "workload_container_app_id" {
  description = "Full resource ID of the demo's Container App, used to scope the narrow 'Container Apps Contributor' grant (see SPEC.md section 9) instead of granting Contributor across the whole workload resource group."
  type        = string
}

variable "workload_access_level" {
  description = <<-EOT
    Controls how much access the agent's identities get on the workload
    resource group (see SPEC.md section 9).

    - "narrow" (default): Reader + Log Analytics Reader at the workload
      resource group, plus Container Apps Contributor scoped only to the
      Container App resource. Enough to read telemetry/resource state and
      perform a revision/traffic rollback, without letting the agent alter
      or delete the ACR, Log Analytics workspace, alert rules, or anything
      else in the resource group.
    - "broad": Contributor at the whole workload resource group (the
      previously deployed grant, matching the official Terraform template's
      tested High-access path). Kept as an escape hatch: flip to this only
      if live testing during the Milestone 5 incident scene proves the
      narrow set insufficient for a real remediation action.

    The narrow default is pending live confirmation against a real
    incident-investigation-and-remediation pass (see PLAN.md Milestone 5).
  EOT
  type        = string
  default     = "narrow"

  validation {
    condition     = contains(["narrow", "broad"], var.workload_access_level)
    error_message = "workload_access_level must be narrow or broad."
  }
}

variable "agent_app_insights_app_id" {
  description = "Application ID of the agent's own Application Insights resource (audit/operational telemetry, distinct from the workload's)."
  type        = string
}

variable "agent_app_insights_connection_string" {
  description = "Connection string of the agent's own Application Insights resource. Not a secret to Azure, but never logged or printed in plain text by labctl (see AGENTS.md)."
  type        = string
  sensitive   = true
}

variable "access_level" {
  description = "Agent action access level. 'High' allows the agent to take real remediation actions, gated by action_mode (see SPEC.md section 9)."
  type        = string
  default     = "High"

  validation {
    condition     = contains(["High", "Low"], var.access_level)
    error_message = "access_level must be High or Low."
  }
}

variable "action_mode" {
  description = "Agent action mode. 'Review' requires explicit human approval for every action (see AGENTS.md 'Default destructive or write-capable scenes to Review mode')."
  type        = string
  default     = "Review"

  validation {
    condition     = contains(["Review", "Automatic"], var.action_mode)
    error_message = "action_mode must be Review or Automatic."
  }
}

variable "upgrade_channel" {
  description = "Agent runtime upgrade channel, matching the official Terraform template's variable."
  type        = string
  default     = "Preview"

  validation {
    condition     = contains(["Stable", "Preview"], var.upgrade_channel)
    error_message = "upgrade_channel must be Stable or Preview."
  }
}

variable "monthly_agent_unit_limit" {
  description = "Monthly Azure Agent Unit consumption limit (see SPEC.md section 14 cost guardrails). 3000 is a demo-sized default: Azure SRE Agent bills a fixed 4 AAUs/agent-hour always-on (https://learn.microsoft.com/azure/sre-agent/pricing-billing), ~2,880 AAU across a full month, so this leaves headroom for that plus several incident-investigation passes without matching the official template's much larger 10,000 permissive-ceiling default."
  type        = number
  default     = 3000

  validation {
    # 5000 mirrors labctl.config.MAX_SENSIBLE_MONTHLY_AAU_ALLOCATION -- a
    # deliberate demo-sized cap, not a documented product minimum/maximum.
    condition     = var.monthly_agent_unit_limit > 0 && var.monthly_agent_unit_limit <= 5000
    error_message = "monthly_agent_unit_limit must be a positive number no greater than 5000 (see SPEC.md section 14; raise deliberately if a rehearsal genuinely needs more)."
  }
}

variable "grant_uami_agent_administrator" {
  description = <<-EOT
    Whether to grant the agent's own user-assigned managed identity (UAMI)
    the "SRE Agent Administrator" role (e79298df-d852-4c6d-84f9-5d13249d1e55)
    on the agent resource itself, in addition to the deployer.

    Default is `false`. Live-verified 2026-07-29 (PLAN.md Milestone 5): with
    this grant present (the prior default, copied from the official
    Microsoft template's general recipe), a real incident-driven mutating
    action (`az containerapp ingress traffic set`) executed with NO entry
    ever appearing under `GET /api/v1/approvals/{threadId}`, despite
    `actionConfiguration.mode: Review` at the agent level and
    `agentMode: Review` on the response plan -- i.e. the Review-mode
    approval gate did not visibly engage. Microsoft's own official
    `deployment-compliance` reference lab (a purpose-built approval-gate
    demo) grants "SRE Agent Administrator" only to the deploying user, never
    to the agent's own identity; its `agent-core.bicep` comments the UAMI
    grant as "needed for Logic App webhook bridge to call HTTP triggers" --
    a capability this repository does not use. Because "only SRE Agent
    Administrators can approve actions" (see
    https://learn.microsoft.com/azure/sre-agent/permissions), granting that
    role to the identity whose own actions are supposed to be gated was a
    plausible self-approval vector, so it was tested directly.

    **This self-approval theory was tested and found insufficient alone.**
    A second, definitive live cycle (2026-07-29, PLAN.md Milestone 5) removed
    this grant while keeping "SRE Agent Administrator" for the deployer, and
    on a genuinely fresh incident thread (forced by temporarily disabling
    `mergeEnabled` so a new thread was created rather than reusing a stale
    one) whose own `agentMode` field read `"Review"` at investigation time,
    the mutating write still executed for real -- Activity Log entry ~5
    seconds after the tool-call message, `GET /api/v1/approvals/{threadId}`
    empty throughout, every message's `hookExecution`/`approval` fields
    `null` the entire thread. Removing this grant did NOT restore a working
    approval gate; the underlying limitation is a platform behavior of this
    preview data-plane API build, not this repository's RBAC configuration.
    See PLAN.md Milestone 5 for the full evidence trail.

    The grant is still kept at `false` by default as ordinary least-privilege
    practice (an agent identity has no legitimate reason to administer its
    own agent resource) even though removing it did not, by itself, fix the
    approval-gate behavior. This demonstration's actual, live-proven
    governance control is TOOL SCOPING (see
    `agent/config/subagents/rollback-advisor.yaml` and SPEC.md section 5
    Scene 5), not this RBAC grant. Set to `true` only if a future scenario
    genuinely needs the agent to call back into its own data-plane API (for
    example a Logic App webhook bridge) and accepts the (separately
    reasoned) least-privilege cost of doing so.
  EOT
  type        = bool
  default     = false
}

variable "default_model_provider" {
  description = "Default LLM provider for the agent. Verify against the live supportedAgentModels API before changing (see labctl preflight's agent-model-availability check)."
  type        = string
  default     = "Anthropic"
}

variable "default_model_name" {
  description = "Default LLM model name for the agent."
  type        = string
  default     = "Automatic"
}

variable "azure_monitor_lookback_days" {
  description = "Lookback window in days for the Azure Monitor connector's alert/incident ingestion."
  type        = number
  default     = 7
}

variable "connector_timeout" {
  description = "Per-operation timeout for each agent connector. Connector PUTs are asynchronous and can take 10-30 minutes in the background; Terraform's own wait is capped here, and a timeout is not treated as final failure by `labctl deploy` (see SPEC.md section 11 and AGENTS.md)."
  type        = string
  default     = "10m"
}
