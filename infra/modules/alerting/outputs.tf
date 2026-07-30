output "action_group_id" {
  description = "Full resource ID of the action group."
  value       = azurerm_monitor_action_group.this.id
}

output "metric_alert_id" {
  description = "Full resource ID of the Container App 5xx metric alert rule."
  value       = azurerm_monitor_metric_alert.containerapp_5xx.id
}

output "metric_alert_name" {
  description = "Name of the Container App 5xx metric alert rule."
  value       = azurerm_monitor_metric_alert.containerapp_5xx.name
}
