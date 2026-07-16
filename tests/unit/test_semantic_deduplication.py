from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings, get_settings
from app.models import Order
from app.services import semantic_deduplication
from app.services.semantic_deduplication import (
    backfill_order_embeddings,
    clear_embedding_model_cache,
    cosine_similarity,
    embed_text,
    find_semantic_duplicate,
    get_embedding_model,
    has_strong_contradictions,
    normalize_embedding_text,
    reset_semantic_metrics,
)


def test_embedding_model_is_cached() -> None:
    clear_embedding_model_cache()

    first = get_embedding_model("test://hash-embedding", None, 16)
    second = get_embedding_model("test://hash-embedding", None, 16)

    assert first is second
    assert get_embedding_model.cache_info().misses == 1
    assert get_embedding_model.cache_info().hits == 1


def test_embedding_text_normalization_masks_contacts() -> None:
    normalized = normalize_embedding_text("Нужен сайт, пишите @client или test@example.com")

    assert "@client" not in normalized
    assert "test@example.com" not in normalized
    assert "username" in normalized
    assert "email" in normalized


def test_paraphrased_russian_orders_are_similar_with_hash_model() -> None:
    clear_embedding_model_cache()
    settings = Settings(
        semantic_model_name="test://hash-embedding",
        semantic_embedding_dimension=64,
    )
    left = embed_text(
        normalize_embedding_text("Нужен лендинг для курса, бюджет 80к"),
        settings,
    )
    right = embed_text(
        normalize_embedding_text("Ищу посадочную страницу для онлайн-курса, бюджет 80000"),
        settings,
    )

    assert cosine_similarity(left, right) >= 0.45


def test_similar_words_but_different_orders_are_not_merged_by_contradictions() -> None:
    assert has_strong_contradictions(
        make_order(
            project_type="landing_page",
            summary="Нужен лендинг для курса",
            budget_from=Decimal("80000"),
            budget_to=Decimal("80000"),
        ),
        make_order(
            project_type="ecommerce",
            summary="Нужен интернет-магазин для курса",
            budget_from=Decimal("80000"),
            budget_to=Decimal("80000"),
        ),
    )


def test_different_project_type_blocks_semantic_merge() -> None:
    assert has_strong_contradictions(
        make_order(project_type="landing_page"),
        make_order(project_type="ecommerce"),
    )


def test_large_budget_difference_blocks_auto_merge() -> None:
    assert has_strong_contradictions(
        make_order(budget_from=Decimal("50000"), budget_to=Decimal("70000")),
        make_order(budget_from=Decimal("500000"), budget_to=Decimal("700000")),
    )


def test_different_explicit_contacts_block_auto_merge() -> None:
    assert has_strong_contradictions(
        make_order(contacts={"telegram_username": ["@first_client"]}),
        make_order(contacts={"telegram_username": ["@second_client"]}),
    )


def test_large_deadline_difference_blocks_auto_merge() -> None:
    assert has_strong_contradictions(
        make_order(deadline=date(2026, 7, 20)),
        make_order(deadline=date(2026, 10, 20)),
    )


async def test_disabled_semantic_dedup_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_DEDUP_ENABLED", "false")
    get_settings.cache_clear()
    reset_semantic_metrics()
    try:
        result = await find_semantic_duplicate(FakeBackfillSession([]), make_order())
    finally:
        get_settings.cache_clear()

    assert result.status == "fallback"
    assert result.fallback_reason == "disabled"


async def test_missing_pgvector_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMANTIC_DEDUP_ENABLED", "true")
    get_settings.cache_clear()
    reset_semantic_metrics()

    async def fake_storage_available(session: object) -> bool:
        return False

    monkeypatch.setattr(
        semantic_deduplication,
        "semantic_storage_available",
        fake_storage_available,
    )
    try:
        result = await find_semantic_duplicate(FakeBackfillSession([]), make_order())
    finally:
        get_settings.cache_clear()

    assert result.status == "fallback"
    assert result.fallback_reason == "pgvector_unavailable"


