from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

from app.core.config import Settings, get_settings


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
        pytest.skip(f"PostgreSQL is not available for migration test: {exc}")

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


async def assert_schema_and_constraints(settings: Settings) -> None:
    connection = await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )
    try:
        table_names = await connection.fetch(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'public'
            """
        )
        assert {
            "users",
            "telegram_accounts",
            "telegram_sources",
            "messages",
            "keywords",
            "negative_keywords",
            "message_entities",
            "classifications",
            "orders",
            "duplicate_groups",
            "notification_deliveries",
            "favorites",
            "audit_logs",
            "failed_tasks",
        }.issubset({row["table_name"] for row in table_names})

        source_id = await connection.fetchval(
            "insert into telegram_sources (normalized_username) values ($1) returning id",
            "test_source",
        )
        await connection.execute(
            """
            insert into messages (source_id, tg_message_id, published_at, content_hash)
            values ($1, 42, now(), 'hash-a')
            """,
            source_id,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(
                """
                insert into messages (source_id, tg_message_id, published_at, content_hash)
                values ($1, 42, now(), 'hash-b')
                """,
                source_id,
            )
    finally:
        await connection.close()


def test_alembic_upgrade_head_on_clean_database(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    database_name = f"tg_order_radar_test_{uuid4().hex}"

    run(lambda: create_database(settings, database_name))
    monkeypatch.setenv("POSTGRES_DB", database_name)
    get_settings.cache_clear()

    try:
        command.upgrade(Config("alembic.ini"), "head")
        migrated_settings = get_settings()
        run(lambda: assert_schema_and_constraints(migrated_settings))
    finally:
        get_settings.cache_clear()
        run(lambda: drop_database(settings, database_name))
