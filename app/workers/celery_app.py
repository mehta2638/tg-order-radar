from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery, Task
from kombu import Exchange, Queue

from app.core.config import get_settings
from app.core.correlation import get_correlation_id
from app.monitoring.sentry import init_sentry
from app.workers.dead_letter import record_failed_task
from app.workers.queues import (
    CLASSIFICATION_QUEUE,
    DUPLICATE_DETECTION_QUEUE,
    MAINTENANCE_QUEUE,
    MESSAGE_PROCESSING_QUEUE,
    NOTIFICATIONS_QUEUE,
    SOURCE_VALIDATION_QUEUE,
    TASK_QUEUES,
    TELEGRAM_COLLECTION_QUEUE,
)

settings = get_settings()
init_sentry(settings, service_name="worker")


class BaseTaskWithRetry(Task):  # type: ignore[misc]
    autoretry_for = (ConnectionError, TimeoutError)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = settings.celery_task_max_retries
    acks_late = True
    reject_on_worker_lost = True

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: object,
    ) -> None:
        retries = int(getattr(self.request, "retries", 0))
        delivery_info = getattr(self.request, "delivery_info", {})
        queue = delivery_info.get("routing_key") if isinstance(delivery_info, dict) else None
        correlation_id = kwargs.get("correlation_id") or get_correlation_id()
        asyncio.run(
            record_failed_task(
                task_name=self.name,
                task_id=task_id,
                queue=queue if isinstance(queue, str) else None,
                args=args,
                kwargs=kwargs,
                reason=f"{type(exc).__name__}: {exc}",
                retries=retries,
                correlation_id=correlation_id if isinstance(correlation_id, str) else None,
            )
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)


celery_app = Celery(
    "tg_order_radar",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    task_cls=BaseTaskWithRetry,
    include=("app.workers.tasks",),
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=30,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_queues=[
        Queue(queue_name, Exchange(queue_name), routing_key=queue_name)
        for queue_name in TASK_QUEUES
    ],
    task_routes={
        "app.workers.tasks.validate_source_task": {"queue": SOURCE_VALIDATION_QUEUE},
        "app.workers.tasks.enqueue_pending_source_validations": {
            "queue": SOURCE_VALIDATION_QUEUE,
        },
        "app.workers.tasks.collect_source_messages_task": {"queue": TELEGRAM_COLLECTION_QUEUE},
        "app.workers.tasks.enqueue_collectable_sources": {"queue": TELEGRAM_COLLECTION_QUEUE},
        "app.workers.tasks.process_message_task": {"queue": MESSAGE_PROCESSING_QUEUE},
        "app.workers.tasks.classify_message_task": {"queue": CLASSIFICATION_QUEUE},
        "app.workers.tasks.detect_duplicates_task": {"queue": DUPLICATE_DETECTION_QUEUE},
        "app.workers.tasks.send_notification_task": {"queue": NOTIFICATIONS_QUEUE},
        "app.workers.tasks.process_deferred_notifications_task": {
            "queue": NOTIFICATIONS_QUEUE,
        },
        "app.workers.tasks.archive_stale_orders_task": {"queue": MAINTENANCE_QUEUE},
        "app.workers.tasks.recalculate_source_activity_task": {
            "queue": MAINTENANCE_QUEUE,
        },
        "app.workers.tasks.ensure_message_partitions_task": {"queue": MAINTENANCE_QUEUE},
        "app.workers.tasks.drop_expired_message_partitions_task": {
            "queue": MAINTENANCE_QUEUE,
        },
        "app.workers.tasks.recover_floodwait_state_task": {"queue": MAINTENANCE_QUEUE},
    },
    beat_schedule={
        "validate-pending-sources": {
            "task": "app.workers.tasks.enqueue_pending_source_validations",
            "schedule": 300.0,
        },
        "archive-stale-orders": {
            "task": "app.workers.tasks.archive_stale_orders_task",
            "schedule": 3600.0,
        },
        "recalculate-source-activity": {
            "task": "app.workers.tasks.recalculate_source_activity_task",
            "schedule": 10800.0,
        },
        "ensure-message-partitions": {
            "task": "app.workers.tasks.ensure_message_partitions_task",
            "schedule": 86400.0,
        },
        "drop-expired-message-partitions": {
            "task": "app.workers.tasks.drop_expired_message_partitions_task",
            "schedule": 86400.0,
        },
        "recover-floodwait-state": {
            "task": "app.workers.tasks.recover_floodwait_state_task",
            "schedule": 60.0,
        },
        "collect-public-sources": {
            "task": "app.workers.tasks.enqueue_collectable_sources",
            "schedule": float(settings.collector_poll_interval_seconds),
        },
        "process-deferred-notifications": {
            "task": "app.workers.tasks.process_deferred_notifications_task",
            "schedule": 60.0,
        },
    },
)
