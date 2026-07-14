from pathlib import Path

from telethon import TelegramClient

from app.core.config import Settings, get_settings


class TelegramSettingsError(RuntimeError):
    pass


class TelegramAccountNotAuthorizedError(RuntimeError):
    pass


def get_session_path(settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    return Path(active_settings.tg_session_dir) / active_settings.tg_session_name


def create_telegram_client(settings: Settings | None = None) -> TelegramClient:
    active_settings = settings or get_settings()
    if active_settings.tg_api_id is None or not active_settings.tg_api_hash:
        raise TelegramSettingsError("TG_API_ID and TG_API_HASH must be configured.")

    session_path = get_session_path(active_settings)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    return TelegramClient(
        str(session_path),
        active_settings.tg_api_id,
        active_settings.tg_api_hash,
        connection_retries=5,
        retry_delay=2,
        auto_reconnect=True,
    )


async def get_authorized_client(settings: Settings | None = None) -> TelegramClient:
    client = create_telegram_client(settings)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise TelegramAccountNotAuthorizedError(
            "Telegram account is not authorized. Run python -m scripts.auth_telegram first."
        )
    return client
