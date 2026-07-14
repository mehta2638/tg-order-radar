from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError

from app.collector.leases import RedisSourceLease, SourceLease
from app.collector.telethon_client import get_authorized_client
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Message, TelegramSource


class TelegramCollectorClient(Protocol):
    async def get_entity(self, username: str) -> object: ...

    def iter_messages(
        self,
        entity: object,
        *,
        min_id: int = 0,
        limit: int | None = None,
    ) -> AsyncIterator[object]: ...

    async def get_messages(self, entity: object, ids: list[int]) -> list[object | None]: ...

    async def disconnect(self) -> None: ...


ClientFactory = Callable[[], Awaitable[TelegramCollectorClient]]
LeaseFactory = Callable[[str, int], SourceLease]
EnqueueMessageProcessing = Callable[[UUID, str | None], None]


@dataclass(frozen=True)
class CollectionResult:
    source_id: UUID
    status: str
    saved: int = 0
    updated: int = 0
    deleted: int = 0
    enqueued: int = 0
    last_seen_message_id: int = 0


@dataclass(frozen=True)
class MessageSnapshot:
    tg_message_id: int
    published_at: datetime
    edited_at: datetime | None
    forward_original_date: datetime | None
    text: str | None
    message_url: str | None
    views_count: int | None
    replies_count: int | None
    content_hash: str
    raw_payload: dict[str, Any]


async def collect_source_messages(
    source_id: UUID,
    *,
    client_factory: ClientFactory = get_authorized_client,
    lease_factory: LeaseFactory | None = None,
    enqueue_message_processing: EnqueueMessageProcessing | None = None,
    correlation_id: str | None = None,
) -> CollectionResult:
    settings = get_settings()
    active_lease_factory = lease_factory or RedisSourceLease
    async with active_lease_factory(
        str(source_id), settings.collector_lease_ttl_seconds
    ) as acquired:
        if not acquired:
            return CollectionResult(source_id=source_id, status="locked")

        client = await client_factory()
        try:
            async with async_session_factory() as session:
                source = await get_collectable_source(session, source_id)
                if source is None:
                    return CollectionResult(source_id=source_id, status="skipped")

                now = now_utc()
                if source.pause_until is not None and source.pause_until > now:
                    return CollectionResult(source_id=source_id, status="paused")

                return await collect_with_client(
                    session,
                    client,
                    source,
                    enqueue_message_processing=enqueue_message_processing,
                    correlation_id=correlation_id,
                )
        finally:
            await client.disconnect()


async def collect_with_client(
    session: AsyncSession,
    client: TelegramCollectorClient,
    source: TelegramSource,
    *,
    enqueue_message_processing: EnqueueMessageProcessing | None,
    correlation_id: str | None,
) -> CollectionResult:
    username = source.normalized_username or source.username
    if not username:
        return CollectionResult(source_id=source.id, status="skipped")

    try:
        entity = await client.get_entity(username)
        snapshots = await fetch_message_snapshots(client, entity, source)
    except FloodWaitError as exc:
        source.access_status = "floodwait"
        source.pause_until = now_utc() + timedelta(seconds=exc.seconds)
        await session.commit()
        return CollectionResult(source_id=source.id, status="floodwait")

    saved = 0
    updated = 0
    enqueued_ids: list[UUID] = []
    max_seen = source.last_seen_message_id

    for snapshot in sorted(snapshots, key=lambda item: item.tg_message_id):
        message, changed, inserted = await upsert_message(session, source, snapshot)
        max_seen = max(max_seen, snapshot.tg_message_id)
        if inserted:
            saved += 1
        elif changed:
            updated += 1
        if inserted or changed:
            enqueued_ids.append(message.id)

    deleted, synced_updated, synced_message_ids = await sync_existing_messages(
        session,
        client,
        entity,
        source,
    )
    updated += synced_updated
    enqueued_ids.extend(synced_message_ids)

    source.last_seen_message_id = max_seen
    source.last_checked_at = now_utc()
    await session.commit()

    if enqueue_message_processing is not None:
        for message_id in enqueued_ids:
            enqueue_message_processing(message_id, correlation_id)

    return CollectionResult(
        source_id=source.id,
        status="ok",
        saved=saved,
        updated=updated,
        deleted=deleted,
        enqueued=len(enqueued_ids),
        last_seen_message_id=max_seen,
    )


async def get_collectable_source(
    session: AsyncSession,
    source_id: UUID,
) -> TelegramSource | None:
    result = await session.scalars(
        select(TelegramSource).where(
            TelegramSource.id == source_id,
            TelegramSource.enabled.is_(True),
            TelegramSource.access_status == "ok",
            TelegramSource.is_public.is_(True),
        )
    )
    return result.one_or_none()


async def fetch_message_snapshots(
    client: TelegramCollectorClient,
    entity: object,
    source: TelegramSource,
) -> list[MessageSnapshot]:
    settings = get_settings()
    cutoff = now_utc() - timedelta(
        days=settings.collector_backfill_days + settings.collector_backfill_buffer_days
    )
    is_initial_backfill = source.last_seen_message_id <= 0
    snapshots: list[MessageSnapshot] = []

    async for raw_message in client.iter_messages(
        entity,
        min_id=source.last_seen_message_id,
        limit=settings.collector_batch_limit,
    ):
        snapshot = snapshot_from_message(source, raw_message)
        if is_initial_backfill and snapshot.published_at < cutoff:
            continue
        snapshots.append(snapshot)

    return snapshots


