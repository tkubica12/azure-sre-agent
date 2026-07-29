// Azure Container Registry used exclusively for `az acr build` cloud builds
// of the PulseMart image (see SPEC.md section 8: "a local Docker daemon is
// not required"). Admin credentials stay disabled; the workload pulls
// images using its user-assigned managed identity and an AcrPull role
// assignment (infra/modules/workload_identity), never a registry password.

resource "azurerm_container_registry" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku
  admin_enabled       = false
  tags                = var.tags
}
