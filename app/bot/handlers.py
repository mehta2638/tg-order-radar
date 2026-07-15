from __future__ import annotations

from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from app.bot.services import add_order_to_favorites_from_bot, change_order_status_from_bot
from app.db.session import async_session_factory

router = Router(name="order_callbacks")


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
