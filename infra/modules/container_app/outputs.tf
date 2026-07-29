output "id" {
  description = "Full resource ID of the Container App."
  value       = azurerm_container_app.this.id
}

output "name" {
  description = "Name of the Container App."
  value       = azurerm_container_app.this.name
}

output "latest_revision_fqdn" {
  description = "FQDN of the latest Container App revision. The stable ingress FQDN operators and labctl should use is `fqdn` below; this is kept for diagnostics."
  value       = azurerm_container_app.this.latest_revision_fqdn
}

output "fqdn" {
  description = "Stable, publicly resolvable FQDN for the Container App's external ingress."
  value       = try(azurerm_container_app.this.ingress[0].fqdn, null)
}
