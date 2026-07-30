variable "region" {
  description = "Azure region for all demo resources. Must be a region where Azure SRE Agent is currently supported (see SPEC.md section 3)."
  type        = string
  default     = "swedencentral"

  validation {
    # Extend this list only after live validation of an additional region
    # (see PLAN.md "Known risks" and https://learn.microsoft.com/azure/sre-agent/supported-regions).
    condition     = contains(["swedencentral"], var.region)
    error_message = "region must be one of the currently supported Azure SRE Agent regions: swedencentral."
  }
}

variable "subscription_id" {
  description = "Optional subscription ID override. Empty string uses the Azure CLI's current subscription."
  type        = string
  default     = ""
}

variable "tenant_id" {
  description = "Optional tenant ID override. Empty string uses the Azure CLI's current tenant."
  type        = string
  default     = ""
}

variable "agent_resource_group_name" {
  description = "Name of the resource group that owns the Azure SRE Agent and its identities."
  type        = string
  default     = "rg-sre-agent-demo"

  validation {
    condition     = length(var.agent_resource_group_name) > 0 && length(var.agent_resource_group_name) <= 90
    error_message = "agent_resource_group_name must be between 1 and 90 characters."
  }
}

variable "workload_resource_group_name" {
  description = "Name of the resource group that owns the demo workload."
  type        = string
  default     = "rg-sre-agent-workload-demo"

  validation {
    condition     = length(var.workload_resource_group_name) > 0 && length(var.workload_resource_group_name) <= 90
    error_message = "workload_resource_group_name must be between 1 and 90 characters."
  }
}

variable "tags" {
  description = "Tags applied to every resource so ownership and cleanup scope are provable (see AGENTS.md)."
  type = object({
    repository    = string
    environment   = string
    owner         = string
    deployment_id = string
  })
  default = {
    repository    = "azure-sre-agent"
    environment   = "demo"
    owner         = "change-me"
    deployment_id = "local"
  }
}

variable "alert_notification_email" {
  description = "Optional operator email address for the workload alert action group. Left empty by default; see infra/modules/alerting and AGENTS.md 'no-secret action group'."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "Log Analytics workspace retention in days for the workload resource group."
  type        = number
  default     = 30
}

variable "alert_threshold_5xx" {
  description = "Minimum total Container App HTTP 5xx requests within the alert window that fires the demo's Azure Monitor alert."
  type        = number
  default     = 3
}

variable "agent_name" {
  description = "Name of the Azure SRE Agent resource (Microsoft.App/agents)."
  type        = string
  default     = "sre-agent-demo"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$", var.agent_name))
    error_message = "agent_name must be lowercase alphanumeric with hyphens, 2-63 characters."
  }
}

variable "agent_upgrade_channel" {
  description = "Azure SRE Agent runtime upgrade channel (see infra/modules/sre_agent)."
  type        = string
  default     = "Preview"

  validation {
    condition     = contains(["Stable", "Preview"], var.agent_upgrade_channel)
    error_message = "agent_upgrade_channel must be Stable or Preview."
  }
}

variable "agent_monthly_aau_allocation" {
  description = "Monthly Azure Agent Unit consumption limit; a demo-sized default, not the official template's much larger permissive-ceiling default (see SPEC.md section 14)."
  type        = number
  default     = 3000

  validation {
    condition     = var.agent_monthly_aau_allocation > 0 && var.agent_monthly_aau_allocation <= 5000
    error_message = "agent_monthly_aau_allocation must be a positive number no greater than 5000 (see SPEC.md section 14)."
  }
}

variable "agent_model_provider" {
  description = "Default LLM provider for the Azure SRE Agent. Verified live against the supportedAgentModels API (see labctl preflight's agent-model-availability check)."
  type        = string
  default     = "Anthropic"
}

variable "agent_model_name" {
  description = "Default LLM model name for the Azure SRE Agent."
  type        = string
  default     = "Automatic"
}

variable "agent_workload_access_level" {
  description = "Access level granted to the Azure SRE Agent's identities on the workload resource group: 'narrow' (default, least privilege) or 'broad' (Contributor at resource-group scope; escape hatch, see SPEC.md section 9 and infra/modules/sre_agent)."
  type        = string
  default     = "narrow"

  validation {
    condition     = contains(["narrow", "broad"], var.agent_workload_access_level)
    error_message = "agent_workload_access_level must be narrow or broad."
  }
}
