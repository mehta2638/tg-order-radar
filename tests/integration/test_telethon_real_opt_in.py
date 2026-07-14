import os

import pytest

from app.collector.telethon_client import TelegramAccountNotAuthorizedError, get_authorized_client
from app.core.config import get_settings


@pytest.mark.skipif(
    not os.getenv("TG_PUBLIC_TEST_SOURCE"),
    reason="Set TG_PUBLIC_TEST_SOURCE and authorized Telegram env to run real Telethon test.",
)
async def test_real_public_telegram_source_can_be_read() -> None:
    settings = get_settings()
    if settings.tg_api_id is None or not settings.tg_api_hash:
        pytest.skip("TG_API_ID and TG_API_HASH are required for real Telethon test.")

    try:
        client = await get_authorized_client(settings)
    except TelegramAccountNotAuthorizedError as exc:
        pytest.skip(str(exc))

    try:
        entity = await client.get_entity(os.environ["TG_PUBLIC_TEST_SOURCE"])
        assert getattr(entity, "username", None)
        await client.get_messages(entity, limit=1)
    finally:
        await client.disconnect()
