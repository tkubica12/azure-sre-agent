// Consumption-only Container Apps environment. Azure always reports back an
// implicit "Consumption" workload_profile even when the resource is created
// without one; declaring it explicitly here (rather than omitting the
// block) keeps `terraform plan` at zero changes on repeat applies instead
// of perpetually proposing to remove a profile Azure keeps re-adding. This
// still matches AGENTS.md's cost guidance to prefer scale-to-zero: the
// Consumption profile itself has no minimum reserved capacity. Logs stream
// to the shared Log Analytics workspace so ContainerAppConsoleLogs_CL
// carries the structured JSON stdout logs PulseMart emits (see
// app/pulsemart/telemetry.py).

resource "azurerm_container_app_environment" "this" {
  name                       = var.name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  logs_destination           = "log-analytics"
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}
