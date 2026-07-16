from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.favorites import router as favorites_router
from app.api.health import router as health_router
from app.api.keywords import router as keywords_router
from app.api.metrics import router as metrics_router
from app.api.orders import router as orders_router
from app.api.sources import router as sources_router
from app.api.stats import router as stats_router
from app.api.subscriptions import router as subscriptions_router
from app.core.config import get_settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.monitoring.sentry import init_sentry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_sentry(settings, service_name="api")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(sources_router)
    app.include_router(orders_router)
    app.include_router(favorites_router)
    app.include_router(keywords_router)
    app.include_router(stats_router)
    app.include_router(subscriptions_router)
    return app


app = create_app()
