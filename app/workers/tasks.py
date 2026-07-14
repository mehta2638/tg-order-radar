from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select, update

from app.db.session import async_session_factory
from app.models import Order, TelegramSource
from app.services.source_validation import validate_source
from app.workers.celery_app import celery_app


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@celery_app.task(name="app.workers.tasks.validate_source_task")
def validate_source_task(source_id: str, correlation_id: str | None = None) -> dict[str, str]:
    return run_async(_validate_source_task(UUID(source_id)))


async def _validate_source_task(source_id: UUID) -> dict[str, str]:
    async with async_session_factory() as session:
        source = await validate_source(session, source_id)
        return {"source_id": str(source.id), "access_status": source.access_status}


@celery_app.task(name="app.workers.tasks.enqueue_pending_source_validations")
def enqueue_pending_source_validations(correlation_id: str | None = None) -> dict[str, int]:
    return run_async(_enqueue_pending_source_validations(correlation_id=correlation_id))


async def _enqueue_pending_source_validations(correlation_id: str | None = None) -> dict[str, int]:
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        source_ids = list(
            await session.scalars(
                select(TelegramSource.id).where(
                    TelegramSource.enabled.is_(True),
                    TelegramSource.access_status == "pending_validation",
                    (TelegramSource.pause_until.is_(None) | (TelegramSource.pause_until <= now)),
                )
            )
        )

    for source_id in source_ids:
        validate_source_task.apply_async(
            args=(str(source_id),),
            kwargs={"correlation_id": correlation_id},
            task_id=f"source-validation:{source_id}",
        )

    return {"enqueued": len(source_ids)}


@celery_app.task(name="app.workers.tasks.archive_stale_orders_task")
def archive_stale_orders_task(correlation_id: str | None = None) -> dict[str, int]:
    return run_async(_archive_stale_orders())


async def _archive_stale_orders() -> dict[str, int]:
    cutoff = datetime.now(UTC) - timedelta(days=7)
    statement = (
        update(Order)
        .where(
            and_(
                Order.published_at < cutoff,
                Order.status != "archived",
            )
        )
        .values(status="archived", is_fresh=False)
    )
    async with async_session_factory() as session:
        result = await session.execute(statement)
        await session.commit()
    return {"archived": int(getattr(result, "rowcount", 0))}


@celery_app.task(name="app.workers.tasks.collect_source_messages_task")
def collect_source_messages_task(
    source_id: str,
    correlation_id: str | None = None,
) -> dict[str, str]:
    return skipped("telegram_collection", source_id)


@celery_app.task(name="app.workers.tasks.process_message_task")
def process_message_task(message_id: str, correlation_id: str | None = None) -> dict[str, str]:
    return skipped("message_processing", message_id)


@celery_app.task(name="app.workers.tasks.classify_message_task")
def classify_message_task(message_id: str, correlation_id: str | None = None) -> dict[str, str]:
    return skipped("classification", message_id)


@celery_app.task(name="app.workers.tasks.detect_duplicates_task")
def detect_duplicates_task(message_id: str, correlation_id: str | None = None) -> dict[str, str]:
    return skipped("duplicate_detection", message_id)


@celery_app.task(name="app.workers.tasks.send_notification_task")
def send_notification_task(order_id: str, correlation_id: str | None = None) -> dict[str, str]:
    return skipped("notifications", order_id)


def skipped(stage: str, entity_id: str) -> dict[str, str]:
    return {"stage": stage, "entity_id": entity_id, "status": "skipped"}
