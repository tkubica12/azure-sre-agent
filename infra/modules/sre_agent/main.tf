// Azure SRE Agent (Microsoft.App/agents), its identities, connectors, and
// RBAC (see SPEC.md sections 6 and 9, and PLAN.md Milestone 3). Resource
// shapes mirror the official Microsoft Terraform template
// (https://github.com/microsoft/sre-agent/tree/main/sreagent-templates/terraform),
// adapted to reuse this repository's existing resource-group/observability
// modules and the workload resources created in Milestone 2, and to apply
// the RBAC set defined in SPEC.md section 9.

data "azurerm_client_config" "current" {}
data "azurerm_subscription" "current" {}

resource "azurerm_user_assigned_identity" "agent" {
  name                = "${var.name}-uami"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azapi_resource" "agent" {
  schema_validation_enabled = false
  type                      = "Microsoft.App/agents@2025-05-01-preview"
  name                      = var.name
  location                  = var.location
  parent_id                 = var.resource_group_id
  tags                      = var.tags

  # Export the real ARM-reported data-plane endpoint rather than guessing a
  # URL pattern: live testing showed `properties.agentEndpoint` includes
  # per-deployment hash suffixes (e.g.
  # "https://<name>--<hash>.<hash2>.<region>.azuresre.ai") that a naive
  # "https://<name>.<region>.azuresre.ai" pattern does not predict.
  response_export_values = ["properties.agentEndpoint", "properties.provisioningState"]

  identity {
    type         = "SystemAssigned, UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.agent.id]
  }

  body = {
    properties = {
      knowledgeGraphConfiguration = {
        identity         = azurerm_user_assigned_identity.agent.id
        managedResources = [var.workload_resource_group_id]
      }
      actionConfiguration = {
        accessLevel = var.access_level
        mode        = var.action_mode
        identity    = azurerm_user_assigned_identity.agent.id
      }
      logConfiguration = {
        applicationInsightsConfiguration = {
          appId            = var.agent_app_insights_app_id
          connectionString = var.agent_app_insights_connection_string
        }
      }
      upgradeChannel        = var.upgrade_channel
      monthlyAgentUnitLimit = var.monthly_agent_unit_limit
      defaultModel = {
        provider = var.default_model_provider
        name     = var.default_model_name
      }
      # Required by the demo's Milestone 4 data-plane content. The official
      # Microsoft template enables all three; EnableV2AgentLoop in particular
      # backs approval hooks, which the Review-mode safety story depends on.
      experimentalSettings = {
        EnableWorkspaceTools = true
        EnableHttpTriggers   = true
        EnableV2AgentLoop    = true
      }
    }
  }

  # The agent's own identities must be able to read the workload resource
  # group before the agent starts using them (see SPEC.md section 9). The
  # narrower, access-level-dependent grants below (Container Apps
  # Contributor / broad Contributor) are not hard dependencies of agent
  # creation itself.
  depends_on = [
    azurerm_role_assignment.uami_workload_reader,
    azurerm_role_assignment.uami_workload_log_reader,
  ]

  timeouts {
    create = "10m"
    update = "10m"
    delete = "10m"
  }
}

# Typed connector properties (see PLAN.md Milestone 3 and the official
# template's `local.toggle_connectors`/`local.all_connectors`). Skills,
# subagents, common prompts, and other data-plane content are deliberately
# deferred to Milestone 4 (see SPEC.md section 10 and AGENTS.md).
locals {
  connectors = {
    "app-insights" = {
      dataConnectorType = "AppInsights"
      dataSource        = var.workload_app_insights_id
      extendedProperties = {
        armResourceId = var.workload_app_insights_id
        resource = {
          name = element(split("/", var.workload_app_insights_id), length(split("/", var.workload_app_insights_id)) - 1)
        }
        appId = var.workload_app_insights_app_id
      }
      identity = "system"
    }
    "log-analytics" = {
      dataConnectorType = "LogAnalytics"
      dataSource        = var.workload_log_analytics_id
      extendedProperties = {
        armResourceId = var.workload_log_analytics_id
        resource = {
          name = element(split("/", var.workload_log_analytics_id), length(split("/", var.workload_log_analytics_id)) - 1)
        }
      }
      identity = "system"
    }
    "azure-monitor" = {
      dataConnectorType = "AzureMonitor"
      dataSource        = data.azurerm_subscription.current.id
      extendedProperties = {
        armResourceId = data.azurerm_subscription.current.id
        lookbackDays  = var.azure_monitor_lookback_days
      }
      identity = "system"
    }
  }
}

