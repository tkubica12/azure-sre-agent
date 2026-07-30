// PulseMart Container App in Multiple revision mode (see SPEC.md section 7).
//
// Terraform intentionally ignores changes to `template` and `ingress` after
// the initial apply. `labctl deploy` builds the real image with `az acr
// build`, then uses `az containerapp update`/`az containerapp ingress
// traffic set` to create the immutable baseline revision and control 100%
// traffic. `labctl demo trigger`/`reset` do the same for the scenario
// revision. If Terraform reconciled either block, a later `terraform apply`
// would silently revert an approved rollback or the demo's known-good state
// back to this bootstrap configuration (see AGENTS.md "Terraform drift from
// scenario changes"). Re-running `labctl deploy`'s Terraform step is
// therefore safe at any time: it never fights the Azure CLI-owned revision
// or traffic state.
resource "azurerm_container_app" "this" {
  name                         = var.name
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.container_app_environment_id
  revision_mode                = "Multiple"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server   = var.acr_login_server
    identity = var.identity_id
  }

  ingress {
    external_enabled = true
    target_port      = var.target_port
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "pulsemart"
      image  = var.bootstrap_image
      cpu    = var.cpu
      memory = var.memory

      env {
        name  = "PULSEMART_ENVIRONMENT"
        value = var.environment_name
      }
      env {
        name  = "PULSEMART_RELEASE"
        value = "bootstrap"
      }
      env {
        name  = "PAYMENT_GATEWAY_PROFILE"
        value = "standard"
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "app-insights-connection-string"
      }
    }
  }

  secret {
    name  = "app-insights-connection-string"
    value = var.app_insights_connection_string
  }

  lifecycle {
    ignore_changes = [
      template,
      ingress,
      # Azure auto-populates workload_profile_name to "Consumption" for
      # Consumption-only environments regardless of whether it was set
      # explicitly; ignoring it avoids a perpetual no-op-equivalent diff.
      workload_profile_name,
    ]
  }
}
