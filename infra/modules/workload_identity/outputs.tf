output "id" {
  description = "Full resource ID of the user-assigned managed identity."
  value       = azurerm_user_assigned_identity.this.id
}

output "principal_id" {
  description = "Object (principal) ID of the identity, used for role assignments."
  value       = azurerm_user_assigned_identity.this.principal_id
}

output "client_id" {
  description = "Client ID of the identity."
  value       = azurerm_user_assigned_identity.this.client_id
}

output "name" {
  description = "Name of the identity."
  value       = azurerm_user_assigned_identity.this.name
}
