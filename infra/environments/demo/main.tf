# Root module for the Azure SRE Agent demonstration environment.
#
# Milestone 1 provisioned only the two owning resource groups. Milestone 2
# added the PulseMart workload: registry, observability, identity, Container
# Apps environment/app, and checkout-failure alerting, all in the workload
# resource group (see SPEC.md sections 6-9). Milestone 3 adds the Azure SRE
# Agent itself, its own identities and telemetry, connectors to the workload
# telemetry, and RBAC, all in the agent resource group.

module "agent_resource_group" {
  source = "../../modules/resource_group"

  name     = var.agent_resource_group_name
  location = var.region
  tags     = var.tags
}

module "workload_resource_group" {
  source = "../../modules/resource_group"

  name     = var.workload_resource_group_name
  location = var.region
  tags     = var.tags
}

# Azure Container Registry names must be globally unique and alphanumeric
# only. A stable random suffix (persisted in Terraform state, unchanged
# across re-applies) keeps the name deterministic for this deployment
# without operator input.
resource "random_string" "acr_suffix" {
  length  = 6
  special = false
  upper   = false
  numeric = true
}

module "container_registry" {
  source = "../../modules/container_registry"

  name                = "crpulsemartdemo${random_string.acr_suffix.result}"
  resource_group_name = module.workload_resource_group.name
  location            = var.region
  tags                = var.tags
}

module "observability" {
  source = "../../modules/observability"

  log_analytics_name  = "law-pulsemart-demo"
  app_insights_name   = "appi-pulsemart-demo"
  resource_group_name = module.workload_resource_group.name
  location            = var.region
  retention_in_days   = var.log_retention_days
  tags                = var.tags
}

module "workload_identity" {
  source = "../../modules/workload_identity"

  name                = "id-pulsemart-workload-demo"
  resource_group_name = module.workload_resource_group.name
  location            = var.region
  acr_id              = module.container_registry.id
  tags                = var.tags
}

module "container_apps_environment" {
  source = "../../modules/container_apps_environment"

  name                       = "cae-pulsemart-demo"
  resource_group_name        = module.workload_resource_group.name
  location                   = var.region
  log_analytics_workspace_id = module.observability.log_analytics_id
  tags                       = var.tags
}

module "container_app" {
  source = "../../modules/container_app"

  name                           = "ca-pulsemart-demo"
  resource_group_name            = module.workload_resource_group.name
  container_app_environment_id   = module.container_apps_environment.id
  identity_id                    = module.workload_identity.id
  acr_login_server               = module.container_registry.login_server
  app_insights_connection_string = module.observability.app_insights_connection_string
  environment_name               = var.tags.environment
  tags                           = var.tags
}

module "alerting" {
  source = "../../modules/alerting"

  resource_group_name     = module.workload_resource_group.name
  action_group_name       = "ag-pulsemart-alerts-demo"
  action_group_short_name = "pulsemart"
  notification_email      = var.alert_notification_email
  container_app_id        = module.container_app.id
  alert_name              = "alert-pulsemart-containerapp-5xx"
  threshold               = var.alert_threshold_5xx
  tags                    = var.tags
}

# Agent telemetry is deliberately separate from workload telemetry (see
# SPEC.md section 6 "Azure resources"): the agent's own Log Analytics
# workspace and Application Insights resource record its audit and
# operational activity, distinct from what it observes in the workload.
module "agent_observability" {
  source = "../../modules/observability"

  log_analytics_name  = "law-sre-agent-demo"
  app_insights_name   = "appi-sre-agent-demo"
  resource_group_name = module.agent_resource_group.name
  location            = var.region
  retention_in_days   = var.log_retention_days
  tags                = var.tags
}

module "sre_agent" {
  source = "../../modules/sre_agent"

  name                = var.agent_name
  resource_group_name = module.agent_resource_group.name
  resource_group_id   = module.agent_resource_group.id
  location            = var.region
  tags                = var.tags

  workload_resource_group_id   = module.workload_resource_group.id
  workload_app_insights_id     = module.observability.app_insights_id
  workload_app_insights_app_id = module.observability.app_insights_app_id
  workload_log_analytics_id    = module.observability.log_analytics_id
  workload_container_app_id    = module.container_app.id
  workload_access_level        = var.agent_workload_access_level

  agent_app_insights_app_id            = module.agent_observability.app_insights_app_id
  agent_app_insights_connection_string = module.agent_observability.app_insights_connection_string

  upgrade_channel          = var.agent_upgrade_channel
  monthly_agent_unit_limit = var.agent_monthly_aau_allocation
  default_model_provider   = var.agent_model_provider
  default_model_name       = var.agent_model_name
}
