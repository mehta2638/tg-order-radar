from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
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
        pytest.skip(f"PostgreSQL is not available: {exc}")

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
) -> Iterator[tuple[object, async_sessionmaker[AsyncSession], Settings]]:
    settings = Settings()
    database_name = f"tg_order_radar_subs_api_test_{uuid4().hex}"

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
        yield app, session_factory, migrated_settings
    finally:
        app.dependency_overrides.clear()
        run(lambda: dispose_engine(engine))
        get_settings.cache_clear()
        run(lambda: drop_database(settings, database_name))


@pytest.mark.asyncio
async def test_subscription_crud_and_ownership(
    api_context: tuple[object, async_sessionmaker[AsyncSession], Settings],
) -> None:
    app, _session_factory, settings = api_context
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post(
            "/api/v1/subscriptions",
            headers={"X-API-Key": settings.api_key_operator},
            json={
                "name": "landing-alerts",
                "min_relevance_score": 70,
                "project_types": ["landing"],
                "budget_min": "50000",
                "budget_max": "200000",
                "currencies": ["rub"],
                "positive_keywords": ["лендинг"],
                "negative_keywords": ["казино"],
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
                "timezone": "Europe/Moscow",
                "freshness_days": 3,
                "max_notifications_per_period": 10,
                "rate_limit_period_minutes": 60,
                "tg_chat_id": 10001,
            },
        )
        assert create_response.status_code == 201, create_response.text
        created = create_response.json()
        subscription_id = created["id"]
        assert created["enabled"] is True
        assert created["currencies"] == ["RUB"]
        assert created["quiet_hours_start"] == "22:00"

        list_own = await client.get(
            "/api/v1/subscriptions",
            headers={"X-API-Key": settings.api_key_operator},
        )
        assert list_own.status_code == 200
        # Operator created subscription for bot user via tg_chat_id, not api-operator user.
        assert list_own.json()["total"] == 0

        get_forbidden = await client.get(
            f"/api/v1/subscriptions/{subscription_id}",
            headers={"X-API-Key": settings.api_key_operator},
        )
        assert get_forbidden.status_code == 403

        admin_get = await client.get(
            f"/api/v1/subscriptions/{subscription_id}",
            headers={"X-API-Key": settings.api_key_admin},
        )
        assert admin_get.status_code == 200

        patch = await client.patch(
            f"/api/v1/subscriptions/{subscription_id}",
            headers={"X-API-Key": settings.api_key_admin},
            json={"name": "landing-v2"},
        )
        assert patch.status_code == 200
        assert patch.json()["name"] == "landing-v2"

        disable = await client.post(
            f"/api/v1/subscriptions/{subscription_id}/disable",
            headers={"X-API-Key": settings.api_key_admin},
        )
        assert disable.status_code == 200
        assert disable.json()["enabled"] is False

        enable = await client.post(
            f"/api/v1/subscriptions/{subscription_id}/enable",
            headers={"X-API-Key": settings.api_key_admin},
        )
        assert enable.status_code == 200
        assert enable.json()["enabled"] is True

        viewer_create = await client.post(
            "/api/v1/subscriptions",
            headers={"X-API-Key": settings.api_key_viewer},
            json={"name": "viewer-sub"},
        )
        assert viewer_create.status_code == 403


@pytest.mark.asyncio
async def test_subscription_validation_errors(
    api_context: tuple[object, async_sessionmaker[AsyncSession], Settings],
) -> None:
    app, _session_factory, settings = api_context
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        bad_budget = await client.post(
            "/api/v1/subscriptions",
            headers={"X-API-Key": settings.api_key_operator},
            json={"name": "bad", "budget_min": "200", "budget_max": "100"},
        )
        assert bad_budget.status_code == 422

        bad_tz = await client.post(
            "/api/v1/subscriptions",
            headers={"X-API-Key": settings.api_key_operator},
            json={"name": "bad-tz", "timezone": "Mars/Phobos"},
        )
        assert bad_tz.status_code == 422

        bad_quiet = await client.post(
            "/api/v1/subscriptions",
            headers={"X-API-Key": settings.api_key_operator},
            json={"name": "bad-quiet", "quiet_hours_start": "22:00"},
        )
        assert bad_quiet.status_code == 422

        bad_relevance = await client.post(
            "/api/v1/subscriptions",
            headers={"X-API-Key": settings.api_key_operator},
            json={"name": "bad-rel", "min_relevance_score": 150},
        )
        assert bad_relevance.status_code == 422


@pytest.mark.asyncio
async def test_user_cannot_modify_foreign_subscription(
    api_context: tuple[object, async_sessionmaker[AsyncSession], Settings],
) -> None:
    app, _session_factory, settings = api_context
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/subscriptions",
            headers={"X-API-Key": settings.api_key_admin},
            json={"name": "admin-sub"},
        )
        assert created.status_code == 201
        subscription_id = created.json()["id"]

        forbidden = await client.patch(
            f"/api/v1/subscriptions/{subscription_id}",
            headers={"X-API-Key": settings.api_key_operator},
            json={"name": "hacked"},
        )
        assert forbidden.status_code == 403
