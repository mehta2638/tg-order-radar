from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ApiPrincipal
from app.bot.cards import OrderCard, build_order_keyboard, first_contact, render_order_card
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.models import (
    DuplicateGroup,
    Message,
    NotificationDelivery,
    NotificationSubscription,
    Order,
    TelegramSource,
    User,
)
from app.monitoring.metrics import record_notification
from app.services.audit import add_audit_log
from app.services.favorites import add_favorite
from app.services.orders import update_order_status
from app.services.subscription_matching import (
    is_in_quiet_hours,
    next_quiet_hours_end,
    subscription_matches_order,
)


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
    deferred: int = 0


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

    order = await session.get(Order, order_id)
    if order is None:
        return NotificationResult(order_id=order_id, status="skipped")
    message = await session.get(Message, order.message_id)

    recipients = await resolve_bot_recipients(session, settings)
    if not recipients:
        return NotificationResult(order_id=order_id, status="no_recipients")

    sent = 0
    skipped = 0
    failed = 0
    deferred = 0
    now = datetime.now(UTC)
    for recipient in recipients:
        subscription = await find_matching_subscription(
            session, recipient.user, order, message, now=now
        )
        if subscription is None:
            skipped += 1
            continue

        if await is_rate_limited(session, recipient.user.id, subscription, now=now):
            skipped += 1
            continue
        if await is_similar_cooldown_active(
            session, recipient.user.id, order, subscription, now=now
        ):
            skipped += 1
            continue

        delivery, created = await get_or_create_delivery(
            session,
            order_id,
            recipient.user.id,
            subscription_id=subscription.id,
        )
        if not created:
            if delivery.status == "deferred" and (
                delivery.scheduled_for is None or delivery.scheduled_for <= now
            ):
                pass
            else:
                skipped += 1
                continue

        if is_in_quiet_hours(
            now,
            start=subscription.quiet_hours_start,
            end=subscription.quiet_hours_end,
            timezone_name=subscription.timezone,
        ):
            scheduled_for = next_quiet_hours_end(
                now,
                start=subscription.quiet_hours_start,
                end=subscription.quiet_hours_end,
                timezone_name=subscription.timezone,
            )
            delivery.status = "deferred"
            delivery.scheduled_for = scheduled_for
            delivery.subscription_id = subscription.id
            deferred += 1
            await session.commit()
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
            delivery.scheduled_for = None
            delivery.subscription_id = subscription.id
            delivery.error = None
            order.notified_at = delivery.sent_at
            sent += 1
        await session.commit()
        await asyncio.sleep(settings.bot_rate_limit_seconds)

    record_notification("sent", sent)
    record_notification("skipped", skipped)
    record_notification("failed", failed)
    record_notification("deferred", deferred)
    return NotificationResult(
        order_id=order_id,
        status="processed",
        sent=sent,
        skipped=skipped,
        failed=failed,
        deferred=deferred,
    )


async def process_deferred_notifications(
    session: AsyncSession,
    sender: BotSender,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    deliveries = list(
        await session.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == "deferred",
                NotificationDelivery.scheduled_for.is_not(None),
                NotificationDelivery.scheduled_for <= now,
            )
            .order_by(NotificationDelivery.scheduled_for.asc())
            .limit(100)
        )
    )
    sent = 0
    failed = 0
    skipped = 0
    for delivery in deliveries:
        card = await get_notifiable_order_card(session, delivery.order_id, settings)
        user = await session.get(User, delivery.user_id)
        if card is None or user is None or user.tg_chat_id is None or not user.is_active:
            delivery.status = "skipped"
            skipped += 1
            await session.commit()
            continue
        try:
            await send_with_retry(
                sender,
                int(user.tg_chat_id),
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
            delivery.scheduled_for = None
            delivery.error = None
            order = await session.get(Order, delivery.order_id)
            if order is not None:
                order.notified_at = delivery.sent_at
            sent += 1
        await session.commit()
        await asyncio.sleep(settings.bot_rate_limit_seconds)
    return {"sent": sent, "failed": failed, "skipped": skipped, "processed": len(deliveries)}


async def find_matching_subscription(
    session: AsyncSession,
    user: User,
    order: Order,
    message: Message | None,
    *,
    now: datetime | None = None,
) -> NotificationSubscription | None:
    subscriptions = list(
        await session.scalars(
            select(NotificationSubscription).where(
                NotificationSubscription.user_id == user.id,
                NotificationSubscription.enabled.is_(True),
            )
        )
    )
    if not subscriptions:
        return None
    active_now = now or datetime.now(UTC)
    matches = [
        subscription
        for subscription in subscriptions
        if subscription_matches_order(subscription, order, message, now_utc=active_now)
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: (item.created_at, str(item.id)))
    return matches[0]


async def is_rate_limited(
    session: AsyncSession,
    user_id: UUID,
    subscription: NotificationSubscription,
    *,
    now: datetime,
) -> bool:
    if subscription.max_notifications_per_period is None:
        return False
    cutoff = now - timedelta(minutes=subscription.rate_limit_period_minutes)
    count = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.user_id == user_id,
            NotificationDelivery.status == "sent",
            NotificationDelivery.sent_at.is_not(None),
            NotificationDelivery.sent_at >= cutoff,
        )
    )
    return int(count or 0) >= subscription.max_notifications_per_period


