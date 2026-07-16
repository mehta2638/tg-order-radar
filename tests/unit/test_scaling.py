from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.collector.accounts import select_account_for_source, session_names_from_settings
from app.core.config import Settings
from app.models import TelegramAccount, TelegramSource
from app.services.floodwait_recovery import recover_expired_source_floodwaits
from app.services.message_partitions import add_months, month_start, partition_name
from app.workers.celery_app import celery_app


def test_session_names_default_to_single_collector() -> None:
    settings = Settings(tg_session_name="collector", tg_session_names="")
    assert session_names_from_settings(settings) == ["collector"]


def test_session_names_support_multi_account_list() -> None:
    settings = Settings(tg_session_names="alpha, beta,gamma")
    assert session_names_from_settings(settings) == ["alpha", "beta", "gamma"]


def test_account_sharding_is_stable_and_distributes() -> None:
    accounts = [
        TelegramAccount(label="a", session_ref="a", status="active"),
        TelegramAccount(label="b", session_ref="b", status="active"),
        TelegramAccount(label="c", session_ref="c", status="active"),
    ]
    source_id = uuid4()
    first = select_account_for_source(source_id, accounts)
    second = select_account_for_source(source_id, accounts)
    assert first is not None
    assert first is second

    # Removing a paused account redistributes remaining sources among live ones.
    live = [account for account in accounts if account.label != first.label]
    reassigned = select_account_for_source(source_id, live)
    assert reassigned is not None
    assert reassigned.label != first.label


def test_partition_helpers_are_month_aligned() -> None:
    assert month_start(date(2026, 7, 16)) == date(2026, 7, 1)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert partition_name(date(2026, 7, 1)) == "messages_2026_07"


def test_maintenance_beat_includes_partition_and_floodwait_jobs() -> None:
    assert "ensure-message-partitions" in celery_app.conf.beat_schedule
    assert "drop-expired-message-partitions" in celery_app.conf.beat_schedule
    assert "recover-floodwait-state" in celery_app.conf.beat_schedule
    assert (
        celery_app.conf.task_routes["app.workers.tasks.ensure_message_partitions_task"]["queue"]
        == "maintenance"
    )


def test_floodwait_recovery_restores_source_after_wait() -> None:
    source = TelegramSource(
        access_status="floodwait",
        pause_until=datetime.now(UTC) - timedelta(seconds=5),
        normalized_username="demo",
        is_public=False,
    )

    async def fake_scalars(statement: object) -> list[TelegramSource]:
        return [source]

    session = MagicMock()
    session.scalars = AsyncMock(side_effect=fake_scalars)
    session.flush = AsyncMock()

    recovered = asyncio.run(recover_expired_source_floodwaits(session))
    assert recovered == 1
    assert source.access_status == "ok"
    assert source.pause_until is None
    assert source.is_public is True
