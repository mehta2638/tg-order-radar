"""Restore sources/accounts after FloodWait windows expire. No early retries."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.accounts import recover_expired_account_floodwaits
from app.models import TelegramSource


def now_utc() -> datetime:
    return datetime.now(UTC)


async def recover_expired_source_floodwaits(session: AsyncSession) -> int:
    now = now_utc()
    sources = list(
        await session.scalars(
            select(TelegramSource).where(
                TelegramSource.access_status == "floodwait",
                TelegramSource.pause_until.is_not(None),
                TelegramSource.pause_until <= now,
            )
        )
    )
    for source in sources:
        source.access_status = "ok"
        source.pause_until = None
        # Sources paused during collection were already public/ok before FloodWait.
        if source.normalized_username:
            source.is_public = True
    if sources:
        await session.flush()
    return len(sources)


async def recover_expired_floodwaits(session: AsyncSession) -> dict[str, int]:
    accounts = await recover_expired_account_floodwaits(session)
    sources = await recover_expired_source_floodwaits(session)
    await session.commit()
    return {"accounts": accounts, "sources": sources}
