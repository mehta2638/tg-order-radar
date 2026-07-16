from __future__ import annotations

from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.services import (
    add_order_to_favorites_from_bot,
    change_order_status_from_bot,
    list_bot_subscriptions,
    set_bot_subscription_enabled,
)
from app.db.session import async_session_factory

router = Router(name="bot_handlers")


@router.message(Command("start", "help"))
async def start_handler(message: Message) -> None:
    await message.answer(
        "TG Order Radar\n"
        "/subscriptions — список подписок\n"
        "/subscription_on <id> — включить\n"
        "/subscription_off <id> — выключить\n"
        "Сложные фильтры настраиваются через API/admin."
    )


@router.message(Command("subscriptions"))
async def subscriptions_handler(message: Message) -> None:
    if message.from_user is None:
        return
    async with async_session_factory() as session:
        text = await list_bot_subscriptions(session, message.from_user.id)
    await message.answer(text)


@router.message(Command("subscription_on"))
async def subscription_on_handler(message: Message) -> None:
    await _toggle_subscription(message, enabled=True)


@router.message(Command("subscription_off"))
async def subscription_off_handler(message: Message) -> None:
    await _toggle_subscription(message, enabled=False)


async def _toggle_subscription(message: Message, *, enabled: bool) -> None:
    if message.from_user is None:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Укажите UUID подписки.")
        return
    try:
        subscription_id = UUID(parts[1])
    except ValueError:
        await message.answer("Некорректный UUID подписки.")
        return
    async with async_session_factory() as session:
        text = await set_bot_subscription_enabled(
            session, message.from_user.id, subscription_id, enabled
        )
    await message.answer(text)


@router.callback_query(
    lambda callback: callback.data is not None and callback.data.startswith("order:")
)
async def order_callback_handler(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    parsed = parse_order_callback(callback.data)
    if parsed is None:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return

    action, order_id, next_status = parsed
    async with async_session_factory() as session:
        if action == "fav":
            message = await add_order_to_favorites_from_bot(
                session, order_id, callback.from_user.id
            )
        else:
            message = await change_order_status_from_bot(
                session,
                order_id,
                callback.from_user.id,
                next_status or "",
            )
    await callback.answer(message, show_alert=False)


def parse_order_callback(data: str) -> tuple[str, UUID, str | None] | None:
    parts = data.split(":")
    try:
        if len(parts) == 3 and parts[0] == "order" and parts[1] == "fav":
            return ("fav", UUID(parts[2]), None)
        if len(parts) == 4 and parts[0] == "order" and parts[1] == "status":
            if parts[2] not in {"contacted", "irrelevant"}:
                return None
            return ("status", UUID(parts[3]), parts[2])
        return None
    except ValueError:
        return None