async def upsert_message(
    session: AsyncSession,
    source: TelegramSource,
    snapshot: MessageSnapshot,
) -> tuple[Message, bool, bool]:
    existing = await session.scalar(
        select(Message).where(
            Message.source_id == source.id,
            Message.tg_message_id == snapshot.tg_message_id,
        )
    )
    if existing is None:
        message = Message(
            source_id=source.id,
            tg_message_id=snapshot.tg_message_id,
            published_at=snapshot.published_at,
            collected_at=now_utc(),
            edited_at=snapshot.edited_at,
            deleted_at=None,
            forward_original_date=snapshot.forward_original_date,
            text=snapshot.text,
            normalized_text=snapshot.text,
            content_hash=snapshot.content_hash,
            message_url=snapshot.message_url,
            views_count=snapshot.views_count,
            replies_count=snapshot.replies_count,
            raw_payload=snapshot.raw_payload,
        )
        session.add(message)
        await session.flush()
        return message, True, True

    changed = apply_snapshot(existing, snapshot)
    return existing, changed, False


def apply_snapshot(message: Message, snapshot: MessageSnapshot) -> bool:
    changed = False
    updates = {
        "published_at": snapshot.published_at,
        "edited_at": snapshot.edited_at,
        "deleted_at": None,
        "forward_original_date": snapshot.forward_original_date,
        "text": snapshot.text,
        "normalized_text": snapshot.text,
        "content_hash": snapshot.content_hash,
        "message_url": snapshot.message_url,
        "views_count": snapshot.views_count,
        "replies_count": snapshot.replies_count,
        "raw_payload": snapshot.raw_payload,
    }
    for field_name, value in updates.items():
        if getattr(message, field_name) != value:
            setattr(message, field_name, value)
            changed = True
    if changed:
        message.collected_at = now_utc()
    return changed


async def sync_existing_messages(
    session: AsyncSession,
    client: TelegramCollectorClient,
    entity: object,
    source: TelegramSource,
) -> tuple[int, int, list[UUID]]:
    known_messages = list(
        await session.scalars(
            select(Message).where(
                Message.source_id == source.id,
                Message.deleted_at.is_(None),
            )
        )
    )
    if not known_messages:
        return 0, 0, []

    known_by_tg_id = {message.tg_message_id: message for message in known_messages}
    known_ids = list(known_by_tg_id)
    existing_raw_messages = await client.get_messages(entity, ids=known_ids)
    now = now_utc()
    deleted = 0
    updated = 0
    changed_message_ids: list[UUID] = []

    for tg_message_id, raw_message in zip(known_ids, existing_raw_messages, strict=False):
        message = known_by_tg_id[tg_message_id]
        if raw_message is None:
            message.deleted_at = now
            deleted += 1
            changed_message_ids.append(message.id)
            continue

        snapshot = snapshot_from_message(source, raw_message)
        if apply_snapshot(message, snapshot):
            updated += 1
            changed_message_ids.append(message.id)

    return deleted, updated, changed_message_ids


def snapshot_from_message(source: TelegramSource, raw_message: object) -> MessageSnapshot:
    telegram_message = cast(Any, raw_message)
    tg_message_id = int(telegram_message.id)
    text = get_message_text(raw_message)
    raw_payload = build_raw_payload(raw_message)
    return MessageSnapshot(
        tg_message_id=tg_message_id,
        published_at=ensure_utc(telegram_message.date),
        edited_at=ensure_optional_utc(getattr(raw_message, "edit_date", None)),
        forward_original_date=get_forward_original_date(raw_message),
        text=text,
        message_url=build_message_url(source, tg_message_id),
        views_count=get_optional_int(raw_message, "views"),
        replies_count=get_replies_count(raw_message),
        content_hash=hash_content(text),
        raw_payload=raw_payload,
    )


def get_message_text(raw_message: object) -> str | None:
    value = getattr(raw_message, "message", None) or getattr(raw_message, "text", None)
    return value if isinstance(value, str) and value else None


def get_forward_original_date(raw_message: object) -> datetime | None:
    forward = getattr(raw_message, "fwd_from", None)
    if forward is None:
        return None
    return ensure_optional_utc(getattr(forward, "date", None))


def get_replies_count(raw_message: object) -> int | None:
    replies = getattr(raw_message, "replies", None)
    value = getattr(replies, "replies", None) if replies is not None else None
    return value if isinstance(value, int) else None


def get_optional_int(raw_message: object, attr_name: str) -> int | None:
    value = getattr(raw_message, attr_name, None)
    return value if isinstance(value, int) else None


def build_message_url(source: TelegramSource, tg_message_id: int) -> str | None:
    username = source.normalized_username or source.username
    if not username:
        return None
    return f"https://t.me/{username}/{tg_message_id}"


def build_raw_payload(raw_message: object) -> dict[str, Any]:
    telegram_message = cast(Any, raw_message)
    return {
        "id": int(telegram_message.id),
        "date": ensure_utc(telegram_message.date).isoformat(),
        "edit_date": optional_datetime_iso(getattr(raw_message, "edit_date", None)),
        "views": get_optional_int(raw_message, "views"),
        "replies": get_replies_count(raw_message),
        "message": get_message_text(raw_message),
        "forward_original_date": optional_datetime_iso(get_forward_original_date(raw_message)),
    }


def hash_content(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def ensure_optional_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return ensure_utc(value)


def optional_datetime_iso(value: object) -> str | None:
    utc_value = ensure_optional_utc(value)
    return utc_value.isoformat() if utc_value is not None else None


def now_utc() -> datetime:
    return datetime.now(UTC)
