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
from app.models import (
    Classification,
    DuplicateGroup,
    Keyword,
    Message,
    MessageEntity,
    NegativeKeyword,
    Order,
    TelegramSource,
)
from app.services.deduplication import detect_duplicates_in_session
from app.services.dictionaries import invalidate_dictionary_cache
from app.services.message_processing import process_message_in_session
from app.services.order_classification import classify_message_in_session


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


async def create_source(
    session: AsyncSession,
    *,
    tg_peer_id: int = -100999,
    username: str = "orders",
) -> TelegramSource:
    source = TelegramSource(
        tg_peer_id=tg_peer_id,
        username=username,
        normalized_username=username,
        type="channel",
        is_public=True,
        enabled=True,
        access_status="ok",
    )
    session.add(source)
    await session.flush()
    return source


async def create_message(
    session: AsyncSession,
    source: TelegramSource,
    text: str | None,
    *,
    published_at: datetime | None = None,
    content_hash: str | None = None,
) -> Message:
    message = Message(
        source_id=source.id,
        tg_message_id=uuid4().int % 1_000_000,
        published_at=published_at or datetime.now(UTC),
        text=text,
        content_hash=content_hash or uuid4().hex,
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


async def test_classify_message_creates_rules_classification_and_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_dictionaries(session)
        source = await create_source(session)
        message = await create_message(
            session,
            source,
            "Нужен лендинг. Бюджет 100к ₽, сделать за 5 дней, пишите @client",
        )
        await process_message_in_session(session, message.id)

        result = await classify_message_in_session(session, message.id)
        classification = await session.scalar(
            select(Classification).where(Classification.message_id == message.id)
        )
        order = await session.scalar(select(Order).where(Order.message_id == message.id))

        assert result.label == "order"
        assert result.order_id is not None
        assert classification is not None
        assert classification.method == "rules"
        assert classification.manual_review is False
        assert order is not None
        assert order.relevance_score >= 60
        assert order.project_type == "landing_page"
        assert order.contacts is not None


async def test_same_order_in_multiple_channels_has_single_canonical_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_dictionaries(session)
        first_source = await create_source(session, tg_peer_id=-100991, username="orders_one")
        second_source = await create_source(session, tg_peer_id=-100992, username="orders_two")
        text = "Нужен лендинг. Бюджет 100к ₽, сделать за 5 дней, пишите @client"
        first_message = await create_message(
            session,
            first_source,
            text,
            published_at=datetime(2026, 7, 15, 10, tzinfo=UTC),
            content_hash="same-normalized-content",
        )
        second_message = await create_message(
            session,
            second_source,
            text,
            published_at=datetime(2026, 7, 15, 11, tzinfo=UTC),
            content_hash="same-normalized-content",
        )
        for message in (first_message, second_message):
            await process_message_in_session(session, message.id)
            await classify_message_in_session(session, message.id)

        first_order = await session.scalar(
            select(Order).where(Order.message_id == first_message.id)
        )
        second_order = await session.scalar(
            select(Order).where(Order.message_id == second_message.id)
        )
        assert first_order is not None
        assert second_order is not None

        first_result = await detect_duplicates_in_session(session, first_order.id)
        second_result = await detect_duplicates_in_session(session, second_order.id)
        duplicate_group = await session.scalar(select(DuplicateGroup))

        assert first_result.is_canonical is True
        assert second_result.is_canonical is False
        assert second_result.canonical_order_id == first_order.id
        assert duplicate_group is not None
        assert duplicate_group.canonical_order_id == first_order.id
        assert duplicate_group.size == 2
        assert first_order.duplicate_group_id == duplicate_group.id
        assert second_order.duplicate_group_id == duplicate_group.id


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
