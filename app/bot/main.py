from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher

from app.bot.handlers import router as bot_router
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(bot_router)
    return dispatcher


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required to start Telegram bot polling.")

    bot = Bot(token=settings.bot_token)
    dispatcher = create_dispatcher()
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
