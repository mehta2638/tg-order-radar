from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import redis
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import FailedTask, TelegramSource
from app.workers.queues import TASK_QUEUES

REGISTRY = CollectorRegistry()

MESSAGES_PROCESSED_TOTAL = Counter(
    "messages_processed_total",
    "Messages processed by the pipeline.",
    ["status"],
    registry=REGISTRY,
)
ORDERS_FOUND_TOTAL = Counter(
    "orders_found_total",
    "Orders created after classification.",
    ["project_type"],
    registry=REGISTRY,
)
DUPLICATES_DETECTED_TOTAL = Counter(
    "duplicates_detected_total",
    "Duplicate detection outcomes.",
    ["method"],
    registry=REGISTRY,
)
NOTIFICATIONS_SENT_TOTAL = Counter(
    "notifications_sent_total",
    "Bot notification delivery outcomes.",
    ["status"],
    registry=REGISTRY,
)
TELEGRAM_API_ERRORS_TOTAL = Counter(
    "telegram_api_errors_total",
    "Telegram API errors observed by collectors.",
    ["kind"],
    registry=REGISTRY,
)
MESSAGE_PROCESSING_SECONDS = Histogram(
    "message_processing_seconds",
    "Message processing latency in seconds.",
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
CLASSIFICATION_LATENCY_SECONDS = Histogram(
    "classification_latency_seconds",
    "Classification latency in seconds.",
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
QUEUE_SIZE = Gauge(
    "queue_size",
    "Celery queue depth.",
    ["queue"],
    registry=REGISTRY,
)
COLLECTOR_LAG_SECONDS = Gauge(
    "collector_lag_seconds",
    "Seconds since the most recent successful source check.",
    registry=REGISTRY,
)
FAILED_TASKS = Gauge(
    "failed_tasks",
    "Number of failed Celery tasks in the dead-letter table.",
    registry=REGISTRY,
)
ACTIVE_SOURCES = Gauge(
    "active_sources",
    "Enabled Telegram sources by access status.",
    ["status"],
    registry=REGISTRY,
)
FLOODWAIT_ACTIVE_ACCOUNTS = Gauge(
    "floodwait_active_accounts",
    "Telegram accounts currently in floodwait.",
    registry=REGISTRY,
)


@contextmanager
def observe_duration(histogram: Histogram) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        histogram.observe(time.perf_counter() - started)


def record_message_processed(status: str) -> None:
    MESSAGES_PROCESSED_TOTAL.labels(status=status).inc()


def record_order_found(project_type: str | None) -> None:
    ORDERS_FOUND_TOTAL.labels(project_type=project_type or "unknown").inc()


def record_duplicate(method: str) -> None:
    DUPLICATES_DETECTED_TOTAL.labels(method=method).inc()


def record_notification(status: str, count: int = 1) -> None:
    if count <= 0:
        return
    NOTIFICATIONS_SENT_TOTAL.labels(status=status).inc(count)


def record_telegram_error(kind: str) -> None:
    TELEGRAM_API_ERRORS_TOTAL.labels(kind=kind).inc()


def update_queue_sizes(settings: Settings | None = None) -> None:
    active = settings or get_settings()
    client = redis.Redis.from_url(active.celery_broker_url, decode_responses=True)
    try:
        for queue_name in TASK_QUEUES:
            size = int(client.llen(queue_name) or 0)
            QUEUE_SIZE.labels(queue=queue_name).set(size)
    finally:
        client.close()


async def refresh_runtime_gauges(session: AsyncSession) -> None:
    failed_count = await session.scalar(select(func.count()).select_from(FailedTask))
    FAILED_TASKS.set(float(failed_count or 0))

    lag_row = await session.execute(
        text(
            """
            select extract(epoch from (now() - max(last_checked_at)))
            from telegram_sources
            where enabled is true
              and access_status = 'ok'
              and last_checked_at is not null
            """
        )
    )
    lag_value = lag_row.scalar_one_or_none()
    COLLECTOR_LAG_SECONDS.set(float(lag_value) if lag_value is not None else 0.0)

    status_rows = await session.execute(
        select(TelegramSource.access_status, func.count())
        .where(TelegramSource.enabled.is_(True))
        .group_by(TelegramSource.access_status)
    )
    seen_statuses: set[str] = set()
    for status_name, count in status_rows.all():
        seen_statuses.add(str(status_name))
        ACTIVE_SOURCES.labels(status=str(status_name)).set(float(count))
    for status_name in ("ok", "pending_validation", "error", "floodwait", "private"):
        if status_name not in seen_statuses:
            ACTIVE_SOURCES.labels(status=status_name).set(0)

    floodwait_count = await session.scalar(
        select(func.count())
        .select_from(TelegramSource)
        .where(
            TelegramSource.enabled.is_(True),
            TelegramSource.access_status == "floodwait",
        )
    )
    FLOODWAIT_ACTIVE_ACCOUNTS.set(float(floodwait_count or 0))


async def render_metrics(
    session: AsyncSession, settings: Settings | None = None
) -> tuple[bytes, str]:
    active = settings or get_settings()
    if not active.prometheus_enabled:
        return b"# prometheus disabled\n", CONTENT_TYPE_LATEST
    update_queue_sizes(active)
    await refresh_runtime_gauges(session)
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def metrics_snapshot() -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "queues": list(TASK_QUEUES),
    }
