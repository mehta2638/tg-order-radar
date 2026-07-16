from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.bot import services
from app.bot.cards import OrderCard
from app.core.config import Settings
from app.models import (
    NotificationDelivery,
    NotificationSubscription,
    Order,
    User,
)


class FakeSender:
    def __init__(self) -> None:
        self.chat_ids: list[int] = []

    async def send_message(self, chat_id: int, **kwargs: object) -> object:
        self.chat_ids.append(chat_id)
        return object()


def make_user(tg_chat_id: int = 42) -> User:
    return User(
        id=uuid4(),
        email=f"bot-{tg_chat_id}@local",
        password_hash="bot",
        role="operator",
        is_active=True,
        tg_chat_id=tg_chat_id,
    )


def make_subscription(user_id, **kwargs: object) -> NotificationSubscription:
    payload = {
        "id": uuid4(),
        "user_id": user_id,
        "name": "sub",
        "enabled": True,
        "project_types": [],
        "currencies": [],
        "source_ids": [],
        "positive_keywords": [],
        "negative_keywords": [],
        "timezone": "UTC",
        "rate_limit_period_minutes": 60,
        "created_at": datetime.now(UTC),
    }
    payload.update(kwargs)
    return NotificationSubscription(**payload)  # type: ignore[arg-type]


async def test_user_without_subscriptions_gets_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    order_id = uuid4()
    user = make_user()

    async def fake_card(*args: object, **kwargs: object) -> OrderCard:
        return OrderCard(
            order_id=str(order_id),
            source="s",
            published_at=datetime.now(UTC),
            project_type="landing",
            summary="Нужен лендинг",
            budget_from=None,
            budget_to=None,
            budget_currency=None,
            deadline_text=None,
            contact=None,
            relevance_score=90,
            message_url=None,
        )

    async def fake_recipients(*args: object, **kwargs: object) -> list[services.BotRecipient]:
        return [services.BotRecipient(user=user, tg_chat_id=42)]

    async def fake_match(*args: object, **kwargs: object) -> None:
        return None

    class FakeSession:
        async def get(self, model: object, entity_id: object) -> Order | None:
            if model is Order:
                return Order(
                    id=order_id,
                    message_id=uuid4(),
                    source_id=uuid4(),
                    published_at=datetime.now(UTC),
                    relevance_score=90,
                    status="new",
                    is_fresh=True,
                )
            return None

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(services, "get_notifiable_order_card", fake_card)
    monkeypatch.setattr(services, "resolve_bot_recipients", fake_recipients)
    monkeypatch.setattr(services, "find_matching_subscription", fake_match)
    sender = FakeSender()
    result = await services.send_order_notification(
        FakeSession(),
        order_id,
        sender,
        Settings(bot_rate_limit_seconds=0, bot_send_max_retries=1),
    )
    assert result.sent == 0
    assert result.skipped == 1
    assert sender.chat_ids == []


