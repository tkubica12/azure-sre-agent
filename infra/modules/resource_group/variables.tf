variable "name" {
  description = "Resource group name."
  type        = string

  validation {
    condition     = length(var.name) > 0 && length(var.name) <= 90
    error_message = "name must be between 1 and 90 characters."
  }
}

variable "location" {
  description = "Azure region for the resource group."
  type        = string
}

variable "tags" {
  description = "Tags applied to the resource group so ownership and cleanup scope are provable."
  type        = map(string)
  default     = {}
}
