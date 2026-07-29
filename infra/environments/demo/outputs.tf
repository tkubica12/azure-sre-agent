output "agent_resource_group_name" {
  description = "Name of the resource group that owns the Azure SRE Agent and its identities."
  value       = module.agent_resource_group.name
}

output "agent_resource_group_id" {
  description = "Full resource ID of the resource group that owns the Azure SRE Agent and its identities, used by `labctl destroy` to verify exact ownership before any destructive operation (see SPEC.md section 11)."
  value       = module.agent_resource_group.id
}

output "workload_resource_group_name" {
  description = "Name of the resource group that owns the demo workload."
  value       = module.workload_resource_group.name
}

output "workload_resource_group_id" {
  description = "Full resource ID of the resource group that owns the demo workload, used by `labctl destroy` to verify exact ownership before any destructive operation (see SPEC.md section 11)."
  value       = module.workload_resource_group.id
}

output "container_registry_name" {
  description = "Name of the Azure Container Registry used for `az acr build`."
  value       = module.container_registry.name
}

output "container_registry_login_server" {
  description = "Login server hostname for the Azure Container Registry."
  value       = module.container_registry.login_server
}

output "workload_identity_id" {
  description = "Resource ID of the workload's user-assigned managed identity (AcrPull)."
  value       = module.workload_identity.id
}

output "workload_identity_client_id" {
  description = "Client ID of the workload's user-assigned managed identity."
  value       = module.workload_identity.client_id
}

output "log_analytics_workspace_id" {
  description = "GUID-formatted Log Analytics workspace ID, used for KQL query API calls."
  value       = module.observability.log_analytics_workspace_id
}

output "log_analytics_resource_id" {
  description = "Full ARM resource ID of the Log Analytics workspace."
  value       = module.observability.log_analytics_id
}

output "app_insights_app_id" {
  description = "Application Insights application ID, used for the Application Insights query API."
  value       = module.observability.app_insights_app_id
}

output "app_insights_resource_id" {
  description = "Full ARM resource ID of the Application Insights resource."
  value       = module.observability.app_insights_id
}

output "app_insights_connection_string" {
  description = "Application Insights connection string. Not treated as a secret by Azure, but kept out of default console output."
  value       = module.observability.app_insights_connection_string
  sensitive   = true
}

output "container_apps_environment_id" {
  description = "Resource ID of the Container Apps environment."
  value       = module.container_apps_environment.id
}

output "container_app_name" {
  description = "Name of the PulseMart Container App."
  value       = module.container_app.name
}

output "container_app_id" {
  description = "Resource ID of the PulseMart Container App."
  value       = module.container_app.id
}

output "container_app_fqdn" {
  description = "Public HTTPS FQDN for the PulseMart Container App."
  value       = module.container_app.fqdn
}

output "action_group_id" {
  description = "Resource ID of the checkout-failure action group."
  value       = module.alerting.action_group_id
}

output "metric_alert_id" {
  description = "Resource ID of the checkout 5xx metric alert rule."
  value       = module.alerting.metric_alert_id
}

output "metric_alert_name" {
  description = "Name of the checkout 5xx metric alert rule."
  value       = module.alerting.metric_alert_name
}

output "agent_id" {
  description = "Full resource ID of the Azure SRE Agent (Microsoft.App/agents)."
  value       = module.sre_agent.agent_id
}

output "agent_name" {
  description = "Name of the Azure SRE Agent resource."
  value       = module.sre_agent.agent_name
}

output "agent_portal_url" {
  description = "Azure SRE Agent portal deep link."
  value       = module.sre_agent.portal_url
}

output "agent_data_plane_endpoint" {
  description = "Azure SRE Agent data-plane endpoint (audience https://azuresre.dev; see SPEC.md section 11)."
  value       = module.sre_agent.data_plane_endpoint
}

output "agent_uami_id" {
  description = "Full resource ID of the agent's user-assigned managed identity."
  value       = module.sre_agent.uami_id
}

output "agent_uami_principal_id" {
  description = "Object (principal) ID of the agent's user-assigned managed identity."
  value       = module.sre_agent.uami_principal_id
}

output "agent_uami_client_id" {
  description = "Client ID of the agent's user-assigned managed identity."
  value       = module.sre_agent.uami_client_id
}

output "agent_system_identity_principal_id" {
  description = "Object (principal) ID of the agent's system-assigned managed identity."
  value       = module.sre_agent.system_identity_principal_id
}

output "agent_connector_names" {
  description = "Names of every agent connector this deployment manages."
  value       = module.sre_agent.connector_names
}

output "agent_app_insights_id" {
  description = "Full resource ID of the agent's own Application Insights resource (distinct from the workload's)."
  value       = module.agent_observability.app_insights_id
}

output "agent_app_insights_app_id" {
  description = "Application ID of the agent's own Application Insights resource."
  value       = module.agent_observability.app_insights_app_id
}

output "agent_log_analytics_id" {
  description = "Full resource ID of the agent's own Log Analytics workspace."
  value       = module.agent_observability.log_analytics_id
}

output "agent_log_analytics_workspace_id" {
  description = "GUID-formatted workspace ID of the agent's own Log Analytics workspace."
  value       = module.agent_observability.log_analytics_workspace_id
}

