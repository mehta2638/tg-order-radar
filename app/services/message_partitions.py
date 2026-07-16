"""Monthly RANGE partitions for messages + retention via DROP PARTITION."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings

PARTITION_NAME_RE = re.compile(r"^messages_(\d{4})_(\d{2})$")


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    return date(year, month, 1)


def partition_name(value: date) -> str:
    return f"messages_{value.year:04d}_{value.month:02d}"


def partition_bounds(value: date) -> tuple[date, date]:
    start = month_start(value)
    end = add_months(start, 1)
    return start, end


async def list_message_partitions(session: AsyncSession) -> list[str]:
    rows = await session.execute(
        text(
            """
            select c.relname as name
            from pg_inherits i
            join pg_class c on c.oid = i.inhrelid
            join pg_class p on p.oid = i.inhparent
            where p.relname = 'messages'
            order by c.relname
            """
        )
    )
    return [str(row.name) for row in rows]


async def ensure_month_partition(session: AsyncSession, value: date) -> str:
    name = partition_name(value)
    start, end = partition_bounds(value)
    start_ts = datetime(start.year, start.month, start.day, tzinfo=UTC).isoformat()
    end_ts = datetime(end.year, end.month, end.day, tzinfo=UTC).isoformat()
    await session.execute(
        text(
            f"""
            create table if not exists {name}
            partition of messages
            for values from ('{start_ts}') to ('{end_ts}')
            """
        )
    )
    return name


async def ensure_message_partitions(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    active = settings or get_settings()
    current = month_start((now or datetime.now(UTC)).date())
    created: list[str] = []
    ensured: list[str] = []

    # Always keep a DEFAULT partition for out-of-range rows.
    await session.execute(
        text(
            """
            do $$
            begin
                if not exists (
                    select 1 from pg_class c
                    join pg_inherits i on i.inhrelid = c.oid
                    join pg_class p on p.oid = i.inhparent
                    where p.relname = 'messages' and c.relname = 'messages_default'
                ) then
                    create table messages_default partition of messages default;
                end if;
            end $$;
            """
        )
    )

    months_behind = max(active.messages_partition_months_behind, 0)
    months_ahead = max(active.messages_partition_months_ahead, 0)
    existing = set(await list_message_partitions(session))

    cursor = add_months(current, -months_behind)
    last = add_months(current, months_ahead)
    while cursor <= last:
        name = partition_name(cursor)
        ensured.append(name)
        if name not in existing:
            await ensure_month_partition(session, cursor)
            created.append(name)
            existing.add(name)
        cursor = add_months(cursor, 1)

    await session.commit()
    return {"ensured": ensured, "created": created}


async def drop_expired_message_partitions(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    active = settings or get_settings()
    retention_days = max(active.messages_retention_days, 30)
    cutoff = (now or datetime.now(UTC)).date() - timedelta(days=retention_days)
    cutoff_month = month_start(cutoff)

    dropped: list[str] = []
    for name in await list_message_partitions(session):
        if name == "messages_default":
            continue
        match = PARTITION_NAME_RE.match(name)
        if match is None:
            continue
        part_month = date(int(match.group(1)), int(match.group(2)), 1)
        # Drop only full months strictly older than the retention cutoff month.
        if part_month < cutoff_month:
            await session.execute(text(f"drop table if exists {name}"))
            dropped.append(name)

    await session.commit()
    return {
        "retention_days": retention_days,
        "cutoff_month": cutoff_month.isoformat(),
        "dropped": dropped,
    }
