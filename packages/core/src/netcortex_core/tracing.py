"""Sentry setup shared by the API and the worker. A no-op without SENTRY_DSN_BACKEND."""

import logging

from netcortex_core.settings import Settings, get_settings

log = logging.getLogger(__name__)


def init_sentry(service: str, settings: Settings | None = None) -> bool:
    """Start Sentry tracing for `service` ("api" or "worker"). Returns False if disabled."""
    settings = settings or get_settings()
    if not settings.sentry_dsn_backend:
        log.info("Sentry disabled: SENTRY_DSN_BACKEND is not set")
        return False
    import sentry_sdk
    from sentry_sdk.integrations.pydantic_ai import PydanticAIIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn_backend,
        traces_sample_rate=1.0,
        send_default_pii=False,
        environment="demo" if settings.demo_mode else "dev",
        server_name=service,
        integrations=[PydanticAIIntegration()],
    )
    sentry_sdk.set_tag("service", service)
    return True
