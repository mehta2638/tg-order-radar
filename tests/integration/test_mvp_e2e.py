from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.bot.services import (
    add_order_to_favorites_from_bot,
    change_order_status_from_bot,
    send_order_notification,
)
from app.collector.messages import collect_with_client
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.models import Favorite, Keyword, Message, NegativeKeyword, NotificationDelivery, Order
from app.services.deduplication import detect_duplicates_in_session
from app.services.dictionaries import invalidate_dictionary_cache
from app.services.message_processing import process_message_in_session
from app.services.order_classification import classify_message_in_session
from app.services.source_validation import validate_source
from app.services.sources import create_source

BOT_USER_ID = 42_424_242


@dataclass(frozen=True)
class FakeEntity:
    peer_id: int = -100777
    username: str = "Public_MVP"
    title: str = "Public MVP"
    participants_count: int = 100
    broadcast: bool = True
    megagroup: bool = False


@dataclass(frozen=True)
class FakeTelegramMessage:
    id: int
    date: datetime
    message: str
    edit_date: datetime | None = None
    views: int | None = None
    replies: object | None = None
    fwd_from: object | None = None


class FakeValidationClient:
    def __init__(self) -> None:
        self.disconnected = False

    async def get_entity(self, username: str) -> FakeEntity:
        return FakeEntity(username=username)

    async def get_messages(self, entity: object, limit: int) -> list[object]:
        return [object()]

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeCollectorClient:
    def __init__(self, messages: list[FakeTelegramMessage]) -> None:
        self.messages = messages

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
        for message in sorted(self.messages, key=lambda item: item.id, reverse=True):
            if message.id <= min_id:
                continue
            if limit is not None and yielded >= limit:
                break
            yielded += 1
            yield message

    async def get_messages(self, entity: object, ids: list[int]) -> list[object | None]:
        return [
            next((message for message in self.messages if message.id == item), None) for item in ids
        ]


class FakeBotSender:
    def __init__(self) -> None:
        self.chat_ids: list[int] = []
        self.texts: list[str] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> object:
        self.chat_ids.append(chat_id)
        self.texts.append(text)
        return object()


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
        pytest.skip(f"PostgreSQL is not available for MVP e2e test: {exc}")

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
def e2e_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[FastAPI, async_sessionmaker[AsyncSession]]]:
    settings = Settings()
    database_name = f"tg_order_radar_mvp_e2e_test_{uuid4().hex}"

    run(lambda: create_database(settings, database_name))
    monkeypatch.setenv("POSTGRES_DB", database_name)
    monkeypatch.setenv("BOT_ALLOWED_USER_IDS", str(BOT_USER_ID))
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    run(lambda: invalidate_dictionary_cache())

    migrated_settings = get_settings()
    engine = create_async_engine(migrated_settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield app, session_factory
    finally:
        app.dependency_overrides.clear()
        run(lambda: dispose_engine(engine))
        get_settings.cache_clear()
        run(lambda: drop_database(settings, database_name))


async def seed_mvp_dictionaries(session: AsyncSession) -> None:
    session.add_all(
        [
            Keyword(
                phrase="нужен сайт",
                lang="ru",
                weight=5,
                category="explicit_need",
                enabled=True,
            ),
            Keyword(
                phrase="лендинг",
                lang="ru",
                weight=4,
                category="project_type",
                enabled=True,
            ),
            NegativeKeyword(
                phrase="делаю сайты",
                lang="ru",
                weight=5,
                enabled=True,
            ),
        ]
    )
    await session.commit()


async def test_mvp_flow_from_source_to_bot_and_api(
    e2e_context: tuple[FastAPI, async_sessionmaker[AsyncSession]],
) -> None:
    app, session_factory = e2e_context
    fake_validation_client = FakeValidationClient()
    sent_message_ids: list[UUID] = []
    fake_bot = FakeBotSender()

    async with session_factory() as session:
        await seed_mvp_dictionaries(session)
        source = await create_source(session, "https://t.me/Public_MVP")

        validated_source = await validate_source(
            session,
            source.id,
            client_factory=lambda: asyncio.sleep(0, result=fake_validation_client),
        )
        assert validated_source.access_status == "ok"
        assert fake_validation_client.disconnected is True

        collector_result = await collect_with_client(
            session,
            FakeCollectorClient(
                [
                    FakeTelegramMessage(
                        id=101,
                        date=datetime.now(UTC),
                        message="Нужен сайт лендинг. Бюджет 120к ₽, срок 7 дней, контакт @client",
                    )
                ]
            ),
            validated_source,
            enqueue_message_processing=lambda message_id, correlation_id=None: (
                sent_message_ids.append(message_id)
            ),
            correlation_id="mvp-e2e",
        )
        assert collector_result.saved == 1
        assert collector_result.enqueued == 1
        assert len(sent_message_ids) == 1

        await process_message_in_session(session, sent_message_ids[0])
        classification = await classify_message_in_session(session, sent_message_ids[0])
        assert classification.order_id is not None
        deduplication = await detect_duplicates_in_session(session, classification.order_id)
        assert deduplication.is_canonical is True

        delivery = await send_order_notification(
            session,
            classification.order_id,
            fake_bot,
            Settings(bot_allowed_user_ids=str(BOT_USER_ID), bot_rate_limit_seconds=0),
        )
        assert delivery.sent == 1
        repeated_delivery = await send_order_notification(
            session,
            classification.order_id,
            fake_bot,
            Settings(bot_allowed_user_ids=str(BOT_USER_ID), bot_rate_limit_seconds=0),
        )
        assert repeated_delivery.sent == 0
        assert repeated_delivery.skipped == 1
        assert fake_bot.chat_ids == [BOT_USER_ID]

        favorite_message = await add_order_to_favorites_from_bot(
            session,
            classification.order_id,
            BOT_USER_ID,
        )
        assert favorite_message == "Добавлено в избранное."
        assert (
            await change_order_status_from_bot(
                session,
                classification.order_id,
                BOT_USER_ID,
                "contacted",
            )
            == "Статус обновлен."
        )

        assert int(await session.scalar(select(func.count()).select_from(Message)) or 0) == 1
        assert int(await session.scalar(select(func.count()).select_from(Order)) or 0) == 1
        deliveries_count = int(
            await session.scalar(select(func.count()).select_from(NotificationDelivery)) or 0
        )
        assert deliveries_count == 1
        assert int(await session.scalar(select(func.count()).select_from(Favorite)) or 0) == 1

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/orders?status=contacted&q=лендинг&relevance_min=60",
            headers={"X-API-Key": "dev-admin-key"},
        )

    assert response.status_code == 200
    assert response.json()["total"] == 1
