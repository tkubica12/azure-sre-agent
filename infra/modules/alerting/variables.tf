variable "resource_group_name" {
  description = "Resource group to create the action group and alert rule in."
  type        = string
}

variable "action_group_name" {
  description = "Name of the Azure Monitor action group."
  type        = string
}

variable "action_group_short_name" {
  description = "Short name (max 12 characters) shown in notifications."
  type        = string

  validation {
    condition     = length(var.action_group_short_name) > 0 && length(var.action_group_short_name) <= 12
    error_message = "action_group_short_name must be 1-12 characters."
  }
}

variable "notification_email" {
  description = "Optional operator email address for alert notifications. Left empty by default so the action group carries no operator-specific contact information; the Container App 5xx alert still fires and is visible in the Azure portal and to the Azure SRE Agent (Milestone 3) without it."
  type        = string
  default     = ""
}

variable "container_app_id" {
  description = "Resource ID of the Container App to scope the metric alert to."
  type        = string
}

variable "app_insights_id" {
  description = "Resource ID of the Application Insights component queried by the canary-regression scheduled query alert."
  type        = string
}

variable "location" {
  description = "Azure region for scheduled query alert resources."
  type        = string
}

variable "alert_name" {
  description = "Name of the metric alert rule."
  type        = string
}

variable "canary_alert_name" {
  description = "Name of the canary-regression scheduled query alert rule."
  type        = string
  default     = "alert-pulsemart-canary-regression"
}

variable "severity" {
  description = "Azure Monitor alert severity (0 = critical .. 4 = verbose)."
  type        = number
  default     = 2

  validation {
    condition     = var.severity >= 0 && var.severity <= 4
    error_message = "severity must be between 0 and 4."
  }
}

variable "threshold" {
  description = "Minimum total Container App HTTP 5xx request count within `window_size` that fires the alert. Kept low and deterministic for a live demo (see AGENTS.md 'short deterministic threshold/evaluation suitable for a demo')."
  type        = number
  default     = 3
}

variable "window_size" {
  description = "ISO 8601 aggregation window for the metric alert."
  type        = string
  default     = "PT5M"
}

variable "frequency" {
  description = "ISO 8601 evaluation frequency for the metric alert."
  type        = string
  default     = "PT1M"
}

variable "canary_frequency" {
  description = "ISO 8601 evaluation frequency for the canary-regression scheduled query alert. Azure Monitor rejects one-minute frequency for log alert rules that do not query a small set of known tables (error `QueryNotContainKnownTable`), so this defaults to five minutes independently of the metric alert's `frequency`. See https://aka.ms/lsa_1m_limits."
  type        = string
  default     = "PT5M"

  validation {
    condition     = contains(["PT1M", "PT5M", "PT10M", "PT15M", "PT30M", "PT45M", "PT1H", "PT2H", "PT3H", "PT4H", "PT5H", "PT6H", "P1D"], var.canary_frequency)
    error_message = "canary_frequency must be a supported Azure Monitor scheduled query rule evaluation frequency."
  }
}

variable "tags" {
  description = "Tags applied to both resources so ownership and cleanup scope are provable."
  type        = map(string)
  default     = {}
}
