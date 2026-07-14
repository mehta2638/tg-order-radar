from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.models import TelegramSource
from app.services import source_validation


@dataclass
class FakeEntity:
    peer_id: int
    username: str
    title: str
    participants_count: int | None = None
    broadcast: bool = True
    megagroup: bool = False


class FakeClient:
    def __init__(self, result: object | Exception) -> None:
        self.result = result
        self.disconnected = False

    async def get_entity(self, username: str) -> object:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def get_messages(self, entity: object, limit: int) -> object:
        return []

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeFloodWaitError(Exception):
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds


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
        pytest.skip(f"PostgreSQL is not available for source validation tests: {exc}")

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
    database_name = f"tg_order_radar_validation_test_{uuid4().hex}"

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


async def create_pending_source(session: AsyncSession) -> TelegramSource:
    source = TelegramSource(
        username="public_source",
        normalized_username="public_source",
        access_status="pending_validation",
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def test_validate_source_success(session_factory: async_sessionmaker[AsyncSession]) -> None:
    fake_client = FakeClient(
        FakeEntity(
            peer_id=-100123,
            username="Public_Source",
            title="Public Source",
            participants_count=42,
            megagroup=True,
            broadcast=False,
        )
    )

    async with session_factory() as session:
        source = await create_pending_source(session)
        result = await source_validation.validate_source(
            session,
            source.id,
            client_factory=lambda: asyncio.sleep(0, result=fake_client),
        )

    assert result.tg_peer_id == -100123
    assert result.username == "Public_Source"
    assert result.normalized_username == "public_source"
    assert result.type == "megagroup"
    assert result.participants_count == 42
    assert result.is_public is True
    assert result.access_status == "ok"
    assert fake_client.disconnected is True


async def test_validate_source_not_found(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNotFoundError(Exception):
        pass

    monkeypatch.setattr(source_validation, "UsernameNotOccupiedError", FakeNotFoundError)
    fake_client = FakeClient(FakeNotFoundError())

    async with session_factory() as session:
        source = await create_pending_source(session)
        result = await source_validation.validate_source(
            session,
            source.id,
            client_factory=lambda: asyncio.sleep(0, result=fake_client),
        )

    assert result.access_status == "not_found"
    assert result.is_public is False


async def test_validate_source_floodwait_records_pause_until(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_validation, "FloodWaitError", FakeFloodWaitError)
    fake_client = FakeClient(FakeFloodWaitError(seconds=30))

    async with session_factory() as session:
        source = await create_pending_source(session)
        result = await source_validation.validate_source(
            session,
            source.id,
            client_factory=lambda: asyncio.sleep(0, result=fake_client),
        )

    assert result.access_status == "floodwait"
    assert result.pause_until is not None
    assert result.is_public is False


async def test_validate_source_network_error_sets_error_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fake_client = FakeClient(ConnectionError("network down"))

    async with session_factory() as session:
        source = await create_pending_source(session)
        result = await source_validation.validate_source(
            session,
            source.id,
            client_factory=lambda: asyncio.sleep(0, result=fake_client),
        )

    assert result.access_status == "error"
    assert result.is_public is False