async def test_quiet_hours_defer_and_process_once(monkeypatch: pytest.MonkeyPatch) -> None:
    order_id = uuid4()
    user = make_user()
    subscription = make_subscription(
        user.id,
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        timezone="UTC",
    )
    delivery = NotificationDelivery(
        order_id=order_id,
        user_id=user.id,
        channel="bot",
        status="queued",
        dedup_key=f"bot:{order_id}:{user.id}",
    )

    async def fake_card(*args: object, **kwargs: object) -> OrderCard:
        return OrderCard(
            order_id=str(order_id),
            source="s",
            published_at=datetime.now(UTC),
            project_type="landing",
            summary="Нужен лендинг",
            budget_from=Decimal("1"),
            budget_to=Decimal("2"),
            budget_currency="RUB",
            deadline_text=None,
            contact=None,
            relevance_score=90,
            message_url=None,
        )

    async def fake_recipients(*args: object, **kwargs: object) -> list[services.BotRecipient]:
        return [services.BotRecipient(user=user, tg_chat_id=42)]

    async def fake_match(*args: object, **kwargs: object) -> NotificationSubscription:
        return subscription

    async def fake_delivery(*args: object, **kwargs: object) -> tuple[NotificationDelivery, bool]:
        return delivery, True

    async def fake_false(*args: object, **kwargs: object) -> bool:
        return False

    class FakeSession:
        async def get(self, model: object, entity_id: object) -> object | None:
            if model is Order:
                return Order(
                    id=order_id,
                    message_id=uuid4(),
                    source_id=uuid4(),
                    published_at=datetime.now(UTC),
                    relevance_score=90,
                    status="new",
                    is_fresh=True,
                )
            if model is User:
                return user
            return None

        async def commit(self) -> None:
            return None

        async def scalars(self, *args: object, **kwargs: object) -> object:
            class Result:
                def all(self_inner) -> list[NotificationDelivery]:
                    return [delivery]

                def __iter__(self_inner):
                    return iter([delivery])

            return Result()

    monkeypatch.setattr(services, "get_notifiable_order_card", fake_card)
    monkeypatch.setattr(services, "resolve_bot_recipients", fake_recipients)
    monkeypatch.setattr(services, "find_matching_subscription", fake_match)
    monkeypatch.setattr(services, "get_or_create_delivery", fake_delivery)
    monkeypatch.setattr(services, "is_rate_limited", fake_false)
    monkeypatch.setattr(services, "is_similar_cooldown_active", fake_false)
    monkeypatch.setattr(
        services,
        "is_in_quiet_hours",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        services,
        "next_quiet_hours_end",
        lambda *args, **kwargs: datetime.now(UTC) + timedelta(hours=1),
    )

    sender = FakeSender()
    result = await services.send_order_notification(
        FakeSession(),
        order_id,
        sender,
        Settings(bot_rate_limit_seconds=0, bot_send_max_retries=1),
    )
    assert result.deferred == 1
    assert delivery.status == "deferred"
    assert sender.chat_ids == []

    delivery.scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
    deferred_result = await services.process_deferred_notifications(
        FakeSession(),
        sender,
        Settings(bot_rate_limit_seconds=0, bot_send_max_retries=1),
    )
    assert deferred_result["sent"] == 1
    assert delivery.status == "sent"
    assert sender.chat_ids == [42]


async def test_rate_limit_blocks_extra_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    order_id = uuid4()
    user = make_user()
    subscription = make_subscription(user.id, max_notifications_per_period=1)

    async def fake_card(*args: object, **kwargs: object) -> OrderCard:
        return OrderCard(
            order_id=str(order_id),
            source="s",
            published_at=datetime.now(UTC),
            project_type="landing",
            summary="x",
            budget_from=None,
            budget_to=None,
            budget_currency=None,
            deadline_text=None,
            contact=None,
            relevance_score=90,
            message_url=None,
        )

    async def fake_recipients(*args: object, **kwargs: object) -> list[services.BotRecipient]:
        return [services.BotRecipient(user=user, tg_chat_id=42)]

    async def fake_match(*args: object, **kwargs: object) -> NotificationSubscription:
        return subscription

    async def fake_true(*args: object, **kwargs: object) -> bool:
        return True

    async def fake_false(*args: object, **kwargs: object) -> bool:
        return False

    class FakeSession:
        async def get(self, model: object, entity_id: object) -> Order | None:
            if model is Order:
                return Order(
                    id=order_id,
                    message_id=uuid4(),
                    source_id=uuid4(),
                    published_at=datetime.now(UTC),
                    relevance_score=90,
                    status="new",
                    is_fresh=True,
                )
            return None

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(services, "get_notifiable_order_card", fake_card)
    monkeypatch.setattr(services, "resolve_bot_recipients", fake_recipients)
    monkeypatch.setattr(services, "find_matching_subscription", fake_match)
    monkeypatch.setattr(services, "is_rate_limited", fake_true)
    monkeypatch.setattr(services, "is_similar_cooldown_active", fake_false)

    sender = FakeSender()
    result = await services.send_order_notification(
        FakeSession(),
        order_id,
        sender,
        Settings(bot_rate_limit_seconds=0, bot_send_max_retries=1),
    )
    assert result.sent == 0
    assert result.skipped == 1
