"""FastAPI application factory and HTTP routes for PulseMart.

Routes match SPEC.md section 7 exactly:

- ``GET /`` self-contained HTML status/checkout dashboard.
- ``GET /healthz`` liveness/readiness probe, always healthy.
- ``GET /api/status`` machine-readable release/revision status.
- ``POST /api/checkout`` the synthetic checkout journey.

There is deliberately no endpoint that can change payment dependency behavior:
the fault is a Container Apps revision environment variable, changed only
through authenticated Azure control-plane operations by ``labctl`` (see
AGENTS.md "Real workload and incidents").
"""

from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, JSONResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from pulsemart import __version__
from pulsemart.settings import Settings, load_settings
from pulsemart.telemetry import configure_logging, configure_telemetry

_START_TIME = time.monotonic()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    logger = configure_logging(settings)
    tracer = configure_telemetry(settings)

    app = FastAPI(title="PulseMart", version=__version__)

    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        # See telemetry.configure_telemetry: automatic instrumentation is
        # disabled and this concrete app instance is instrumented explicitly
        # instead, so `requests`/server spans reliably reach Application
        # Insights under the `uvicorn ... --factory` deployment model.
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)

    app.state.settings = settings
    app.state.logger = logger
    app.state.tracer = tracer

    dashboard_html = (
        resources.files("pulsemart")
        .joinpath("templates/dashboard.html")
        .read_text(encoding="utf-8")
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> str:
        return dashboard_html

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        # Always available during the checkout regression: SPEC.md requires
        # health/admin endpoints to keep working while checkout fails.
        return {"status": "ok"}

    @app.get("/api/status")
    async def api_status() -> dict[str, Any]:
        return {
            "service": "pulsemart",
            "release": settings.pulsemart_release,
            "revision": settings.revision(),
            "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @app.post("/api/checkout")
    async def api_checkout() -> Response:
        order_id = str(uuid.uuid4())
        log_extra = {
            "order_id": order_id,
        }

        with tracer.start_as_current_span("checkout") as checkout_span:
            checkout_span.set_attribute("order.id", order_id)
            checkout_span.set_attribute("service.release", settings.pulsemart_release)
            checkout_span.set_attribute("service.revision", settings.revision())

            await _check_inventory(tracer, order_id)

            try:
                await _charge_payment(tracer, order_id, settings)
            except UpstreamPaymentGatewayError as exc:
                checkout_span.record_exception(exc)
                checkout_span.set_status(Status(StatusCode.ERROR, str(exc)))
                logger.error("checkout failed: %s", exc, extra=log_extra)
                return JSONResponse(
                    status_code=500,
                    content={
                        "order_id": order_id,
                        "status": "failed",
                        "error": "payment authorization temporarily unavailable",
                    },
                )

            logger.info("checkout succeeded", extra=log_extra)
            return JSONResponse(
                status_code=200,
                content={
                    "order_id": order_id,
                    "status": "confirmed",
                    "amount_usd": round(random.uniform(12.0, 240.0), 2),
                },
            )

    return app


class UpstreamPaymentGatewayError(RuntimeError):
    """Raised when the simulated payment dependency rejects authorization."""


async def _check_inventory(tracer: trace.Tracer, order_id: str) -> None:
    """Simulate an inventory-service dependency call. Always succeeds; this
    span is present in both the healthy and failing paths so an operator can
    see the failure is isolated to payment processing.
    """

    with tracer.start_as_current_span("inventory.check") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("peer.service", "inventory-service")
        await asyncio.sleep(random.uniform(0.01, 0.03))
        span.set_attribute("inventory.available", True)


async def _charge_payment(tracer: trace.Tracer, order_id: str, settings: Settings) -> None:
    """Simulate a payment-gateway dependency call."""

    with tracer.start_as_current_span("payment.charge") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("peer.service", "payment-gateway")
        await asyncio.sleep(random.uniform(0.02, 0.05))
        if settings.payment_gateway_regression_active():
            span.set_attribute("payment.result", "error")
            raise UpstreamPaymentGatewayError(
                "upstream payment gateway returned HTTP 502 Bad Gateway "
                "while authorizing the charge"
            )
        span.set_attribute("payment.result", "approved")


__all__ = ["create_app", "UpstreamPaymentGatewayError"]
