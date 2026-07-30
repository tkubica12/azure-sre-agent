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

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "canary_regression" {
  name                    = var.canary_alert_name
  resource_group_name     = var.resource_group_name
  location                = var.location
  scopes                  = [var.app_insights_id]
  description             = "PulseMart checkout failure rate is elevated during a canary release; partition failures by Container App revision before acting."
  severity                = var.severity
  enabled                 = true
  evaluation_frequency    = var.frequency
  window_duration         = var.window_size
  auto_mitigation_enabled = true
  tags                    = var.tags

  criteria {
    query = <<-KQL
      requests
      | where name =~ "POST /api/checkout" or operation_Name =~ "POST /api/checkout"
      | extend weightedItemCount = tolong(coalesce(itemCount, 1))
      | summarize total=sum(weightedItemCount), failed=sumif(weightedItemCount, toint(resultCode) between (500 .. 599))
      | where total >= 30 and failed >= 3 and todouble(failed) / todouble(total) >= 0.05
    KQL

    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.this.id]
  }
}
