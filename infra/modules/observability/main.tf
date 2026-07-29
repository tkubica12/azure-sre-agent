// Workspace-based Application Insights: Log Analytics is the sole storage
// backend, and Application Insights is the request/trace/dependency query
// experience on top of it (see SPEC.md section 6). This is the only
// currently supported Application Insights creation mode; the legacy
// "classic" (non-workspace-based) mode is deprecated.

resource "azurerm_log_analytics_workspace" "this" {
  name                = var.log_analytics_name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  daily_quota_gb      = var.daily_quota_gb
  tags                = var.tags
}

resource "azurerm_application_insights" "this" {
  name                = var.app_insights_name
  resource_group_name = var.resource_group_name
  location            = var.location
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
  tags                = var.tags
}
