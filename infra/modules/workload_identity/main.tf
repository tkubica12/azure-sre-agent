// User-assigned managed identity for the PulseMart Container App. Grants
// only `AcrPull` at the single registry's scope so the Container App can
// pull images without a registry password (see SPEC.md section 9:
// "Container App identity | ACR | AcrPull"). This identity is intentionally
// unrelated to the Azure SRE Agent's own identities, which are created in
// Milestone 3.

resource "azurerm_user_assigned_identity" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
}
