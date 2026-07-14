import asyncio

import redis.asyncio as redis

from app.core.config import get_settings
from app.db.health import check_database
from app.workers.celery_app import celery_app


async def check_worker_dependencies() -> dict[str, str]:
    settings = get_settings()
    await check_database()

    broker = redis.from_url(settings.celery_broker_url)
    backend = redis.from_url(settings.celery_result_backend)
    try:
        await broker.ping()
        await backend.ping()
    finally:
        await broker.aclose()
        await backend.aclose()

    if celery_app.main != "tg_order_radar":
        raise RuntimeError("Celery app is not configured.")

    return {"status": "ok"}


async def main() -> None:
    await check_worker_dependencies()
    print("worker dependencies ok")


if __name__ == "__main__":
    asyncio.run(main())
