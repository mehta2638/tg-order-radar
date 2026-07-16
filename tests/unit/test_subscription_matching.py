from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.models import Message, NotificationSubscription, Order
from app.services.subscription_matching import (
    is_in_quiet_hours,
    next_quiet_hours_end,
    subscription_matches_order,
    validate_quiet_hours,
    validate_timezone,
)


def make_order(**kwargs: object) -> Order:
    payload = {
        "id": uuid4(),
        "message_id": uuid4(),
        "source_id": uuid4(),
        "project_type": "landing",
        "title": "Нужен лендинг",
        "summary": "Нужен лендинг для курса",
        "budget_from": Decimal("80000"),
        "budget_to": Decimal("100000"),
        "budget_currency": "RUB",
        "published_at": datetime.now(UTC),
        "relevance_score": 85,
        "status": "new",
        "is_fresh": True,
        "duplicate_fingerprint": "fp-1",
    }
    payload.update(kwargs)
    return Order(**payload)  # type: ignore[arg-type]


def make_subscription(**kwargs: object) -> NotificationSubscription:
    payload = {
        "id": uuid4(),
        "user_id": uuid4(),
        "name": "default",
        "enabled": True,
        "project_types": [],
        "currencies": [],
        "source_ids": [],
        "positive_keywords": [],
        "negative_keywords": [],
        "timezone": "UTC",
        "rate_limit_period_minutes": 60,
    }
    payload.update(kwargs)
    return NotificationSubscription(**payload)  # type: ignore[arg-type]


def test_empty_filters_do_not_block_order() -> None:
    assert subscription_matches_order(make_subscription(), make_order(), None) is True


def test_relevance_threshold_blocks_low_score() -> None:
    assert (
        subscription_matches_order(
            make_subscription(min_relevance_score=90),
            make_order(relevance_score=80),
            None,
        )
        is False
    )


def test_project_type_filter_allows_and_blocks() -> None:
    subscription = make_subscription(project_types=["landing", "bot"])
    assert subscription_matches_order(subscription, make_order(project_type="landing"), None)
    assert not subscription_matches_order(subscription, make_order(project_type="ecommerce"), None)


def test_budget_and_currency_filters() -> None:
    subscription = make_subscription(
        budget_min=Decimal("50000"),
        budget_max=Decimal("120000"),
        currencies=["RUB"],
    )
    assert subscription_matches_order(subscription, make_order(), None)
    assert not subscription_matches_order(subscription, make_order(budget_currency="USD"), None)
    assert not subscription_matches_order(
        subscription,
        make_order(budget_from=Decimal("200000"), budget_to=Decimal("250000")),
        None,
    )


def test_positive_keyword_allows_and_negative_blocks() -> None:
    message = Message(
        id=uuid4(),
        source_id=uuid4(),
        tg_message_id=1,
        text="Нужен лендинг и crm",
        normalized_text="нужен лендинг и crm",
        published_at=datetime.now(UTC),
    )
    positive = make_subscription(positive_keywords=["лендинг"])
    assert subscription_matches_order(positive, make_order(), message)
    blocked = make_subscription(
        positive_keywords=["лендинг"],
        negative_keywords=["crm"],
    )
    assert not subscription_matches_order(blocked, make_order(), message)


def test_source_filter() -> None:
    source_id = uuid4()
    subscription = make_subscription(source_ids=[str(source_id)])
    assert subscription_matches_order(subscription, make_order(source_id=source_id), None)
    assert not subscription_matches_order(subscription, make_order(), None)


def test_disabled_subscription_never_matches() -> None:
    assert not subscription_matches_order(make_subscription(enabled=False), make_order(), None)


def test_quiet_hours_across_midnight() -> None:
    now = datetime(2026, 7, 16, 23, 30, tzinfo=UTC)
    assert is_in_quiet_hours(now, start="22:00", end="07:00", timezone_name="UTC")
    assert not is_in_quiet_hours(
        datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
        start="22:00",
        end="07:00",
        timezone_name="UTC",
    )
    scheduled = next_quiet_hours_end(now, start="22:00", end="07:00", timezone_name="UTC")
    assert scheduled is not None
    assert scheduled == datetime(2026, 7, 17, 7, 0, tzinfo=UTC)


def test_quiet_hours_in_user_timezone() -> None:
    # 21:30 UTC = 00:30 Europe/Moscow next day
    now = datetime(2026, 7, 16, 21, 30, tzinfo=UTC)
    assert is_in_quiet_hours(now, start="00:00", end="08:00", timezone_name="Europe/Moscow")


def test_validate_timezone_and_quiet_hours() -> None:
    assert validate_timezone("Europe/Moscow") == "Europe/Moscow"
    with pytest.raises(ValueError):
        validate_timezone("Not/AZone")
    assert validate_quiet_hours("22:00", "07:00") == ("22:00", "07:00")
    with pytest.raises(ValueError):
        validate_quiet_hours("22:00", None)


def test_zoneinfo_available_for_moscow() -> None:
    assert ZoneInfo("Europe/Moscow").key == "Europe/Moscow"


def test_freshness_filter() -> None:
    subscription = make_subscription(freshness_days=2)
    old = make_order(published_at=datetime.now(UTC) - timedelta(days=5))
    assert not subscription_matches_order(subscription, old, None)
