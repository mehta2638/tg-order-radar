from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app
from app.monitoring import metrics as metrics_module
from app.monitoring.metrics import (
    CLASSIFICATION_LATENCY_SECONDS,
    QUEUE_SIZE,
    observe_duration,
    record_notification,
    refresh_runtime_gauges,
    render_metrics,
    update_queue_sizes,
)
from app.monitoring.sentry import init_sentry


async def test_metrics_endpoint_returns_prometheus_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        async def scalar(self, *args: object, **kwargs: object) -> int:
            return 0

        async def execute(self, *args: object, **kwargs: object) -> object:
            class Result:
                def scalar_one_or_none(self_inner: object) -> float:
                    return 12.5

                def all(self_inner: object) -> list[tuple[str, int]]:
                    return [("ok", 2)]

            return Result()

    async def fake_render(session: object, settings: Settings | None = None) -> tuple[bytes, str]:
        return await render_metrics(FakeSession(), Settings(prometheus_enabled=True))  # type: ignore[arg-type]

    monkeypatch.setattr("app.api.metrics.render_metrics", fake_render)
    monkeypatch.setattr(
        "app.monitoring.metrics.update_queue_sizes",
        lambda settings=None: QUEUE_SIZE.labels(queue="message_processing").set(3),
    )

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert (
        "queue_size" in response.text
        or "collector_lag_seconds" in response.text
        or "failed_tasks" in response.text
    )


def test_observe_classification_latency_records_histogram() -> None:
    with observe_duration(CLASSIFICATION_LATENCY_SECONDS):
        pass


def test_record_notification_increments_counter() -> None:
    record_notification("sent", 2)
    record_notification("failed", 1)


def test_sentry_disabled_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.monitoring.sentry._INITIALIZED", False)
    assert init_sentry(Settings(sentry_dsn=None), service_name="api") is False


async def test_refresh_runtime_gauges_reads_failed_tasks_and_lag() -> None:
    class FakeSession:
        async def scalar(self, statement: object) -> int:
            return 4

        async def execute(self, statement: object) -> object:
            class Result:
                def scalar_one_or_none(self_inner: object) -> float:
                    return 42.0

                def all(self_inner: object) -> list[tuple[str, int]]:
                    return [("ok", 1), ("floodwait", 1)]

            return Result()

    await refresh_runtime_gauges(FakeSession())  # type: ignore[arg-type]


def test_update_queue_sizes_sets_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRedis:
        def llen(self, name: str) -> int:
            return 7 if name == "classification" else 0

        def close(self) -> None:
            return None

    class FakeFactory:
        @staticmethod
        def from_url(url: str, decode_responses: bool = False) -> FakeRedis:
            return FakeRedis()

    monkeypatch.setattr(metrics_module.redis, "Redis", FakeFactory)
    update_queue_sizes(Settings(celery_broker_url="redis://localhost:6379/1"))
