// Declares the non-default-namespace provider this module uses directly
// (Microsoft.App/agents requires azapi; see AGENTS.md "Use the AzAPI
// provider for Azure SRE Agent"). Version pinning stays solely in
// infra/environments/demo/versions.tf (see AGENTS.md "Pin Terraform and
// provider versions deliberately").
terraform {
  required_providers {
    azapi = {
      source = "azure/azapi"
    }
  }
}
