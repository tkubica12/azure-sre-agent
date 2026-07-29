variable "log_analytics_name" {
  description = "Name of the Log Analytics workspace."
  type        = string
}

variable "app_insights_name" {
  description = "Name of the Application Insights resource."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create both resources in."
  type        = string
}

variable "location" {
  description = "Azure region for both resources."
  type        = string
}

variable "retention_in_days" {
  description = "Log Analytics data retention in days. 30 is the minimum practical retention for the PerGB2018 SKU used here (see AGENTS.md cost guidance: 'minimum practical log retention')."
  type        = number
  default     = 30

  validation {
    condition     = var.retention_in_days >= 30 && var.retention_in_days <= 730
    error_message = "retention_in_days must be between 30 and 730 for the PerGB2018 SKU."
  }
}

variable "daily_quota_gb" {
  description = "Daily ingestion cap in GB for the Log Analytics workspace, to bound cost for a demo environment. -1 disables the cap."
  type        = number
  default     = 1
}

variable "tags" {
  description = "Tags applied to both resources so ownership and cleanup scope are provable."
  type        = map(string)
  default     = {}
}
