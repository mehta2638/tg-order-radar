from uuid import UUID, uuid4

import pytest

from app.collector.messages import CollectionResult
from app.services.message_processing import MessageProcessingResult
from app.workers import tasks
from app.workers.celery_app import BaseTaskWithRetry, celery_app
from app.workers.queues import (
    CLASSIFICATION_QUEUE,
    DUPLICATE_DETECTION_QUEUE,
    MESSAGE_PROCESSING_QUEUE,
    NOTIFICATIONS_QUEUE,
    SOURCE_VALIDATION_QUEUE,
    TELEGRAM_COLLECTION_QUEUE,
)
from app.workers.tasks import (
    classify_message_task,
    collect_source_messages_task,
    detect_duplicates_task,
    process_message_task,
    send_notification_task,
)


def test_celery_queues_and_routes_are_configured() -> None:
    queue_names = {queue.name for queue in celery_app.conf.task_queues}

    assert {
        SOURCE_VALIDATION_QUEUE,
        TELEGRAM_COLLECTION_QUEUE,
        MESSAGE_PROCESSING_QUEUE,
        CLASSIFICATION_QUEUE,
        DUPLICATE_DETECTION_QUEUE,
        NOTIFICATIONS_QUEUE,
    }.issubset(queue_names)
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_base_task_retry_policy_is_bounded() -> None:
    assert BaseTaskWithRetry.retry_backoff is True
    assert BaseTaskWithRetry.retry_jitter is True
    assert BaseTaskWithRetry.max_retries == 3
    assert BaseTaskWithRetry.acks_late is True
    assert BaseTaskWithRetry.reject_on_worker_lost is True


def test_collect_source_task_returns_collector_result(monkeypatch: pytest.MonkeyPatch) -> None:
    source_id = uuid4()

    async def fake_collect_source_messages(
        source_id: UUID,
        **kwargs: object,
    ) -> CollectionResult:
        return CollectionResult(source_id=source_id, status="ok", saved=1, enqueued=1)

    monkeypatch.setattr(tasks, "collect_source_messages", fake_collect_source_messages)

    assert collect_source_messages_task(str(source_id)) == {
        "source_id": str(source_id),
        "status": "ok",
        "saved": 1,
        "updated": 0,
        "deleted": 0,
        "enqueued": 1,
        "last_seen_message_id": 0,
    }


def test_process_message_task_returns_processing_result(monkeypatch: pytest.MonkeyPatch) -> None:
    message_id = uuid4()

    async def fake_process_message(message_id: UUID) -> MessageProcessingResult:
        return MessageProcessingResult(
            message_id=message_id,
            status="processed",
            passed_prefilter=True,
            detected_language="ru",
            keyword_hits=1,
            negative_hits=0,
            entities=4,
        )

    monkeypatch.setattr(tasks, "process_message", fake_process_message)

    assert process_message_task(str(message_id)) == {
        "message_id": str(message_id),
        "status": "processed",
        "passed_prefilter": True,
        "detected_language": "ru",
        "keyword_hits": 1,
        "negative_hits": 0,
        "entities": 4,
    }


def test_placeholder_task_entrypoints_are_idempotent_skips() -> None:
    assert classify_message_task("message-1")["status"] == "skipped"
    assert detect_duplicates_task("message-1")["status"] == "skipped"
    assert send_notification_task("order-1")["status"] == "skipped"
