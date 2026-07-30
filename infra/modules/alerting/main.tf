// Real Azure Monitor alerting for the bad-deployment scenario (see
// SPEC.md sections 5 and 6). The action group intentionally carries no
// secrets: it has zero receivers unless an operator supplies
// `notification_email`, and even then only a plain email address (not a
// credential) is stored. The metric alert is the mechanism that eventually
// reaches the Azure SRE Agent's Azure Monitor incident workflow in
// Milestone 3.

resource "azurerm_monitor_action_group" "this" {
  name                = var.action_group_name
  resource_group_name = var.resource_group_name
  short_name          = var.action_group_short_name
  tags                = var.tags

  dynamic "email_receiver" {
    for_each = var.notification_email != "" ? [var.notification_email] : []
    content {
      name                    = "operator"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}

// Requests, split by statusCodeCategory, is the documented metric for
// Microsoft.App/containerApps (verified against
// https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-app-containerapps-metrics
// on the date recorded in PLAN.md). "5xx" is the exact dimension value
// Azure Monitor reports for server-error responses.
resource "azurerm_monitor_metric_alert" "containerapp_5xx" {
  name                = var.alert_name
  resource_group_name = var.resource_group_name
  scopes              = [var.container_app_id]
  description         = "PulseMart Container App is returning HTTP 5xx responses; determine the failing operation from telemetry."
  severity            = var.severity
  window_size         = var.window_size
  frequency           = var.frequency
  tags                = var.tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Requests"
    aggregation      = "Total"
    operator         = "GreaterThanOrEqual"
    threshold        = var.threshold

    dimension {
      name     = "statusCodeCategory"
      operator = "Include"
      values   = ["5xx"]
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.this.id
  }
}
