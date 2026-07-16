from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import Message, NotificationSubscription, Order
from app.processing.normalization import normalize_text


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(hour=int(hours), minute=int(minutes))


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {name}") from exc
    return name


def validate_quiet_hours(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    if start is None and end is None:
        return None, None
    if start is None or end is None:
        raise ValueError("quiet_hours_start and quiet_hours_end must be set together")
    try:
        parse_hhmm(start)
        parse_hhmm(end)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("quiet hours must use HH:MM format") from exc
    if len(start) != 5 or len(end) != 5:
        raise ValueError("quiet hours must use HH:MM format")
    return start, end


def is_in_quiet_hours(
    now_utc: datetime,
    *,
    start: str | None,
    end: str | None,
    timezone_name: str,
) -> bool:
    if not start or not end:
        return False
    local_now = now_utc.astimezone(ZoneInfo(timezone_name))
    local_time = local_now.timetz().replace(tzinfo=None)
    start_time = parse_hhmm(start)
    end_time = parse_hhmm(end)
    if start_time <= end_time:
        return start_time <= local_time < end_time
    return local_time >= start_time or local_time < end_time


def next_quiet_hours_end(
    now_utc: datetime,
    *,
    start: str | None,
    end: str | None,
    timezone_name: str,
) -> datetime | None:
    if (
        not start
        or not end
        or not is_in_quiet_hours(now_utc, start=start, end=end, timezone_name=timezone_name)
    ):
        return None
    tz = ZoneInfo(timezone_name)
    local_now = now_utc.astimezone(tz)
    end_time = parse_hhmm(end)
    candidate = datetime.combine(local_now.date(), end_time, tzinfo=tz)
    if candidate <= local_now:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(UTC)


def order_search_text(order: Order, message: Message | None) -> str:
    parts = [
        order.title or "",
        order.summary or "",
    ]
    if message is not None:
        parts.append(message.normalized_text or message.text or "")
    return normalize_text(" ".join(parts)).casefold()


def keyword_hit(haystack: str, keywords: list[str]) -> bool:
    if not keywords:
        return False
    return any(normalize_text(keyword).casefold() in haystack for keyword in keywords if keyword)


def representative_order_budget(order: Order) -> Decimal | None:
    if order.budget_from is not None and order.budget_to is not None:
        return (order.budget_from + order.budget_to) / Decimal("2")
    return order.budget_from or order.budget_to


def subscription_matches_order(
    subscription: NotificationSubscription,
    order: Order,
    message: Message | None,
    *,
    now_utc: datetime | None = None,
) -> bool:
    if not subscription.enabled:
        return False

    now = now_utc or datetime.now(UTC)
    if subscription.min_relevance_score is not None:
        if order.relevance_score < subscription.min_relevance_score:
            return False

    project_types = [str(item) for item in (subscription.project_types or [])]
    if project_types:
        if order.project_type is None or order.project_type not in project_types:
            return False

    source_ids = [str(item) for item in (subscription.source_ids or [])]
    if source_ids and str(order.source_id) not in source_ids:
        return False

    currencies = [str(item).upper() for item in (subscription.currencies or [])]
    if currencies:
        if order.budget_currency is None or order.budget_currency.upper() not in currencies:
            return False

    if subscription.budget_min is not None or subscription.budget_max is not None:
        amount = representative_order_budget(order)
        if amount is None:
            return False
        if subscription.budget_min is not None and amount < subscription.budget_min:
            return False
        if subscription.budget_max is not None and amount > subscription.budget_max:
            return False

    if subscription.freshness_days is not None:
        cutoff = now - timedelta(days=subscription.freshness_days)
        if order.published_at < cutoff:
            return False

    haystack = order_search_text(order, message)
    negative = [str(item) for item in (subscription.negative_keywords or [])]
    if keyword_hit(haystack, negative):
        return False

    positive = [str(item) for item in (subscription.positive_keywords or [])]
    if positive and not keyword_hit(haystack, positive):
        return False

    return True
