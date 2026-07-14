from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select, update

from app.collector.messages import collect_source_messages
from app.db.session import async_session_factory
from app.models import Order, TelegramSource
from app.services.message_processing import process_message
from app.services.order_classification import classify_message
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
) -> dict[str, int | str]:
    result = run_async(
        collect_source_messages(
            UUID(source_id),
            enqueue_message_processing=enqueue_message_processing,
            correlation_id=correlation_id,
        )
    )
    return {
        "source_id": str(result.source_id),
        "status": result.status,
        "saved": result.saved,
        "updated": result.updated,
        "deleted": result.deleted,
        "enqueued": result.enqueued,
        "last_seen_message_id": result.last_seen_message_id,
    }


@celery_app.task(name="app.workers.tasks.enqueue_collectable_sources")
def enqueue_collectable_sources(correlation_id: str | None = None) -> dict[str, int]:
    return run_async(_enqueue_collectable_sources(correlation_id=correlation_id))


async def _enqueue_collectable_sources(correlation_id: str | None = None) -> dict[str, int]:
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        source_ids = list(
            await session.scalars(
                select(TelegramSource.id).where(
                    TelegramSource.enabled.is_(True),
                    TelegramSource.is_public.is_(True),
                    TelegramSource.access_status == "ok",
                    (TelegramSource.pause_until.is_(None) | (TelegramSource.pause_until <= now)),
                )
            )
        )

    for source_id in source_ids:
        collect_source_messages_task.apply_async(
            args=(str(source_id),),
            kwargs={"correlation_id": correlation_id},
            task_id=f"telegram-collection:{source_id}",
        )

    return {"enqueued": len(source_ids)}


def enqueue_message_processing(message_id: UUID, correlation_id: str | None = None) -> None:
    process_message_task.apply_async(
        args=(str(message_id),),
        kwargs={"correlation_id": correlation_id},
        task_id=f"message-processing:{message_id}",
    )


@celery_app.task(name="app.workers.tasks.process_message_task")
def process_message_task(
    message_id: str, correlation_id: str | None = None
) -> dict[str, int | str | bool]:
    result = run_async(process_message(UUID(message_id)))
    if result.status == "processed":
        enqueue_classification(result.message_id, correlation_id)
    return {
        "message_id": str(result.message_id),
        "status": result.status,
        "passed_prefilter": result.passed_prefilter,
        "detected_language": result.detected_language,
        "keyword_hits": result.keyword_hits,
        "negative_hits": result.negative_hits,
        "entities": result.entities,
    }


def enqueue_classification(message_id: UUID, correlation_id: str | None = None) -> None:
    classify_message_task.apply_async(
        args=(str(message_id),),
        kwargs={"correlation_id": correlation_id},
        task_id=f"classification:{message_id}",
    )


@celery_app.task(name="app.workers.tasks.classify_message_task")
def classify_message_task(
    message_id: str,
    correlation_id: str | None = None,
) -> dict[str, float | int | str | bool | None]:
    result = run_async(classify_message(UUID(message_id)))
    if result.order_id is not None:
        detect_duplicates_task.apply_async(
            args=(str(result.order_id),),
            kwargs={"correlation_id": correlation_id},
            task_id=f"duplicate-detection:{result.order_id}",
        )
    return {
        "message_id": str(result.message_id),
        "status": result.status,
        "label": result.label,
        "confidence": result.confidence,
        "manual_review": result.manual_review,
        "relevance_score": result.relevance_score,
        "order_id": str(result.order_id) if result.order_id is not None else None,
    }


@celery_app.task(name="app.workers.tasks.detect_duplicates_task")
def detect_duplicates_task(message_id: str, correlation_id: str | None = None) -> dict[str, str]:
    return skipped("duplicate_detection", message_id)


@celery_app.task(name="app.workers.tasks.send_notification_task")
def send_notification_task(order_id: str, correlation_id: str | None = None) -> dict[str, str]:
    return skipped("notifications", order_id)


def skipped(stage: str, entity_id: str) -> dict[str, str]:
    return {"stage": stage, "entity_id": entity_id, "status": "skipped"}
