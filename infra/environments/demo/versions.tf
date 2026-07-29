# Terraform and provider version pins for the Azure SRE Agent demonstration.
#
# Versions are pinned deliberately (see AGENTS.md "Infrastructure as code").
# Bump them intentionally, re-run `terraform init -upgrade`, and re-validate
# rather than floating on a range.

terraform {
  required_version = "= 1.10.1"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 4.81.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "= 2.11.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.9.0"
    }
  }

  # Terraform state stays local and git-ignored under the repository root's
  # .state/ directory (see AGENTS.md and SPEC.md section 8). No remote
  # backend is configured. The path below is relative to this working
  # directory (infra/environments/demo).
  backend "local" {
    path = "../../../.state/demo.tfstate"
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id != "" ? var.subscription_id : null
  tenant_id       = var.tenant_id != "" ? var.tenant_id : null

  features {
    resource_group {
      # Application Insights automatically provisions a "Failure Anomalies"
      # smart detector alert rule (microsoft.alertsmanagement/
      # smartDetectorAlertRules) outside of Terraform whenever a Component is
      # created. Terraform never manages that resource, so the default
      # `prevent_deletion_if_contains_resources = true` blocks resource-group
      # deletion during `labctl destroy` with "the Resource Group still
      # contains Resources" (live-verified 2026-07-29: this stalled a full
      # `terraform destroy` for the entire ~35-minute run before failing).
      # `labctl destroy`'s own ownership check already enumerates every
      # child resource in the resource group and refuses to proceed if any
      # resource is unrecognized (see `labctl/src/labctl/destroy.py`), so it
      # is safe to let the azurerm provider delete the resource group
      # directly via the Azure API rather than requiring every implicitly
      # created child resource to be modeled in Terraform.
      prevent_deletion_if_contains_resources = false
    }
  }

  # Resource provider registration (including Microsoft.App, required by the
  # Azure SRE Agent) is verified read-only by `labctl preflight` and, where
  # unavoidable, registered explicitly by the operator ahead of deployment.
  # Terraform is not granted implicit registration write access here.
  resource_provider_registrations = "none"
}

provider "azapi" {
  subscription_id = var.subscription_id != "" ? var.subscription_id : null
  tenant_id       = var.tenant_id != "" ? var.tenant_id : null
}