resource "azapi_resource" "connector" {
  for_each                  = local.connectors
  schema_validation_enabled = false
  type                      = "Microsoft.App/agents/connectors@2025-05-01-preview"
  name                      = each.key
  parent_id                 = azapi_resource.agent.id

  body = {
    properties = each.value
  }

  # Connector PUTs are asynchronous and can take 10-30 minutes in the
  # background (documented Azure SRE Agent behavior). Terraform's own wait is
  # capped so `terraform apply` cannot hang indefinitely; a timeout here is
  # not treated as final failure by `labctl deploy`, which reconciles
  # Terraform state and then polls each connector to a terminal state
  # directly against Azure with its own bounded overall deadline (see
  # SPEC.md section 11 and labctl/src/labctl/agent_azure.py).
  timeouts {
    create = var.connector_timeout
    update = var.connector_timeout
    delete = var.connector_timeout
  }
}

# --------------------------------------------------------------------------
# Incident platform (properties.incidentManagementConfiguration) is
# deliberately NOT managed by Terraform.
#
# This field is not part of `azapi_resource.agent`'s `body` above.
# Live-proven (2026-07-29, see PLAN.md Milestone 3 "B1 fix"): the ARM
# provider for Microsoft.App/agents replaces the entire `properties` object
# on every PUT with whatever `body` contains, so any unrelated
# `terraform apply` -- one that only touches, say, `monthlyAgentUnitLimit`
# -- silently nulls out `incidentManagementConfiguration` if it had been set
# out-of-band. That broke alert routing without any error, defeating the
# "repeatable deploy" contract in AGENTS.md.
#
# A Terraform-native fix was tried first: `azapi_update_resource`, the AzAPI
# provider's resource for managing a *subset* of an existing resource's
# properties. It failed live (2026-07-29) with ARM error
# `MismatchingResourceIdentityPrincipalId`: despite being documented as a
# partial-property PATCH, it actually issues a read-merge-PUT under the
# hood, and the merged body echoed back this agent's own system-assigned
# identity `principalId`, which ARM rejects on write (that field is
# server-computed and read-only). See docs/adr/0001-incident-platform-reconciliation.md
# for the full comparison and decision.
#
# `labctl deploy` now owns this field instead: right after `terraform apply`
# succeeds, it PATCHes `properties.incidentManagementConfiguration` via
# `az rest` (a real HTTP PATCH, not a PUT) and is idempotent -- a no-op when
# already correct -- so it is safe on every run, including the "reconcile
# after a tolerated connector timeout" re-apply. See
# labctl/src/labctl/deploy.py's `_reconcile_incident_platform` and
# labctl/src/labctl/agent_azure.py's `set_incident_platform`. `labctl
# provision` never PATCHes this field itself; it only reads it back to
# confirm `labctl deploy` already configured it, so there is exactly one
# writer.

# --------------------------------------------------------------------------
# RBAC: agent UAMI and system-assigned identity on the workload RG (see
# SPEC.md section 9's identity and permissions table). Every ServicePrincipal
# assignment skips the AAD existence check because the corresponding
# identity is created in this same apply and can lag AAD propagation,
# otherwise causing a spurious "PrincipalNotFound" failure on the first run.
# --------------------------------------------------------------------------

