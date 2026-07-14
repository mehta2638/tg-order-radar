from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.models import FailedTask
from app.workers.dead_letter import record_failed_task


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
        pytest.skip(f"PostgreSQL is not available for dead-letter tests: {exc}")

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
    database_name = f"tg_order_radar_dlq_test_{uuid4().hex}"

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


async def test_record_failed_task_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_inserted = await record_failed_task(
        task_name="app.workers.tasks.process_message_task",
        task_id="task-1",
        queue="message_processing",
        args=("message-1",),
        kwargs={"correlation_id": "corr-1"},
        reason="RuntimeError: boom",
        retries=3,
        correlation_id="corr-1",
        session_factory=session_factory,
    )
    second_inserted = await record_failed_task(
        task_name="app.workers.tasks.process_message_task",
        task_id="task-1",
        queue="message_processing",
        args=("message-1",),
        kwargs={"correlation_id": "corr-1"},
        reason="RuntimeError: boom",
        retries=3,
        correlation_id="corr-1",
        session_factory=session_factory,
    )

    async with session_factory() as session:
        failed_tasks = list(await session.scalars(select(FailedTask)))

    assert first_inserted is True
    assert second_inserted is False
    assert len(failed_tasks) == 1
    assert failed_tasks[0].correlation_id == "corr-1"
    assert failed_tasks[0].queue == "message_processing"