async def test_unavailable_model_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMANTIC_DEDUP_ENABLED", "true")
    get_settings.cache_clear()
    reset_semantic_metrics()

    async def fake_storage_available(session: object) -> bool:
        return True

    async def fake_ensure(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        semantic_deduplication,
        "semantic_storage_available",
        fake_storage_available,
    )
    monkeypatch.setattr(semantic_deduplication, "ensure_order_embedding", fake_ensure)
    try:
        result = await find_semantic_duplicate(FakeBackfillSession([]), make_order())
    finally:
        get_settings.cache_clear()

    assert result.status == "fallback"
    assert result.fallback_reason == "embedding_unavailable"


async def test_backfill_dry_run_does_not_update_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_DEDUP_ENABLED", "true")
    get_settings.cache_clear()
    session = FakeBackfillSession([make_order()])
    calls = 0

    async def fake_storage_available(session: object) -> bool:
        return True

    async def fake_ensure_order_embedding(*args: object, **kwargs: object) -> list[float]:
        nonlocal calls
        calls += 1
        return [0.1, 0.2]

    monkeypatch.setattr(
        semantic_deduplication, "semantic_storage_available", fake_storage_available
    )
    monkeypatch.setattr(
        semantic_deduplication, "ensure_order_embedding", fake_ensure_order_embedding
    )

    try:
        result = await backfill_order_embeddings(session, dry_run=True, batch_size=1)
    finally:
        get_settings.cache_clear()

    assert result.scanned == 1
    assert result.updated == 0
    assert result.skipped == 1
    assert calls == 0
    assert session.commits == 0


async def test_backfill_batch_updates_and_repeat_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_DEDUP_ENABLED", "true")
    get_settings.cache_clear()
    first_order = make_order()
    second_order = make_order()
    second_order.id = UUID("00000000-0000-0000-0000-000000000002")
    session = FakeBackfillSession([first_order, second_order])

    async def fake_storage_available(session: object) -> bool:
        return True

    async def fake_ensure_order_embedding(*args: object, **kwargs: object) -> list[float]:
        return [0.1, 0.2]

    monkeypatch.setattr(
        semantic_deduplication, "semantic_storage_available", fake_storage_available
    )
    monkeypatch.setattr(
        semantic_deduplication, "ensure_order_embedding", fake_ensure_order_embedding
    )

    try:
        first = await backfill_order_embeddings(session, dry_run=False, batch_size=1)
        session.orders = []
        second = await backfill_order_embeddings(session, dry_run=False, batch_size=1)
    finally:
        get_settings.cache_clear()

    assert first.scanned == 1
    assert first.updated == 1
    assert first.skipped == 0
    assert second.scanned == 0
    assert second.updated == 0
    assert session.commits == 2


def make_order(
    *,
    project_type: str = "landing_page",
    summary: str = "Нужен лендинг для курса",
    budget_from: Decimal = Decimal("50000"),
    budget_to: Decimal = Decimal("70000"),
    contacts: dict[str, list[str]] | None = None,
    deadline: date = date(2026, 7, 20),
) -> Order:
    return Order(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        message_id=uuid4(),
        source_id=uuid4(),
        project_type=project_type,
        summary=summary,
        budget_from=budget_from,
        budget_to=budget_to,
        budget_currency="RUB",
        contacts=contacts or {"telegram_username": ["@client"]},
        deadline=deadline,
        published_at=datetime.now(UTC),
        relevance_score=90,
    )


class FakeRows:
    def __init__(self, rows: list[tuple[UUID]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[UUID]]:
        return self._rows


class FakeBackfillSession:
    def __init__(self, orders: list[Order]) -> None:
        self.orders = orders
        self.commits = 0

    async def execute(self, *args: object, **kwargs: object) -> FakeRows:
        return FakeRows([(order.id,) for order in self.orders[:1]])

    async def get(self, model: object, order_id: UUID) -> Order | None:
        return next((order for order in self.orders if order.id == order_id), None)

    async def commit(self) -> None:
        self.commits += 1