resource "azurerm_role_assignment" "uami_workload_reader" {
  scope                            = var.workload_resource_group_id
  role_definition_name             = "Reader"
  principal_id                     = azurerm_user_assigned_identity.agent.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "uami_workload_log_reader" {
  scope                            = var.workload_resource_group_id
  role_definition_name             = "Log Analytics Reader"
  principal_id                     = azurerm_user_assigned_identity.agent.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "uami_workload_contributor" {
  count                            = var.workload_access_level == "broad" ? 1 : 0
  scope                            = var.workload_resource_group_id
  role_definition_name             = "Contributor"
  principal_id                     = azurerm_user_assigned_identity.agent.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "system_workload_reader" {
  scope                            = var.workload_resource_group_id
  role_definition_name             = "Reader"
  principal_id                     = azapi_resource.agent.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "system_workload_log_reader" {
  scope                            = var.workload_resource_group_id
  role_definition_name             = "Log Analytics Reader"
  principal_id                     = azapi_resource.agent.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "system_workload_contributor" {
  count                            = var.workload_access_level == "broad" ? 1 : 0
  scope                            = var.workload_resource_group_id
  role_definition_name             = "Contributor"
  principal_id                     = azapi_resource.agent.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

# Narrow default (var.workload_access_level == "narrow"): let the agent
# create Container App revisions and shift traffic (a rollback) without
# granting it Contributor over the ACR, Log Analytics workspace, alert
# rules, or anything else in the workload resource group. "Container Apps
# Contributor" is a genuine built-in role (verified live 2026-07-29 via `az
# role definition list --name "Container Apps Contributor"`; an earlier
# review incorrectly claimed otherwise -- see SPEC.md section 9 and PLAN.md).
resource "azurerm_role_assignment" "uami_workload_container_apps_contributor" {
  count                            = var.workload_access_level == "narrow" ? 1 : 0
  scope                            = var.workload_container_app_id
  role_definition_name             = "Container Apps Contributor"
  principal_id                     = azurerm_user_assigned_identity.agent.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "system_workload_container_apps_contributor" {
  count                            = var.workload_access_level == "narrow" ? 1 : 0
  scope                            = var.workload_container_app_id
  role_definition_name             = "Container Apps Contributor"
  principal_id                     = azapi_resource.agent.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

# --------------------------------------------------------------------------
# RBAC: alert lifecycle (acknowledge/close). Azure Monitor alert instances
# (Microsoft.AlertsManagement/alerts) are subscription-scoped resources, not
# contained by any resource group, so a role assignment at the workload
# resource group cannot grant permission on them -- Azure RBAC only inherits
# downward through the ARM containment hierarchy. A deployment-unique custom
# role grants only the two alert-instance actions the agent needs. Actions run
# as the UAMI configured in properties.actionConfiguration.identity above, so
# this subscription-scoped alert-lifecycle grant is intentionally not duplicated
# to the system-assigned identity. The official Microsoft template additionally
# grants the UAMI "Monitoring Reader" on the agent's own resource group; matched
# here for parity.
# --------------------------------------------------------------------------

locals {
  alert_lifecycle_role_name = "Azure SRE Agent Alert Lifecycle - ${var.name} - ${var.tags.deployment_id}"
}

resource "azurerm_role_definition" "alert_lifecycle" {
  name        = local.alert_lifecycle_role_name
  scope       = data.azurerm_subscription.current.id
  description = "Azure SRE Agent demo alert read/change-state only for ${var.name} (${var.tags.deployment_id})."

  permissions {
    actions = [
      "Microsoft.AlertsManagement/alerts/read",
      "Microsoft.AlertsManagement/alerts/changestate/action",
    ]
    not_actions = []
  }

  assignable_scopes = [
    data.azurerm_subscription.current.id,
  ]
}

resource "azurerm_role_assignment" "uami_subscription_alert_lifecycle" {
  scope                            = data.azurerm_subscription.current.id
  role_definition_id               = azurerm_role_definition.alert_lifecycle.role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.agent.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "uami_agent_rg_monitoring_reader" {
  scope                            = var.resource_group_id
  role_definition_name             = "Monitoring Reader"
  principal_id                     = azurerm_user_assigned_identity.agent.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

# --------------------------------------------------------------------------
# RBAC: "SRE Agent Administrator" on the agent resource itself.
#
# The deployer (current signed-in principal) always gets this role -- it is
# required to manage the agent via the data-plane API (skills, hooks,
# response plans, etc.) and to approve/deny pending actions in the portal.
#
# The agent's own UAMI does NOT get this role by default (see
# `var.grant_uami_agent_administrator`). This was tested as a plausible
# self-approval fix for the Review-mode approval gate never visibly
# engaging on real incident-driven mutating actions (`GET
# /api/v1/approvals/{threadId}` stayed empty across every write) and found
# insufficient alone: live-verified 2026-07-29 (PLAN.md Milestone 5), a
# second full incident cycle with this grant removed and a genuinely fresh
# Review-mode thread still executed the mutating write unattended. Removing
# the grant is kept as ordinary least-privilege practice regardless (an
# agent identity has no legitimate reason to administer its own agent
# resource), but it is not claimed as a fix for the approval-gate behavior.
# See SPEC.md section 9 and PLAN.md Milestone 5 for the full evidence trail.
# --------------------------------------------------------------------------

resource "azurerm_role_assignment" "deployer_agent_admin" {
  scope                = azapi_resource.agent.id
  role_definition_name = "SRE Agent Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "uami_agent_admin" {
  count                            = var.grant_uami_agent_administrator ? 1 : 0
  scope                            = azapi_resource.agent.id
  role_definition_name             = "SRE Agent Administrator"
  principal_id                     = azurerm_user_assigned_identity.agent.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}
