from uuid import UUID, uuid4

import pytest

from app.collector.messages import CollectionResult
from app.core.config import get_settings
from app.services.deduplication import DeduplicationResult
from app.services.message_processing import MessageProcessingResult
from app.services.order_classification import OrderClassificationResult
from app.workers import tasks
from app.workers.celery_app import BaseTaskWithRetry, celery_app
from app.workers.queues import (
    CLASSIFICATION_QUEUE,
    DUPLICATE_DETECTION_QUEUE,
    MAINTENANCE_QUEUE,
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
        MAINTENANCE_QUEUE,
    }.issubset(queue_names)
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert (
        celery_app.conf.task_routes["app.workers.tasks.recalculate_source_activity_task"]["queue"]
        == MAINTENANCE_QUEUE
    )
    assert "recalculate-source-activity" in celery_app.conf.beat_schedule


def test_base_task_retry_policy_is_bounded() -> None:
    assert BaseTaskWithRetry.retry_backoff is True
    assert BaseTaskWithRetry.retry_jitter is True
    assert BaseTaskWithRetry.max_retries == 3
    assert BaseTaskWithRetry.acks_late is True
    assert BaseTaskWithRetry.reject_on_worker_lost is True


def test_worker_crash_before_ack_requeues_task() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


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
    monkeypatch.setattr(tasks, "enqueue_classification", lambda *args, **kwargs: None)

    assert process_message_task(str(message_id)) == {
        "message_id": str(message_id),
        "status": "processed",
        "passed_prefilter": True,
        "detected_language": "ru",
        "keyword_hits": 1,
        "negative_hits": 0,
        "entities": 4,
    }


def test_detect_duplicates_task_enqueues_only_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id = uuid4()
    enqueued: list[str] = []

    async def fake_detect_duplicates_for_order(order_id: UUID) -> DeduplicationResult:
        return DeduplicationResult(
            order_id=order_id,
            status="unique",
            is_canonical=True,
            canonical_order_id=order_id,
            duplicate_group_id=None,
            duplicate_count=1,
            method="fingerprint",
        )

    class FakeNotificationTask:
        def apply_async(self, args: tuple[str], **kwargs: object) -> None:
            enqueued.append(args[0])

    monkeypatch.setattr(tasks, "detect_duplicates_for_order", fake_detect_duplicates_for_order)
    monkeypatch.setattr(tasks, "send_notification_task", FakeNotificationTask())

    assert detect_duplicates_task(str(order_id)) == {
        "order_id": str(order_id),
        "status": "unique",
        "is_canonical": True,
        "canonical_order_id": str(order_id),
        "duplicate_group_id": None,
        "duplicate_count": 1,
        "method": "fingerprint",
    }
    assert enqueued == [str(order_id)]


def test_notification_task_skips_without_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    get_settings.cache_clear()
    order_id = uuid4()

    try:
        assert send_notification_task(str(order_id)) == {
            "stage": "notifications",
            "entity_id": str(order_id),
            "status": "skipped",
        }
    finally:
        get_settings.cache_clear()


def test_classify_message_task_returns_rules_result(monkeypatch: pytest.MonkeyPatch) -> None:
    message_id = uuid4()

    async def fake_classify_message(message_id: UUID) -> OrderClassificationResult:
        return OrderClassificationResult(
            message_id=message_id,
            status="classified",
            label="order",
            confidence=0.9,
            manual_review=False,
            relevance_score=88,
            order_id=None,
        )

    monkeypatch.setattr(tasks, "classify_message", fake_classify_message)

    assert classify_message_task(str(message_id)) == {
        "message_id": str(message_id),
        "status": "classified",
        "label": "order",
        "confidence": 0.9,
        "manual_review": False,
        "relevance_score": 88,
        "order_id": None,
    }
