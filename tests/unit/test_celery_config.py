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


def test_placeholder_task_entrypoints_are_idempotent_skips() -> None:
    assert collect_source_messages_task("source-1") == {
        "stage": "telegram_collection",
        "entity_id": "source-1",
        "status": "skipped",
    }
    assert process_message_task("message-1")["status"] == "skipped"
    assert classify_message_task("message-1")["status"] == "skipped"
    assert detect_duplicates_task("message-1")["status"] == "skipped"
    assert send_notification_task("order-1")["status"] == "skipped"
