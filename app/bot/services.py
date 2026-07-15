from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ApiPrincipal
from app.bot.cards import OrderCard, build_order_keyboard, first_contact, render_order_card
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.models import (
    DuplicateGroup,
    Message,
    NotificationDelivery,
    Order,
    TelegramSource,
    User,
)
from app.services.audit import add_audit_log
from app.services.favorites import add_favorite
from app.services.orders import update_order_status


class BotSender(Protocol):
    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str,
        reply_markup: InlineKeyboardMarkup,
        disable_web_page_preview: bool,
    ) -> object: ...


@dataclass(frozen=True)
class BotRecipient:
    user: User
    tg_chat_id: int


@dataclass(frozen=True)
class NotificationResult:
    order_id: UUID
    status: str
    sent: int = 0
    skipped: int = 0
    failed: int = 0


async def send_order_notification(
    session: AsyncSession,
    order_id: UUID,
    sender: BotSender,
    settings: Settings | None = None,
) -> NotificationResult:
    settings = settings or get_settings()
    card = await get_notifiable_order_card(session, order_id, settings)
    if card is None:
        return NotificationResult(order_id=order_id, status="skipped")

    recipients = await resolve_bot_recipients(session, settings)
    if not recipients:
        return NotificationResult(order_id=order_id, status="no_recipients")

    sent = 0
    skipped = 0
    failed = 0
    for recipient in recipients:
        delivery, created = await get_or_create_delivery(session, order_id, recipient.user.id)
        if not created:
            skipped += 1
            continue

        try:
            await send_with_retry(
                sender,
                recipient.tg_chat_id,
                render_order_card(card),
                build_order_keyboard(card),
                settings,
            )
        except Exception as exc:  # noqa: BLE001
            delivery.status = "failed"
            delivery.error = str(exc)[:2000]
            failed += 1
        else:
            delivery.status = "sent"
            delivery.sent_at = datetime.now(UTC)
            delivery.error = None
            sent += 1
        await session.commit()
        await asyncio.sleep(settings.bot_rate_limit_seconds)

    return NotificationResult(
        order_id=order_id, status="processed", sent=sent, skipped=skipped, failed=failed
    )


async def get_notifiable_order_card(
    session: AsyncSession,
    order_id: UUID,
    settings: Settings,
) -> OrderCard | None:
    cutoff = datetime.now(UTC) - timedelta(days=settings.relevance_freshness_days)
    row = (
        await session.execute(
            select(
                Order,
                TelegramSource.normalized_username,
                Message.message_url,
                DuplicateGroup.canonical_order_id,
            )
            .join(Message, Order.message_id == Message.id)
            .join(TelegramSource, Order.source_id == TelegramSource.id)
            .outerjoin(DuplicateGroup, Order.duplicate_group_id == DuplicateGroup.id)
            .where(Order.id == order_id)
        )
    ).one_or_none()
    if row is None:
        return None

    order, source_name, message_url, canonical_order_id = row
    is_canonical = canonical_order_id is None or canonical_order_id == order.id
    if not is_canonical:
        return None
    if not order.is_fresh or order.published_at < cutoff:
        return None
    if order.relevance_score < settings.order_min_relevance_score:
        return None
    if order.status in {"irrelevant", "archived"}:
        return None

    return OrderCard(
        order_id=str(order.id),
        source=source_name,
        published_at=order.published_at,
        project_type=order.project_type,
        summary=order.summary or order.title,
        budget_from=order.budget_from,
        budget_to=order.budget_to,
        budget_currency=order.budget_currency,
        deadline_text=order.deadline_text
        or (order.deadline.isoformat() if order.deadline else None),
        contact=first_contact(order.contacts),
        relevance_score=order.relevance_score,
        message_url=message_url,
    )


