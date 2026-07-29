output "id" {
  description = "Full resource ID of the Container Apps environment."
  value       = azurerm_container_app_environment.this.id
}

output "name" {
  description = "Name of the Container Apps environment."
  value       = azurerm_container_app_environment.this.name
}

output "default_domain" {
  description = "Default, publicly resolvable domain suffix for Container Apps in this environment."
  value       = azurerm_container_app_environment.this.default_domain
}
