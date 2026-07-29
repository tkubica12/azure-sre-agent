output "log_analytics_id" {
  description = "Full resource ID of the Log Analytics workspace."
  value       = azurerm_log_analytics_workspace.this.id
}

output "log_analytics_name" {
  description = "Name of the Log Analytics workspace."
  value       = azurerm_log_analytics_workspace.this.name
}

output "log_analytics_workspace_id" {
  description = "The workspace's GUID-formatted customer/workspace ID, used for Log Analytics query API calls."
  value       = azurerm_log_analytics_workspace.this.workspace_id
}

output "app_insights_id" {
  description = "Full resource ID of the Application Insights resource."
  value       = azurerm_application_insights.this.id
}

output "app_insights_name" {
  description = "Name of the Application Insights resource."
  value       = azurerm_application_insights.this.name
}

output "app_insights_app_id" {
  description = "Application Insights application ID, used for the Application Insights query API."
  value       = azurerm_application_insights.this.app_id
}

output "app_insights_connection_string" {
  description = "Application Insights connection string. Not treated as a secret by Azure (it identifies an ingestion endpoint, not a credential), but kept out of plain console output by callers where practical."
  value       = azurerm_application_insights.this.connection_string
  sensitive   = true
}

output "app_insights_instrumentation_key" {
  description = "Legacy instrumentation key, retained for tools that do not yet accept a connection string."
  value       = azurerm_application_insights.this.instrumentation_key
  sensitive   = true
}