async def resolve_bot_recipients(session: AsyncSession, settings: Settings) -> list[BotRecipient]:
    env_ids = settings.parsed_bot_allowed_user_ids
    recipients_by_chat_id: dict[int, BotRecipient] = {}
    db_users = list(
        await session.scalars(
            select(User).where(User.is_active.is_(True), User.tg_chat_id.is_not(None))
        )
    )
    for user in db_users:
        if user.tg_chat_id is not None:
            recipients_by_chat_id[int(user.tg_chat_id)] = BotRecipient(
                user=user, tg_chat_id=int(user.tg_chat_id)
            )

    for tg_chat_id in env_ids:
        if tg_chat_id in recipients_by_chat_id:
            continue
        user = await get_or_create_bot_user(session, tg_chat_id)
        recipients_by_chat_id[tg_chat_id] = BotRecipient(user=user, tg_chat_id=tg_chat_id)
    await session.commit()
    return list(recipients_by_chat_id.values())


async def get_or_create_bot_user(session: AsyncSession, tg_chat_id: int) -> User:
    result = await session.scalars(select(User).where(User.tg_chat_id == tg_chat_id))
    user = result.one_or_none()
    if user is not None:
        return user

    user = User(
        email=f"bot-{tg_chat_id}@local",
        password_hash="bot-allowed-user",
        role="operator",
        is_active=True,
        tg_chat_id=tg_chat_id,
    )
    session.add(user)
    await session.flush()
    return user


async def get_or_create_delivery(
    session: AsyncSession,
    order_id: UUID,
    user_id: UUID,
) -> tuple[NotificationDelivery, bool]:
    result = await session.scalars(
        select(NotificationDelivery).where(
            NotificationDelivery.order_id == order_id,
            NotificationDelivery.user_id == user_id,
            NotificationDelivery.channel == "bot",
        )
    )
    delivery = result.one_or_none()
    if delivery is not None:
        return delivery, False

    delivery = NotificationDelivery(
        order_id=order_id,
        user_id=user_id,
        channel="bot",
        status="queued",
        dedup_key=f"bot:{order_id}:{user_id}",
    )
    session.add(delivery)
    await session.flush()
    return delivery, True


async def send_with_retry(
    sender: BotSender,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    settings: Settings,
) -> None:
    last_error: Exception | None = None
    for attempt in range(settings.bot_send_max_retries):
        try:
            await sender.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(min(2**attempt, 10))
    if last_error is not None:
        raise last_error


async def get_authorized_bot_user(session: AsyncSession, tg_user_id: int) -> User | None:
    settings = get_settings()
    result = await session.scalars(
        select(User).where(User.tg_chat_id == tg_user_id, User.is_active.is_(True))
    )
    user = result.one_or_none()
    if user is not None:
        return user
    if tg_user_id in settings.parsed_bot_allowed_user_ids:
        user = await get_or_create_bot_user(session, tg_user_id)
        await session.commit()
        return user
    return None


async def add_order_to_favorites_from_bot(
    session: AsyncSession, order_id: UUID, tg_user_id: int
) -> str:
    user = await get_authorized_bot_user(session, tg_user_id)
    if user is None:
        return "Нет доступа."
    principal = ApiPrincipal(role=user.role, key_name=f"bot-{tg_user_id}")
    await add_favorite(session, principal, order_id)
    return "Добавлено в избранное."


async def change_order_status_from_bot(
    session: AsyncSession,
    order_id: UUID,
    tg_user_id: int,
    status: str,
) -> str:
    user = await get_authorized_bot_user(session, tg_user_id)
    if user is None:
        return "Нет доступа."
    if user.role not in {"admin", "operator"}:
        return "Недостаточно прав."
    order = await session.get(Order, order_id)
    if order is None:
        return "Заказ не найден."
    try:
        await update_order_status(session, order_id, status, order.version)
    except ApiError as exc:
        return exc.message
    await add_audit_log(
        session,
        action="bot.callback.status",
        entity="order",
        entity_id=order_id,
        payload={"tg_user_id": tg_user_id, "status": status},
    )
    await session.commit()
    return "Статус обновлен."
