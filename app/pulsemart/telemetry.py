"""Observability wiring for PulseMart.

Two independent telemetry paths reach Azure, matching SPEC.md section 7:

1. Structured JSON logs on stdout, which the Container Apps environment
   forwards to the Log Analytics workspace (`ContainerAppConsoleLogs_CL`)
   because the environment's log destination is configured for Log
   Analytics in Terraform.
2. OpenTelemetry traces, requests, dependencies, exceptions, and logs
   exported directly to Application Insights via the Azure Monitor
   OpenTelemetry distro (``configure_azure_monitor``). FastAPI request spans
   are instrumented automatically by the distro; this module adds the
   process-wide resource attributes (release/revision/environment) and the
   tracer used for the custom checkout span.

Per Microsoft's guidance, FastAPI is an "officially supported" distro
instrumentation and must not be instrumented a second time manually (see
https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-add-modify).
"""

from __future__ import annotations

import logging
import os
import sys

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Tracer
from pythonjsonlogger.json import JsonFormatter

from pulsemart.settings import Settings

SERVICE_NAME = "pulsemart"
TRACER_NAME = "pulsemart.checkout"

_LOG_RECORD_EXTRA_FIELDS = (
    "release",
    "revision",
    "order_id",
)


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure structured JSON logging to stdout.

    Every record carries release/revision context so a log line is diagnosable
    on its own, without joining back to trace context, matching AGENTS.md's
    requirement for structured JSON logs.
    """

    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = JsonFormatter(
        "{asctime}{levelname}{name}{message}",
        style="{",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        static_fields={
            "service": SERVICE_NAME,
            "release": settings.pulsemart_release,
            "revision": settings.revision(),
        },
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.pulsemart_log_level.upper())

    # Quiet noisy third-party access logs; uvicorn's own request logging is
    # redundant with the OpenTelemetry request spans.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    return logging.getLogger(SERVICE_NAME)


def configure_telemetry(settings: Settings) -> Tracer:
    """Configure OpenTelemetry and return the application's tracer for
    custom spans.

    When ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set (every real Azure
    deployment), telemetry is exported to Application Insights through the
    Azure Monitor OpenTelemetry distro. When it is unset (local development
    and unit tests), a plain SDK ``TracerProvider`` with no exporter is used
    instead so spans can still be created without failing startup or
    reaching out to Azure.
    """

    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": settings.pulsemart_release,
            "service.instance.id": settings.revision(),
        }
    )

    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry import configure_azure_monitor

        # The distro's automatic class-level FastAPI instrumentation has been
        # observed (in this repository's own live Container Apps
        # deployment) to silently fail to attach when the app is created via
        # a factory function passed to uvicorn as a string
        # (`uvicorn pulsemart.main:create_app --factory`), which is exactly
        # how this app is served (see app/Dockerfile). Requests never
        # appeared in Application Insights even though custom spans, logs,
        # and dependencies did. Disabling the automatic instrumentation here
        # and instead calling `FastAPIInstrumentor.instrument_app(app)`
        # explicitly on the concrete app instance in `create_app` is the
        # documented manual-instrumentation path and reliably attaches the
        # ASGI middleware regardless of factory timing.
        configure_azure_monitor(
            resource=resource,
            logger_name=SERVICE_NAME,
            instrumentation_options={"fastapi": {"enabled": False}},
        )
    else:
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

    return trace.get_tracer(TRACER_NAME)


__all__ = [
    "SERVICE_NAME",
    "TRACER_NAME",
    "configure_logging",
    "configure_telemetry",
]
