output "id" {
  description = "Full resource ID of the container registry."
  value       = azurerm_container_registry.this.id
}

output "name" {
  description = "Name of the container registry."
  value       = azurerm_container_registry.this.name
}

output "login_server" {
  description = "Login server hostname used for image references (e.g. myregistry.azurecr.io)."
  value       = azurerm_container_registry.this.login_server
}
