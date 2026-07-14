from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.collector import messages as collector_messages
from app.collector.messages import collect_source_messages, collect_with_client
from app.core.config import Settings, get_settings
from app.models import Message, TelegramSource


@dataclass
class FakeReplies:
    replies: int


@dataclass
class FakeForward:
    date: datetime


@dataclass
class FakeTelegramMessage:
    id: int
    date: datetime
    message: str
    edit_date: datetime | None = None
    views: int | None = None
    replies: FakeReplies | None = None
    fwd_from: FakeForward | None = None


class FakeCollectorClient:
    def __init__(
        self,
        messages: list[FakeTelegramMessage],
        deleted_ids: set[int] | None = None,
    ) -> None:
        self.messages = {message.id: message for message in messages}
        self.deleted_ids = deleted_ids or set()

    async def get_entity(self, username: str) -> object:
        return {"username": username}

    async def iter_messages(
        self,
        entity: object,
        *,
        min_id: int = 0,
        limit: int | None = None,
    ) -> AsyncIterator[object]:
        yielded = 0
        for message in sorted(self.messages.values(), key=lambda item: item.id, reverse=True):
            if message.id <= min_id:
                continue
            if limit is not None and yielded >= limit:
                break
            yielded += 1
            yield message

    async def get_messages(self, entity: object, ids: list[int]) -> list[object | None]:
        return [
            None if message_id in self.deleted_ids else self.messages.get(message_id)
            for message_id in ids
        ]


class FakeFloodWaitError(Exception):
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds


class LockedLease:
    async def __aenter__(self) -> bool:
        return False

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        return None


def run(coro_factory: Callable[[], Awaitable[None]]) -> None:
    asyncio.run(coro_factory())


async def create_database(settings: Settings, database_name: str) -> None:
    try:
        connection = await asyncpg.connect(
            user=settings.postgres_user,
            password=settings.postgres_password,
            host=settings.postgres_host,
            port=settings.postgres_port,
            database="postgres",
        )
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for collector tests: {exc}")

    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def drop_database(settings: Settings, database_name: str) -> None:
    connection = await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database="postgres",
    )
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
    finally:
        await connection.close()


async def dispose_engine(engine: AsyncEngine) -> None:
    await engine.dispose()


@pytest.fixture
def session_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[async_sessionmaker[AsyncSession]]:
    settings = Settings()
    database_name = f"tg_order_radar_collector_test_{uuid4().hex}"

    run(lambda: create_database(settings, database_name))
    monkeypatch.setenv("POSTGRES_DB", database_name)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")

    migrated_settings = get_settings()
    engine = create_async_engine(migrated_settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        yield factory
    finally:
        run(lambda: dispose_engine(engine))
        get_settings.cache_clear()
        run(lambda: drop_database(settings, database_name))


async def create_source(
    session: AsyncSession,
    *,
    last_seen_message_id: int = 0,
    pause_until: datetime | None = None,
) -> TelegramSource:
    source = TelegramSource(
        tg_peer_id=-100123,
        username="Public_Source",
        normalized_username="public_source",
        title="Public Source",
        type="channel",
        is_public=True,
        enabled=True,
        access_status="ok",
        last_seen_message_id=last_seen_message_id,
        pause_until=pause_until,
    )
    session.add(source)
    await session.flush()
    return source


async def collect(
    session: AsyncSession,
    source: TelegramSource,
    client: FakeCollectorClient,
) -> tuple[dict[str, int], collector_messages.CollectionResult]:
    enqueued: dict[str, int] = {}

    def enqueue(message_id: UUID, correlation_id: str | None = None) -> None:
        enqueued[str(message_id)] = enqueued.get(str(message_id), 0) + 1

    result = await collect_with_client(
        session,
        client,
        source,
        enqueue_message_processing=enqueue,
        correlation_id="test-correlation",
    )
    return enqueued, result


async def count_messages(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Message)) or 0)


def message(
    message_id: int,
    *,
    days_ago: int = 0,
    text: str | None = None,
    edited: bool = False,
) -> FakeTelegramMessage:
    published_at = datetime.now(UTC) - timedelta(days=days_ago)
    return FakeTelegramMessage(
        id=message_id,
        date=published_at,
        message=text or f"message {message_id}",
        edit_date=published_at + timedelta(minutes=5) if edited else None,
        views=message_id * 10,
        replies=FakeReplies(replies=message_id),
        fwd_from=FakeForward(date=published_at - timedelta(days=1)),
    )


async def test_initial_backfill_is_limited_and_repeat_collection_has_no_duplicates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = await create_source(session)
        source_messages = [message(1, days_ago=9), message(2), message(3)]
        first_client = FakeCollectorClient(source_messages)
        enqueued, result = await collect(session, source, first_client)

        assert result.saved == 2
        assert result.last_seen_message_id == 3
        assert len(enqueued) == 2
        assert await count_messages(session) == 2

        second_client = FakeCollectorClient(source_messages)
        enqueued_again, second_result = await collect(session, source, second_client)

        assert second_result.saved == 0
        assert second_result.updated == 0
        assert len(enqueued_again) == 0
        assert await count_messages(session) == 2


async def test_collection_uses_last_seen_message_id_for_gaps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = await create_source(session, last_seen_message_id=5)
        client = FakeCollectorClient([message(4), message(5), message(6), message(8)])

        enqueued, result = await collect(session, source, client)

        assert result.saved == 2
        assert result.last_seen_message_id == 8
        assert len(enqueued) == 2
        assert [
            item.tg_message_id
            for item in await session.scalars(select(Message).order_by(Message.tg_message_id))
        ] == [6, 8]


async def test_existing_edited_message_is_updated_and_reenqueued(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = await create_source(session)
        await collect(session, source, FakeCollectorClient([message(10, text="before")]))

        edited_client = FakeCollectorClient([message(10, text="after", edited=True)])
        enqueued, result = await collect(session, source, edited_client)
        stored_message = await session.scalar(select(Message).where(Message.tg_message_id == 10))

        assert result.saved == 0
        assert result.updated == 1
        assert len(enqueued) == 1
        assert stored_message is not None
        assert stored_message.text == "after"
        assert stored_message.edited_at is not None


async def test_deleted_message_is_soft_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = await create_source(session)
        await collect(session, source, FakeCollectorClient([message(20)]))

        deleted_client = FakeCollectorClient([], deleted_ids={20})
        enqueued, result = await collect(session, source, deleted_client)
        stored_message = await session.scalar(select(Message).where(Message.tg_message_id == 20))

        assert result.deleted == 1
        assert len(enqueued) == 1
        assert stored_message is not None
        assert stored_message.deleted_at is not None


async def test_floodwait_sets_source_pause_until(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collector_messages, "FloodWaitError", FakeFloodWaitError)

    class FloodWaitClient(FakeCollectorClient):
        async def get_entity(self, username: str) -> object:
            raise FakeFloodWaitError(seconds=60)

    async with session_factory() as session:
        source = await create_source(session)
        result = await collect_with_client(
            session,
            FloodWaitClient([]),
            source,
            enqueue_message_processing=None,
            correlation_id=None,
        )

        assert result.status == "floodwait"
        assert source.access_status == "floodwait"
        assert source.pause_until is not None


async def test_collection_skips_when_source_lease_is_locked() -> None:
    async def fail_client_factory() -> FakeCollectorClient:
        raise AssertionError("client must not be created when lock is not acquired")

    result = await collect_source_messages(
        uuid4(),
        client_factory=fail_client_factory,
        lease_factory=lambda source_id, ttl_seconds: LockedLease(),
    )

    assert result.status == "locked"
