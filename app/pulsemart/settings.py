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

#: Supported payment-gateway profiles. Any unsupported value is rejected at
#: startup so a typo cannot silently produce a healthy app when a checkout
#: regression was intended, or vice versa.
PAYMENT_GATEWAY_PROFILE_STANDARD = "standard"
PAYMENT_GATEWAY_PROFILE_LEGACY_ACQUIRER = "legacy-acquirer"
SUPPORTED_PAYMENT_GATEWAY_PROFILES = frozenset(
    {PAYMENT_GATEWAY_PROFILE_STANDARD, PAYMENT_GATEWAY_PROFILE_LEGACY_ACQUIRER}
)

CHECKOUT_PRICING_PROFILE_STANDARD = "standard"
CHECKOUT_PRICING_PROFILE_STRICT_DECIMAL = "strict-decimal"
SUPPORTED_CHECKOUT_PRICING_PROFILES = frozenset(
    {CHECKOUT_PRICING_PROFILE_STANDARD, CHECKOUT_PRICING_PROFILE_STRICT_DECIMAL}
)


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

    # Non-public payment dependency profile. Never exposed through any HTTP
    # endpoint; it can only be set via Container Apps revision configuration
    # by an authenticated operator (see AGENTS.md).
    payment_gateway_profile: str = PAYMENT_GATEWAY_PROFILE_STANDARD
    checkout_pricing_profile: str = CHECKOUT_PRICING_PROFILE_STANDARD

    pulsemart_log_level: str = "INFO"

    def revision(self) -> str:
        return self.container_app_revision or socket.gethostname()

    def payment_gateway_regression_active(self) -> bool:
        return self.payment_gateway_profile == PAYMENT_GATEWAY_PROFILE_LEGACY_ACQUIRER

    def checkout_pricing_regression_active(self) -> bool:
        return self.checkout_pricing_profile == CHECKOUT_PRICING_PROFILE_STRICT_DECIMAL


def load_settings() -> Settings:
    settings = Settings()
    if settings.payment_gateway_profile not in SUPPORTED_PAYMENT_GATEWAY_PROFILES:
        raise ValueError(
            f"Unsupported PAYMENT_GATEWAY_PROFILE={settings.payment_gateway_profile!r}. "
            f"Supported values: {sorted(SUPPORTED_PAYMENT_GATEWAY_PROFILES)!r}."
        )
    if settings.checkout_pricing_profile not in SUPPORTED_CHECKOUT_PRICING_PROFILES:
        raise ValueError(
            f"Unsupported CHECKOUT_PRICING_PROFILE={settings.checkout_pricing_profile!r}. "
            f"Supported values: {sorted(SUPPORTED_CHECKOUT_PRICING_PROFILES)!r}."
        )
    return settings


__all__ = [
    "CHECKOUT_PRICING_PROFILE_STANDARD",
    "CHECKOUT_PRICING_PROFILE_STRICT_DECIMAL",
    "PAYMENT_GATEWAY_PROFILE_LEGACY_ACQUIRER",
    "PAYMENT_GATEWAY_PROFILE_STANDARD",
    "SUPPORTED_CHECKOUT_PRICING_PROFILES",
    "SUPPORTED_PAYMENT_GATEWAY_PROFILES",
    "Settings",
    "load_settings",
]
