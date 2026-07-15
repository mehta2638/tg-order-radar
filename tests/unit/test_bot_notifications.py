from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.bot import services
from app.bot.cards import OrderCard, build_order_keyboard, render_order_card
from app.bot.handlers import parse_order_callback
from app.core.config import Settings
from app.models import NotificationDelivery, User


class FakeSender:
    def __init__(self) -> None:
        self.chat_ids: list[int] = []

    async def send_message(self, chat_id: int, **kwargs: object) -> object:
        self.chat_ids.append(chat_id)
        return object()


def make_card(order_id: str) -> OrderCard:
    return OrderCard(
        order_id=order_id,
        source="orders<&>",
        published_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
        project_type="landing",
        summary="Нужен <лендинг> & CRM",
        budget_from=Decimal("100000"),
        budget_to=Decimal("150000"),
        budget_currency="RUB",
        deadline_text="<неделя>",
        contact="@client",
        relevance_score=92,
        message_url="https://t.me/orders/1",
    )


def test_render_order_card_escapes_user_content() -> None:
    text = render_order_card(make_card(str(uuid4())))

    assert "&lt;лендинг&gt;" in text
    assert "orders&lt;&amp;&gt;" in text
    assert "<b>Новый заказ</b>" in text


def test_order_keyboard_contains_required_actions() -> None:
    order_id = str(uuid4())
    keyboard = build_order_keyboard(make_card(order_id))
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(
        button.text == "Открыть" and button.url == "https://t.me/orders/1" for button in buttons
    )
    assert any(button.callback_data == f"order:fav:{order_id}" for button in buttons)
    assert any(button.callback_data == f"order:status:contacted:{order_id}" for button in buttons)
    assert any(button.callback_data == f"order:status:irrelevant:{order_id}" for button in buttons)


def test_parse_order_callback_accepts_known_actions() -> None:
    order_id = uuid4()

    assert parse_order_callback(f"order:fav:{order_id}") == ("fav", order_id, None)
    assert parse_order_callback(f"order:status:contacted:{order_id}") == (
        "status",
        order_id,
        "contacted",
    )
    assert parse_order_callback(f"order:status:archived:{order_id}") is None
    assert parse_order_callback("order:fav:not-a-uuid") is None


async def test_send_order_notification_skips_existing_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id = uuid4()
    user = User(
        id=uuid4(),
        email="operator@example.com",
        password_hash="hash",
        role="operator",
        is_active=True,
        tg_chat_id=42,
    )
    delivery = NotificationDelivery(
        order_id=order_id,
        user_id=user.id,
        channel="bot",
        status="sent",
        dedup_key=f"bot:{order_id}:{user.id}",
    )

    async def fake_card(*args: object, **kwargs: object) -> OrderCard:
        return make_card(str(order_id))

    async def fake_recipients(*args: object, **kwargs: object) -> list[services.BotRecipient]:
        return [services.BotRecipient(user=user, tg_chat_id=42)]

    async def fake_delivery(*args: object, **kwargs: object) -> tuple[NotificationDelivery, bool]:
        return delivery, False

    monkeypatch.setattr(services, "get_notifiable_order_card", fake_card)
    monkeypatch.setattr(services, "resolve_bot_recipients", fake_recipients)
    monkeypatch.setattr(services, "get_or_create_delivery", fake_delivery)

    sender = FakeSender()
    result = await services.send_order_notification(
        session=object(),
        order_id=order_id,
        sender=sender,
        settings=Settings(bot_rate_limit_seconds=0, bot_send_max_retries=1),
    )

    assert result.skipped == 1
    assert result.sent == 0
    assert sender.chat_ids == []


async def test_send_order_notification_sends_new_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    order_id = uuid4()
    user = User(
        id=uuid4(),
        email="operator@example.com",
        password_hash="hash",
        role="operator",
        is_active=True,
        tg_chat_id=42,
    )
    delivery = NotificationDelivery(
        order_id=order_id,
        user_id=user.id,
        channel="bot",
        status="queued",
        dedup_key=f"bot:{order_id}:{user.id}",
    )

    async def fake_card(*args: object, **kwargs: object) -> OrderCard:
        return make_card(str(order_id))

    async def fake_recipients(*args: object, **kwargs: object) -> list[services.BotRecipient]:
        return [services.BotRecipient(user=user, tg_chat_id=42)]

    async def fake_delivery(*args: object, **kwargs: object) -> tuple[NotificationDelivery, bool]:
        return delivery, True

    class FakeSession:
        async def commit(self) -> None:
            return None

    monkeypatch.setattr(services, "get_notifiable_order_card", fake_card)
    monkeypatch.setattr(services, "resolve_bot_recipients", fake_recipients)
    monkeypatch.setattr(services, "get_or_create_delivery", fake_delivery)

    sender = FakeSender()
    result = await services.send_order_notification(
        session=FakeSession(),
        order_id=order_id,
        sender=sender,
        settings=Settings(bot_rate_limit_seconds=0, bot_send_max_retries=1),
    )

    assert result.sent == 1
    assert delivery.status == "sent"
    assert sender.chat_ids == [42]
