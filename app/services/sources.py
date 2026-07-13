from uuid import UUID

from fastapi import status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import TelegramSource
from app.services.audit import add_audit_log
from app.services.source_links import normalize_source_link


async def create_source(session: AsyncSession, raw_link: str) -> TelegramSource:
    normalized_link = normalize_source_link(raw_link)
    existing_source = await get_source_by_normalized_username(
        session,
        normalized_link.normalized_username,
    )
    if existing_source is not None:
        raise_source_exists(normalized_link.normalized_username)

    source = TelegramSource(
        username=normalized_link.username,
        normalized_username=normalized_link.normalized_username,
        access_status="pending_validation",
        type="unknown",
        is_public=False,
        enabled=True,
    )
    session.add(source)
    await session.flush()
    await add_audit_log(
        session,
        action="source.create",
        entity="telegram_source",
        entity_id=source.id,
        payload={"normalized_username": source.normalized_username},
    )

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise_source_exists(normalized_link.normalized_username, exc)

    await session.refresh(source)
    return source


async def list_sources(
    session: AsyncSession,
    page: int,
    size: int,
    q: str | None = None,
) -> tuple[list[TelegramSource], int]:
    statement: Select[tuple[TelegramSource]] = select(TelegramSource).order_by(
        TelegramSource.created_at.desc(),
        TelegramSource.id.desc(),
    )
    count_statement = select(func.count()).select_from(TelegramSource)

    if q:
        normalized_q = f"%{q.strip().lower()}%"
        statement = statement.where(TelegramSource.normalized_username.ilike(normalized_q))
        count_statement = count_statement.where(
            TelegramSource.normalized_username.ilike(normalized_q)
        )

    total = await session.scalar(count_statement)
    result = await session.scalars(statement.offset((page - 1) * size).limit(size))
    return list(result), total or 0


async def get_source(session: AsyncSession, source_id: UUID) -> TelegramSource:
    source = await session.get(TelegramSource, source_id)
    if source is None:
        raise ApiError(
            code="SOURCE_NOT_FOUND",
            message="Telegram source was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"source_id": str(source_id)},
        )
    return source


async def set_source_enabled(
    session: AsyncSession,
    source_id: UUID,
    enabled: bool,
) -> TelegramSource:
    source = await get_source(session, source_id)
    if source.enabled != enabled:
        source.enabled = enabled
        await add_audit_log(
            session,
            action="source.update_enabled",
            entity="telegram_source",
            entity_id=source.id,
            payload={"enabled": enabled},
        )
        await session.commit()
        await session.refresh(source)
    return source


async def disable_source(session: AsyncSession, source_id: UUID) -> None:
    source = await get_source(session, source_id)
    if source.enabled:
        source.enabled = False
        await add_audit_log(
            session,
            action="source.disable",
            entity="telegram_source",
            entity_id=source.id,
            payload={"enabled": False},
        )
        await session.commit()


async def get_source_by_normalized_username(
    session: AsyncSession,
    normalized_username: str,
) -> TelegramSource | None:
    result = await session.scalars(
        select(TelegramSource).where(TelegramSource.normalized_username == normalized_username)
    )
    return result.one_or_none()


def raise_source_exists(normalized_username: str, cause: Exception | None = None) -> None:
    error = ApiError(
        code="SOURCE_EXISTS",
        message="Telegram source already exists.",
        status_code=status.HTTP_409_CONFLICT,
        details={"normalized_username": normalized_username},
    )
    if cause is not None:
        raise error from cause
    raise error
