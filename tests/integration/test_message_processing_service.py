from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
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
from app.models import Keyword, Message, MessageEntity, NegativeKeyword, TelegramSource
from app.services.dictionaries import invalidate_dictionary_cache
from app.services.message_processing import process_message_in_session


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
        pytest.skip(f"PostgreSQL is not available for message processing tests: {exc}")

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
    database_name = f"tg_order_radar_processing_test_{uuid4().hex}"

    run(lambda: create_database(settings, database_name))
    monkeypatch.setenv("POSTGRES_DB", database_name)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    run(lambda: invalidate_dictionary_cache())

    migrated_settings = get_settings()
    engine = create_async_engine(migrated_settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        yield factory
    finally:
        run(lambda: dispose_engine(engine))
        get_settings.cache_clear()
        run(lambda: drop_database(settings, database_name))


async def seed_dictionaries(session: AsyncSession) -> None:
    session.add_all(
        [
            Keyword(
                phrase="нужен сайт",
                lang="ru",
                weight=5,
                category="explicit_need",
                is_regex=False,
                enabled=True,
            ),
            Keyword(
                phrase="доработать",
                lang="ru",
                weight=4,
                category="revision",
                is_regex=False,
                enabled=True,
            ),
            Keyword(
                phrase=r"ищу\s+разработчик\w*",
                lang="ru",
                weight=4,
                category="explicit_need",
                is_regex=True,
                enabled=True,
            ),
            NegativeKeyword(
                phrase="делаю сайты",
                lang="ru",
                weight=5,
                is_regex=False,
                enabled=True,
            ),
        ]
    )
    await session.flush()


async def create_source(session: AsyncSession) -> TelegramSource:
    source = TelegramSource(
        tg_peer_id=-100999,
        username="orders",
        normalized_username="orders",
        type="channel",
        is_public=True,
        enabled=True,
        access_status="ok",
    )
    session.add(source)
    await session.flush()
    return source


async def create_message(
    session: AsyncSession, source: TelegramSource, text: str | None
) -> Message:
    message = Message(
        source_id=source.id,
        tg_message_id=uuid4().int % 1_000_000,
        published_at=datetime.now(UTC),
        text=text,
        content_hash=uuid4().hex,
    )
    session.add(message)
    await session.flush()
    return message


async def entity_count(session: AsyncSession, message: Message) -> int:
    result = await session.scalars(
        select(MessageEntity).where(MessageEntity.message_id == message.id)
    )
    return len(list(result))


async def test_process_message_saves_prefilter_and_entities_idempotently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_dictionaries(session)
        source = await create_source(session)
        message = await create_message(
            session,
            source,
            "Нужен сайт-визитка. Бюджет от 50к до 80к ₽, срочно, пишите @client",
        )

        result = await process_message_in_session(session, message.id)
        first_entity_count = await entity_count(session, message)
        await process_message_in_session(session, message.id)
        entities = list(
            await session.scalars(
                select(MessageEntity).where(MessageEntity.message_id == message.id)
            )
        )

        assert result.status == "processed"
        assert result.passed_prefilter is True
        assert message.detected_language == "ru"
        assert message.passed_prefilter is True
        assert message.normalized_text is not None
        assert {entity.type for entity in entities}.issuperset(
            {"keyword_hit", "budget", "deadline", "contact", "project_type"}
        )
        assert len(entities) == first_entity_count


@pytest.mark.parametrize(
    ("text", "expected_negative_hits"),
    [
        (None, 0),
        ("Делаю сайты недорого, моё портфолио в профиле", 1),
    ],
)
async def test_process_message_rejects_empty_or_negative_text(
    session_factory: async_sessionmaker[AsyncSession],
    text: str | None,
    expected_negative_hits: int,
) -> None:
    async with session_factory() as session:
        await seed_dictionaries(session)
        source = await create_source(session)
        message = await create_message(session, source, text)

        result = await process_message_in_session(session, message.id)

        assert result.passed_prefilter is False
        assert result.negative_hits == expected_negative_hits
        assert message.passed_prefilter is False
