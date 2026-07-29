variable "name" {
  description = "Globally unique Azure Container Registry name (alphanumeric only, 5-50 characters)."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9]{5,50}$", var.name))
    error_message = "name must be 5-50 alphanumeric characters (no hyphens or underscores)."
  }
}

variable "resource_group_name" {
  description = "Resource group to create the registry in."
  type        = string
}

variable "location" {
  description = "Azure region for the registry."
  type        = string
}

variable "sku" {
  description = "Registry SKU. Basic is the least expensive tier and is sufficient for a single demo image (see AGENTS.md cost guidance)."
  type        = string
  default     = "Basic"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.sku)
    error_message = "sku must be one of: Basic, Standard, Premium."
  }
}

variable "tags" {
  description = "Tags applied to the registry so ownership and cleanup scope are provable."
  type        = map(string)
  default     = {}
}
