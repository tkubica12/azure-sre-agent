variable "name" {
  description = "Name of the Container App."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create the Container App in."
  type        = string
}

variable "container_app_environment_id" {
  description = "Resource ID of the Container Apps environment to deploy into."
  type        = string
}

variable "identity_id" {
  description = "Resource ID of the user-assigned managed identity used for AcrPull image pulls."
  type        = string
}

variable "acr_login_server" {
  description = "Login server hostname of the Azure Container Registry (e.g. myregistry.azurecr.io)."
  type        = string
}

variable "app_insights_connection_string" {
  description = "Application Insights connection string, passed to the container as an environment variable so the Azure Monitor OpenTelemetry distro can export telemetry."
  type        = string
  sensitive   = true
}

variable "environment_name" {
  description = "Value of the PULSEMART_ENVIRONMENT environment variable exposed through GET /api/status."
  type        = string
  default     = "demo"
}

variable "bootstrap_image" {
  description = "Stable public image used only for the initial Terraform apply, before `labctl deploy` builds and switches to the real ACR image (see SPEC.md section 8 'Deployment sequence')."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}

variable "target_port" {
  description = "TCP port the PulseMart container listens on (see app/Dockerfile EXPOSE)."
  type        = number
  default     = 8000
}

variable "cpu" {
  description = "vCPU allocated to the single container. Must combine with `memory` into a supported Consumption-plan allocation."
  type        = number
  default     = 0.25
}

variable "memory" {
  description = "Memory allocated to the single container. Must combine with `cpu` into a supported Consumption-plan allocation."
  type        = string
  default     = "0.5Gi"
}

variable "min_replicas" {
  description = "Minimum replica count. 0 allows scale-to-zero when idle (see AGENTS.md cost guidance); the demo's own traffic and health probes keep it warm during a rehearsal."
  type        = number
  default     = 0
}

variable "max_replicas" {
  description = "Maximum replica count, bounded to keep the demo inexpensive."
  type        = number
  default     = 2
}

variable "tags" {
  description = "Tags applied to the Container App so ownership and cleanup scope are provable."
  type        = map(string)
  default     = {}
}
