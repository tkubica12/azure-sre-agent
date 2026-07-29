variable "name" {
  description = "Name of the user-assigned managed identity."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create the identity in."
  type        = string
}

variable "location" {
  description = "Azure region for the identity."
  type        = string
}

variable "acr_id" {
  description = "Resource ID of the Azure Container Registry this identity should be granted AcrPull on."
  type        = string
}

variable "tags" {
  description = "Tags applied to the identity so ownership and cleanup scope are provable."
  type        = map(string)
  default     = {}
}