async def is_similar_cooldown_active(
    session: AsyncSession,
    user_id: UUID,
    order: Order,
    subscription: NotificationSubscription,
    *,
    now: datetime,
) -> bool:
    if subscription.similar_cooldown_minutes is None or not order.duplicate_fingerprint:
        return False
    cutoff = now - timedelta(minutes=subscription.similar_cooldown_minutes)
    existing = await session.scalar(
        select(NotificationDelivery.id)
        .join(Order, Order.id == NotificationDelivery.order_id)
        .where(
            NotificationDelivery.user_id == user_id,
            NotificationDelivery.status == "sent",
            NotificationDelivery.sent_at.is_not(None),
            NotificationDelivery.sent_at >= cutoff,
            Order.duplicate_fingerprint == order.duplicate_fingerprint,
            Order.id != order.id,
        )
        .limit(1)
    )
    return existing is not None


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
        if user.tg_chat_id is None:
            continue
        chat_id = int(user.tg_chat_id)
        if env_ids and chat_id not in env_ids:
            continue
        recipients_by_chat_id[chat_id] = BotRecipient(user=user, tg_chat_id=chat_id)

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
    *,
    subscription_id: UUID | None = None,
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
        subscription_id=subscription_id,
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


def summarize_subscription(subscription: NotificationSubscription) -> str:
    parts = [f"#{str(subscription.id)[:8]}", subscription.name]
    parts.append("on" if subscription.enabled else "off")
    if subscription.min_relevance_score is not None:
        parts.append(f"rel>={subscription.min_relevance_score}")
    if subscription.project_types:
        parts.append("types=" + ",".join(str(item) for item in subscription.project_types[:5]))
    if subscription.quiet_hours_start and subscription.quiet_hours_end:
        parts.append(
            f"quiet {subscription.quiet_hours_start}-{subscription.quiet_hours_end}"
            f" {subscription.timezone}"
        )
    return " | ".join(parts)


async def list_bot_subscriptions(session: AsyncSession, tg_user_id: int) -> str:
    user = await get_authorized_bot_user(session, tg_user_id)
    if user is None:
        return "Нет доступа."
    subscriptions = list(
        await session.scalars(
            select(NotificationSubscription)
            .where(NotificationSubscription.user_id == user.id)
            .order_by(NotificationSubscription.created_at.desc())
        )
    )
    if not subscriptions:
        return "Подписок нет. Создайте через API /admin frontend."
    lines = ["Ваши подписки:"]
    lines.extend(summarize_subscription(item) for item in subscriptions)
    return "\n".join(lines)


async def set_bot_subscription_enabled(
    session: AsyncSession,
    tg_user_id: int,
    subscription_id: UUID,
    enabled: bool,
) -> str:
    user = await get_authorized_bot_user(session, tg_user_id)
    if user is None:
        return "Нет доступа."
    subscription = await session.get(NotificationSubscription, subscription_id)
    if subscription is None or subscription.user_id != user.id:
        return "Подписка не найдена."
    subscription.enabled = enabled
    await add_audit_log(
        session,
        action="subscription.enable" if enabled else "subscription.disable",
        entity="notification_subscription",
        entity_id=subscription.id,
        payload={"tg_user_id": tg_user_id, "enabled": enabled},
    )
    await session.commit()
    return f"Подписка {'включена' if enabled else 'выключена'}."
