from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterator
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

from app.collector.messages import collect_with_client
from app.collector.telethon_client import (
    TelegramAccountNotAuthorizedError,
    get_authorized_client,
)
from app.core.config import Settings, get_settings
from app.services.source_validation import validate_source
from app.services.sources import create_source


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
        pytest.skip(f"PostgreSQL is not available for MVP real smoke test: {exc}")

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
    database_name = f"tg_order_radar_real_smoke_test_{uuid4().hex}"

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


@pytest.mark.skipif(
    os.getenv("RUN_MVP_REAL_SMOKE") != "1" or not os.getenv("TG_PUBLIC_TEST_SOURCE"),
    reason="Set RUN_MVP_REAL_SMOKE=1 and TG_PUBLIC_TEST_SOURCE to run real smoke test.",
)
async def test_real_public_source_validates_and_collects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = get_settings()
    if settings.tg_api_id is None or not settings.tg_api_hash:
        pytest.skip("TG_API_ID and TG_API_HASH are required for real smoke test.")

    async with session_factory() as session:
        source = await create_source(session, os.environ["TG_PUBLIC_TEST_SOURCE"])
        try:
            validation_client = await get_authorized_client(settings)
        except TelegramAccountNotAuthorizedError as exc:
            pytest.skip(str(exc))

        validated = await validate_source(
            session,
            source.id,
            client_factory=lambda: asyncio.sleep(0, result=validation_client),
        )
        assert validated.access_status == "ok"

        try:
            collector_client = await get_authorized_client(settings)
        except TelegramAccountNotAuthorizedError as exc:
            pytest.skip(str(exc))
        try:
            result = await collect_with_client(
                session,
                collector_client,
                validated,
                enqueue_message_processing=None,
                correlation_id="real-smoke",
            )
            assert result.status == "ok"
        finally:
            await collector_client.disconnect()
