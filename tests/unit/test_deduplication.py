from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.models import Message, Order
from app.services.deduplication import (
    OrderDuplicateCandidate,
    build_duplicate_fingerprint,
    choose_canonical_order,
    order_completeness,
)


def test_same_order_across_channels_has_same_duplicate_fingerprint() -> None:
    first_order = make_order(
        "00000000-0000-0000-0000-000000000001",
        "11111111-1111-1111-1111-111111111111",
    )
    second_order = make_order(
        "00000000-0000-0000-0000-000000000002",
        "22222222-2222-2222-2222-222222222222",
    )
    first_message = make_message(first_order.message_id)
    second_message = make_message(second_order.message_id)

    assert build_duplicate_fingerprint(first_order, first_message) == build_duplicate_fingerprint(
        second_order,
        second_message,
    )


def test_canonical_order_is_deterministic_by_earliest_completeness_relevance_id() -> None:
    later_full = OrderDuplicateCandidate(
        order_id=UUID("00000000-0000-0000-0000-000000000003"),
        published_at=datetime(2026, 7, 15, 11, tzinfo=UTC),
        completeness=6,
        relevance_score=95,
    )
    earliest_sparse = OrderDuplicateCandidate(
        order_id=UUID("00000000-0000-0000-0000-000000000001"),
        published_at=datetime(2026, 7, 15, 10, tzinfo=UTC),
        completeness=2,
        relevance_score=60,
    )
    same_time_more_complete = OrderDuplicateCandidate(
        order_id=UUID("00000000-0000-0000-0000-000000000002"),
        published_at=datetime(2026, 7, 15, 10, tzinfo=UTC),
        completeness=5,
        relevance_score=90,
    )

    canonical = choose_canonical_order([later_full, earliest_sparse, same_time_more_complete])

    assert canonical.order_id == same_time_more_complete.order_id


def test_only_canonical_order_is_notification_candidate() -> None:
    canonical = UUID("00000000-0000-0000-0000-000000000001")
    duplicate = UUID("00000000-0000-0000-0000-000000000002")

    assert (
        canonical
        == choose_canonical_order(
            [
                OrderDuplicateCandidate(
                    order_id=duplicate,
                    published_at=datetime(2026, 7, 15, 12, tzinfo=UTC),
                    completeness=6,
                    relevance_score=99,
                ),
                OrderDuplicateCandidate(
                    order_id=canonical,
                    published_at=datetime(2026, 7, 15, 11, tzinfo=UTC),
                    completeness=6,
                    relevance_score=90,
                ),
            ]
        ).order_id
    )


def test_order_completeness_counts_budget_deadline_contact_project_type_summary() -> None:
    order = make_order(
        "00000000-0000-0000-0000-000000000004",
        "33333333-3333-3333-3333-333333333333",
    )

    assert order_completeness(order) == 5


def make_order(order_id: str, message_id: str) -> Order:
    return Order(
        id=UUID(order_id),
        message_id=UUID(message_id),
        source_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        project_type="landing_page",
        summary="Нужен лендинг для курса",
        budget_from=Decimal("50000"),
        budget_to=Decimal("80000"),
        budget_currency="RUB",
        budget_negotiable=False,
        deadline=datetime(2026, 7, 25, tzinfo=UTC).date(),
        contacts={"telegram_username": ["@client"]},
        published_at=datetime(2026, 7, 15, tzinfo=UTC),
        relevance_score=90,
    )


def make_message(message_id: UUID) -> Message:
    return Message(
        id=message_id,
        source_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        tg_message_id=1,
        published_at=datetime.now(UTC) - timedelta(days=1),
        normalized_text="нужен лендинг для курса бюджет 50к 80к пишите @client",
        content_hash="same-content-hash",
    )
