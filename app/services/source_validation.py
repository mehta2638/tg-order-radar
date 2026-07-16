from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import ChannelPrivateError, FloodWaitError, RPCError, UsernameNotOccupiedError
from telethon.utils import get_peer_id

from app.collector.telethon_client import (
    TelegramAccountNotAuthorizedError,
    TelegramSettingsError,
    get_authorized_client,
)
from app.core.errors import ApiError
from app.models import TelegramSource
from app.monitoring.metrics import record_telegram_error
from app.services.audit import add_audit_log
from app.services.sources import get_source


class TelegramValidationClient(Protocol):
    async def get_entity(self, username: str) -> object: ...

    async def get_messages(self, entity: object, limit: int) -> object: ...

    async def disconnect(self) -> None: ...


ClientFactory = Callable[[], Awaitable[TelegramValidationClient]]


async def validate_source(
    session: AsyncSession,
    source_id: UUID,
    client_factory: ClientFactory = get_authorized_client,
) -> TelegramSource:
    source = await get_source(session, source_id)
    if not source.normalized_username:
        source.access_status = "error"
        source.is_public = False
        source.last_checked_at = now_utc()
        await commit_validation_result(
            session,
            source,
            {"reason": "missing_normalized_username"},
        )
        return source

    try:
        client = await client_factory()
    except TelegramSettingsError as exc:
        raise ApiError(
            code="TELEGRAM_NOT_CONFIGURED",
            message="Telegram API credentials are not configured.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    except TelegramAccountNotAuthorizedError as exc:
        raise ApiError(
            code="TELEGRAM_ACCOUNT_NOT_AUTHORIZED",
            message="Telegram account is not authorized.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    try:
        entity = await client.get_entity(source.normalized_username)
        await client.get_messages(entity, limit=1)
        apply_successful_validation(source, entity)
        await commit_validation_result(session, source, {"access_status": "ok"})
    except UsernameNotOccupiedError:
        record_telegram_error("not_found")
        await apply_failed_validation(session, source, "not_found")
    except ChannelPrivateError:
        record_telegram_error("private")
        await apply_failed_validation(session, source, "private")
    except FloodWaitError as exc:
        record_telegram_error("floodwait")
        source.access_status = "floodwait"
        source.is_public = False
        source.pause_until = now_utc() + timedelta(seconds=exc.seconds)
        source.last_checked_at = now_utc()
        await commit_validation_result(
            session,
            source,
            {"access_status": "floodwait", "seconds": exc.seconds},
        )
    except (OSError, ConnectionError, RPCError) as exc:
        record_telegram_error("rpc_error")
        source.access_status = "error"
        source.is_public = False
        source.last_checked_at = now_utc()
        await commit_validation_result(
            session,
            source,
            {"access_status": "error", "error_type": type(exc).__name__},
        )
    finally:
        await client.disconnect()

    return source


def apply_successful_validation(source: TelegramSource, entity: object) -> None:
    username = getattr(entity, "username", None)
    is_channel = bool(getattr(entity, "broadcast", False))
    is_group = bool(getattr(entity, "megagroup", False))
    if not isinstance(username, str) or not username or not (is_channel or is_group):
        raise ChannelPrivateError(request=None)

    source.tg_peer_id = extract_peer_id(entity)
    source.title = str(getattr(entity, "title", ""))
    source.username = username
    source.normalized_username = username.lower()
    source.type = "megagroup" if is_group else "channel"
    source.participants_count = get_participants_count(entity)
    source.is_public = True
    source.access_status = "ok"
    source.pause_until = None
    source.last_checked_at = now_utc()


def get_participants_count(entity: object) -> int | None:
    value = getattr(entity, "participants_count", None)
    return value if isinstance(value, int) else None


def extract_peer_id(entity: object) -> int:
    test_peer_id = getattr(entity, "peer_id", None)
    if isinstance(test_peer_id, int):
        return test_peer_id
    return int(get_peer_id(entity))


async def apply_failed_validation(
    session: AsyncSession,
    source: TelegramSource,
    access_status: str,
) -> None:
    source.access_status = access_status
    source.is_public = False
    source.last_checked_at = now_utc()
    await commit_validation_result(session, source, {"access_status": access_status})


async def commit_validation_result(
    session: AsyncSession,
    source: TelegramSource,
    payload: dict[str, Any],
) -> None:
    await add_audit_log(
        session,
        action="source.validate",
        entity="telegram_source",
        entity_id=source.id,
        payload=payload,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            code="SOURCE_EXISTS",
            message="Telegram source already exists.",
            status_code=status.HTTP_409_CONFLICT,
            details={
                "tg_peer_id": source.tg_peer_id,
                "normalized_username": source.normalized_username,
            },
        ) from exc
    await session.refresh(source)


def now_utc() -> datetime:
    return datetime.now(UTC)
