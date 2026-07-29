"""Typed runtime configuration for PulseMart, sourced entirely from
environment variables so the same immutable container image behaves
differently only through Container Apps revision configuration (see
SPEC.md section 7 and AGENTS.md "Real workload and incidents").

No configuration value here is a secret. Application Insights authentication
uses ``APPLICATIONINSIGHTS_CONNECTION_STRING``, which is read directly by the
Azure Monitor OpenTelemetry distro and is not treated as sensitive by Azure
(it identifies an ingestion endpoint, not a credential).
"""

from __future__ import annotations

import socket

from pydantic_settings import BaseSettings, SettingsConfigDict

#: The only supported non-empty value for DEMO_FAILURE_MODE today. Any other
#: non-empty value is rejected at startup so a typo cannot silently produce a
#: healthy app when a failure was intended, or vice versa.
FAILURE_MODE_CHECKOUT_500 = "checkout-500"
SUPPORTED_FAILURE_MODES = frozenset({"", FAILURE_MODE_CHECKOUT_500})


class Settings(BaseSettings):
    """Environment-driven settings. Field names map to env vars of the same
    name (case-insensitive), see ``model_config`` below.
    """

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    # Identity of this specific deployment. `labctl deploy` sets these when it
    # creates a new Container Apps revision from the immutable ACR image.
    pulsemart_release: str = "local-dev"
    pulsemart_environment: str = "local"

    # Azure Container Apps injects CONTAINER_APP_REVISION automatically; it is
    # the most reliable revision identifier because it comes from the
    # platform rather than from labctl's own bookkeeping. See
    # https://learn.microsoft.com/azure/container-apps/environment-variables
    container_app_revision: str = ""
    container_app_name: str = ""

    # The demo's single, non-public fault switch. Never exposed through any
    # HTTP endpoint; it can only be set via Container Apps revision
    # configuration by an authenticated operator (see AGENTS.md).
    demo_failure_mode: str = ""

    pulsemart_log_level: str = "INFO"

    def revision(self) -> str:
        return self.container_app_revision or socket.gethostname()

    def failure_mode_active(self) -> bool:
        return self.demo_failure_mode == FAILURE_MODE_CHECKOUT_500


def load_settings() -> Settings:
    settings = Settings()
    if settings.demo_failure_mode not in SUPPORTED_FAILURE_MODES:
        raise ValueError(
            f"Unsupported DEMO_FAILURE_MODE={settings.demo_failure_mode!r}. "
            f"Supported values: {sorted(SUPPORTED_FAILURE_MODES)!r}."
        )
    return settings


__all__ = [
    "FAILURE_MODE_CHECKOUT_500",
    "SUPPORTED_FAILURE_MODES",
    "Settings",
    "load_settings",
]
