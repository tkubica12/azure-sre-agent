output "agent_id" {
  description = "Full resource ID of the Azure SRE Agent (Microsoft.App/agents)."
  value       = azapi_resource.agent.id
}

output "agent_name" {
  description = "Name of the Azure SRE Agent resource."
  value       = azapi_resource.agent.name
}

output "system_identity_principal_id" {
  description = "Object (principal) ID of the agent's system-assigned managed identity."
  value       = azapi_resource.agent.identity[0].principal_id
}

output "uami_id" {
  description = "Full resource ID of the agent's user-assigned managed identity."
  value       = azurerm_user_assigned_identity.agent.id
}

output "uami_principal_id" {
  description = "Object (principal) ID of the agent's user-assigned managed identity."
  value       = azurerm_user_assigned_identity.agent.principal_id
}

output "uami_client_id" {
  description = "Client ID of the agent's user-assigned managed identity."
  value       = azurerm_user_assigned_identity.agent.client_id
}

output "portal_url" {
  description = "Azure SRE Agent portal deep link (see SPEC.md section 11)."
  value       = "https://sre.azure.com/#/agent/${data.azurerm_subscription.current.subscription_id}/${var.resource_group_name}/${var.name}"
}

output "data_plane_endpoint" {
  description = "Azure SRE Agent data-plane endpoint, read directly from ARM's `properties.agentEndpoint` (its real hostname includes deployment-specific hash suffixes, e.g. \"https://<name>--<hash>.<hash2>.<region>.azuresre.ai\", not just \"<name>.<region>.azuresre.ai\"; verified live). Its Microsoft Entra token audience is https://azuresre.dev, kept distinct (see SPEC.md section 11)."
  value       = azapi_resource.agent.output.properties.agentEndpoint
}

output "connector_names" {
  description = "Names of every agent connector this module manages."
  value       = keys(local.connectors)
}
