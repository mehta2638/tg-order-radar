"""Multi-account pool for legitimate read-load distribution only.

Never used to bypass FloodWait: paused accounts stay paused until Telegram's wait expires.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import TelegramAccount


def now_utc() -> datetime:
    return datetime.now(UTC)


def session_names_from_settings(settings: Settings | None = None) -> list[str]:
    active = settings or get_settings()
    raw = active.tg_session_names.strip()
    if raw:
        names = [part.strip() for part in raw.split(",") if part.strip()]
        return names or [active.tg_session_name]
    return [active.tg_session_name]


def select_account_for_source(
    source_id: UUID,
    accounts: list[TelegramAccount],
) -> TelegramAccount | None:
    if not accounts:
        return None
    digest = hashlib.sha256(str(source_id).encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(accounts)
    return accounts[index]


async def sync_accounts_from_settings(
    session: AsyncSession,
    settings: Settings | None = None,
) -> list[TelegramAccount]:
    active = settings or get_settings()
    synced: list[TelegramAccount] = []
    for label in session_names_from_settings(active):
        account = await session.scalar(
            select(TelegramAccount).where(TelegramAccount.label == label)
        )
        if account is None:
            account = TelegramAccount(
                label=label,
                session_ref=label,
                status="active",
            )
            session.add(account)
        else:
            if not account.session_ref:
                account.session_ref = label
            if account.status == "disabled":
                # Keep disabled accounts out of the pool unless operator re-enables them.
                pass
        synced.append(account)
    await session.flush()
    return synced


async def list_available_accounts(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
) -> list[TelegramAccount]:
    await recover_expired_account_floodwaits(session)
    await sync_accounts_from_settings(session, settings=settings)
    result = await session.scalars(
        select(TelegramAccount)
        .where(
            TelegramAccount.status == "active",
            or_(
                TelegramAccount.floodwait_until.is_(None),
                TelegramAccount.floodwait_until <= now_utc(),
            ),
        )
        .order_by(TelegramAccount.label.asc())
    )
    return list(result)


async def resolve_account_for_source(
    session: AsyncSession,
    source_id: UUID,
    *,
    settings: Settings | None = None,
) -> TelegramAccount | None:
    accounts = await list_available_accounts(session, settings=settings)
    return select_account_for_source(source_id, accounts)


async def mark_account_floodwait(
    session: AsyncSession,
    account: TelegramAccount,
    seconds: int,
) -> None:
    """Pause the account for Telegram's wait. Do not rotate around the wait."""
    until = now_utc() + timedelta(seconds=max(seconds, 0))
    account.status = "floodwait"
    account.floodwait_until = until
    account.last_used_at = now_utc()
    await session.flush()


async def touch_account_used(session: AsyncSession, account: TelegramAccount) -> None:
    account.last_used_at = now_utc()
    await session.flush()


async def recover_expired_account_floodwaits(session: AsyncSession) -> int:
    now = now_utc()
    accounts = list(
        await session.scalars(
            select(TelegramAccount).where(
                TelegramAccount.status == "floodwait",
                TelegramAccount.floodwait_until.is_not(None),
                TelegramAccount.floodwait_until <= now,
            )
        )
    )
    for account in accounts:
        account.status = "active"
        account.floodwait_until = None
    if accounts:
        await session.flush()
    return len(accounts)
