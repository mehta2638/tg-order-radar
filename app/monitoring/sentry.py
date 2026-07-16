from __future__ import annotations

from typing import Any

import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)
_INITIALIZED = False


def init_sentry(
    settings: Settings | None = None,
    *,
    service_name: str = "api",
) -> bool:
    global _INITIALIZED
    active = settings or get_settings()
    if not active.sentry_dsn:
        logger.info("sentry_disabled", reason="missing_dsn", service=service_name)
        return False
    if _INITIALIZED:
        return True

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    integrations: list[Any] = [
        LoggingIntegration(level=None, event_level=None),
        SqlalchemyIntegration(),
        CeleryIntegration(),
    ]
    if service_name == "api":
        integrations.append(FastApiIntegration())

    sentry_sdk.init(
        dsn=active.sentry_dsn,
        environment=active.environment,
        release=f"tg-order-radar@{active.app_version}",
        traces_sample_rate=active.sentry_traces_sample_rate,
        send_default_pii=False,
        integrations=integrations,
    )
    sentry_sdk.set_tag("service", service_name)
    _INITIALIZED = True
    logger.info("sentry_initialized", service=service_name, environment=active.environment)
    return True
