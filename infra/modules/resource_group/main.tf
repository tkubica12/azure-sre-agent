// Minimal, reusable resource group module.
//
// Used by infra/environments/demo to create the agent and workload resource
// groups described in SPEC.md section 6. Kept intentionally small: naming,
// location, and tagging are the only concerns owned here.

resource "azurerm_resource_group" "this" {
  name     = var.name
  location = var.location
  tags     = var.tags
}
