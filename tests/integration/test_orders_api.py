from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import asyncpg
import httpx
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
from app.db.session import get_session
from app.main import create_app
from app.models import Message, Order, TelegramSource


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
        pytest.skip(f"PostgreSQL is not available for orders API tests: {exc}")

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
def api_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[object, async_sessionmaker[AsyncSession]]]:
    settings = Settings()
    database_name = f"tg_order_radar_orders_api_test_{uuid4().hex}"

    run(lambda: create_database(settings, database_name))
    monkeypatch.setenv("POSTGRES_DB", database_name)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")

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


async def seed_order(session_factory: async_sessionmaker[AsyncSession]) -> Order:
    async with session_factory() as session:
        source = TelegramSource(
            tg_peer_id=-1001,
            username="orders",
            normalized_username="orders",
            type="channel",
            is_public=True,
            access_status="ok",
        )
        session.add(source)
        await session.flush()
        message = Message(
            source_id=source.id,
            tg_message_id=1,
            published_at=datetime.now(UTC),
            text="Нужен лендинг",
            normalized_text="нужен лендинг",
            message_url="https://t.me/orders/1",
            content_hash="hash",
        )
        session.add(message)
        await session.flush()
        order = Order(
            message_id=message.id,
            source_id=source.id,
            project_type="landing_page",
            title="Нужен лендинг",
            summary="Нужен лендинг, бюджет 100к",
            budget_from=Decimal("100000"),
            budget_to=Decimal("100000"),
            budget_currency="RUB",
            contacts={"telegram_username": ["@client"]},
            published_at=message.published_at,
            relevance_score=90,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order


async def test_orders_api_auth_filters_status_favorites_keywords_stats_export(
    api_context: tuple[object, async_sessionmaker[AsyncSession]],
) -> None:
    app, session_factory = api_context
    order = await seed_order(session_factory)
    headers = {"X-API-Key": "dev-admin-key"}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/orders")).status_code == 401

        list_response = await client.get(
            "/api/v1/orders?project_type=landing_page&relevance_min=80&q=лендинг",
            headers=headers,
        )
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1

        detail_response = await client.get(f"/api/v1/orders/{order.id}", headers=headers)
        assert detail_response.status_code == 200
        assert detail_response.json()["message_url"] == "https://t.me/orders/1"

        status_response = await client.patch(
            f"/api/v1/orders/{order.id}/status",
            json={"status": "viewed", "version": 1},
            headers=headers,
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "viewed"

        favorite_response = await client.post(f"/api/v1/favorites/{order.id}", headers=headers)
        assert favorite_response.status_code == 201
        assert (await client.get("/api/v1/favorites", headers=headers)).json()["total"] == 1
        assert (
            await client.delete(f"/api/v1/favorites/{order.id}", headers=headers)
        ).status_code == 204

        keyword_response = await client.post(
            "/api/v1/keywords",
            json={"phrase": "нужен сайт", "category": "explicit_need"},
            headers=headers,
        )
        assert keyword_response.status_code == 201
        assert (await client.get("/api/v1/keywords", headers=headers)).json()["total"] == 1

        stats_response = await client.get("/api/v1/stats/summary", headers=headers)
        assert stats_response.status_code == 200
        assert stats_response.json()["orders_total"] == 1

        csv_response = await client.get("/api/v1/orders/export?format=csv", headers=headers)
        assert csv_response.status_code == 200
        assert "Нужен лендинг" in csv_response.text
