variable "name" {
  description = "Name of the Container Apps environment."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create the environment in."
  type        = string
}

variable "location" {
  description = "Azure region for the environment."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace platform logs are sent to."
  type        = string
}

variable "tags" {
  description = "Tags applied to the environment so ownership and cleanup scope are provable."
  type        = map(string)
  default     = {}
}
