import asyncio

from app.collector.telethon_client import create_telegram_client, get_session_path
from app.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    if settings.tg_phone is None:
        raise RuntimeError("TG_PHONE must be configured for interactive authorization.")

    client = create_telegram_client(settings)
    try:
        await client.start(phone=settings.tg_phone)
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram authorization did not complete successfully.")
        print(f"Telegram session saved to {get_session_path(settings)}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
