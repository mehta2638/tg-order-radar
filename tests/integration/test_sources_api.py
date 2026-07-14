from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.models import AuditLog, TelegramSource
from app.services.sources import get_source


@dataclass(frozen=True)
class ApiTestContext:
    app: FastAPI
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


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
        pytest.skip(f"PostgreSQL is not available for source API tests: {exc}")

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
def api_context(monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiTestContext]:
    settings = Settings()
    database_name = f"tg_order_radar_sources_test_{uuid4().hex}"

    run(lambda: create_database(settings, database_name))
    monkeypatch.setenv("POSTGRES_DB", database_name)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")

    migrated_settings = get_settings()
    engine = create_async_engine(migrated_settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    try:
        yield ApiTestContext(app=app, engine=engine, session_factory=session_factory)
    finally:
        app.dependency_overrides.clear()
        run(lambda: dispose_engine(engine))
        get_settings.cache_clear()
        run(lambda: drop_database(settings, database_name))


async def test_create_list_get_update_delete_source(api_context: ApiTestContext) -> None:
    transport = httpx.ASGITransport(app=api_context.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post(
            "/api/v1/sources",
            json={"link": "https://t.me/Freelance_Orders/123"},
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["normalized_username"] == "freelance_orders"
        assert created["access_status"] == "pending_validation"
        assert created["enabled"] is True
        assert created["tg_peer_id"] is None

        duplicate_response = await client.post(
            "/api/v1/sources",
            json={"link": "@freelance_orders"},
        )
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error"]["code"] == "SOURCE_EXISTS"

        list_response = await client.get("/api/v1/sources?page=1&size=10")
        assert list_response.status_code == 200
        assert list_response.headers["X-Total-Count"] == "1"
        assert list_response.json()["total"] == 1

        source_id = created["id"]
        get_response = await client.get(f"/api/v1/sources/{source_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == source_id

        patch_response = await client.patch(
            f"/api/v1/sources/{source_id}",
            json={"enabled": False},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["enabled"] is False

        delete_response = await client.delete(f"/api/v1/sources/{source_id}")
        assert delete_response.status_code == 204

    async with api_context.session_factory() as session:
        audit_actions = list(
            await session.scalars(select(AuditLog.action).order_by(AuditLog.action))
        )

    assert audit_actions == ["source.create", "source.update_enabled"]


async def test_private_and_invalid_source_links_return_unified_errors(
    api_context: ApiTestContext,
) -> None:
    transport = httpx.ASGITransport(app=api_context.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        private_response = await client.post(
            "/api/v1/sources",
            json={"link": "https://t.me/+private"},
        )
        assert private_response.status_code == 409
        assert private_response.json()["error"]["code"] == "SOURCE_NOT_PUBLIC"

        invalid_response = await client.post(
            "/api/v1/sources",
            json={"link": "bad-name"},
        )
        assert invalid_response.status_code == 422
        assert invalid_response.json()["error"]["code"] == "INVALID_SOURCE_USERNAME"


async def test_get_unknown_source_returns_not_found(api_context: ApiTestContext) -> None:
    transport = httpx.ASGITransport(app=api_context.app)
    unknown_id = uuid4()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/sources/{unknown_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SOURCE_NOT_FOUND"


async def test_validate_source_endpoint(
    api_context: ApiTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate_source(session: AsyncSession, source_id: UUID) -> TelegramSource:
        source = await get_source(session, source_id)
        source.access_status = "ok"
        source.is_public = True
        source.tg_peer_id = -100777
        await session.commit()
        await session.refresh(source)
        return source

    monkeypatch.setattr("app.api.sources.validate_source", fake_validate_source)

    transport = httpx.ASGITransport(app=api_context.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post(
            "/api/v1/sources",
            json={"link": "@validate_source"},
        )
        source_id = create_response.json()["id"]

        validate_response = await client.post(f"/api/v1/sources/{source_id}/validate")

    assert validate_response.status_code == 200
    assert validate_response.json()["access_status"] == "ok"
    assert validate_response.json()["tg_peer_id"] == -100777
