from pathlib import Path

from telethon import TelegramClient

from app.core.config import Settings, get_settings
from app.models import TelegramAccount


class TelegramSettingsError(RuntimeError):
    pass


class TelegramAccountNotAuthorizedError(RuntimeError):
    pass


def get_session_path(
    settings: Settings | None = None,
    *,
    session_name: str | None = None,
) -> Path:
    active_settings = settings or get_settings()
    name = session_name or active_settings.tg_session_name
    return Path(active_settings.tg_session_dir) / name


def create_telegram_client(
    settings: Settings | None = None,
    *,
    session_name: str | None = None,
) -> TelegramClient:
    active_settings = settings or get_settings()
    if active_settings.tg_api_id is None or not active_settings.tg_api_hash:
        raise TelegramSettingsError("TG_API_ID and TG_API_HASH must be configured.")

    session_path = get_session_path(active_settings, session_name=session_name)
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
    return await get_authorized_client_for_session(
        session_name=None,
        settings=settings,
    )


async def get_authorized_client_for_session(
    session_name: str | None,
    settings: Settings | None = None,
) -> TelegramClient:
    client = create_telegram_client(settings, session_name=session_name)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise TelegramAccountNotAuthorizedError(
            "Telegram account is not authorized. Run python -m scripts.auth_telegram first."
        )
    return client


async def get_authorized_client_for_account(
    account: TelegramAccount,
    settings: Settings | None = None,
) -> TelegramClient:
    session_name = account.session_ref or account.label
    return await get_authorized_client_for_session(session_name, settings=settings)
