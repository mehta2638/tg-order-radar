from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Classification, Message, Order, TelegramSource


@dataclass(frozen=True)
class ActivityMetrics:
    msg_count_7d: int
    order_candidates_7d: int
    hours_since_last: float | None
    active_days_7d: int
    relevant_orders_7d: int
    spam_7d: int
    dup_7d: int


@dataclass(frozen=True)
class ActivityCalculation:
    source_id: UUID
    activity_score: int
    activity_status: str
    poll_mode: str
    metrics: ActivityMetrics


async def recalculate_source_activity(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[ActivityCalculation]:
    active_now = normalize_datetime(now or datetime.now(UTC))
    source_ids = list(await session.scalars(select(TelegramSource.id).order_by(TelegramSource.id)))
    results: list[ActivityCalculation] = []
    for source_id in source_ids:
        result = await recalculate_single_source_activity(session, source_id, now=active_now)
        if result is not None:
            results.append(result)
    await session.commit()
    return results


async def recalculate_single_source_activity(
    session: AsyncSession,
    source_id: UUID,
    *,
    now: datetime | None = None,
) -> ActivityCalculation | None:
    source = await session.get(TelegramSource, source_id)
    if source is None:
        return None

    active_now = normalize_datetime(now or datetime.now(UTC))
    cutoff = active_now - timedelta(days=7)
    metrics = await collect_activity_metrics(session, source_id, cutoff=cutoff, now=active_now)
    score = calculate_activity_score(metrics)
    status = activity_status(score)
    poll_mode = activity_poll_mode(score, source.type)

    source.activity_score = score
    source.activity_status = status
    source.poll_mode = poll_mode
    await session.flush()
    return ActivityCalculation(
        source_id=source.id,
        activity_score=score,
        activity_status=status,
        poll_mode=poll_mode,
        metrics=metrics,
    )


async def collect_activity_metrics(
    session: AsyncSession,
    source_id: UUID,
    *,
    cutoff: datetime,
    now: datetime,
) -> ActivityMetrics:
    message_row = (
        await session.execute(
            select(
                func.count(Message.id),
                func.max(Message.published_at),
                func.count(distinct(func.date(Message.published_at))),
                func.coalesce(
                    func.sum(case((Message.passed_prefilter.is_(True), 1), else_=0)),
                    0,
                ),
            ).where(
                Message.source_id == source_id,
                Message.published_at >= cutoff,
                Message.deleted_at.is_(None),
            )
        )
    ).one()
    msg_count = int(message_row[0] or 0)
    last_published_at = message_row[1]
    active_days = int(message_row[2] or 0)
    order_candidates = int(message_row[3] or 0)
    relevant_orders = int(
        await session.scalar(
            select(func.count(Order.id)).where(
                Order.source_id == source_id,
                Order.published_at >= cutoff,
                Order.relevance_score >= get_settings().order_min_relevance_score,
            )
        )
        or 0
    )
    spam_count = int(
        await session.scalar(
            select(func.count(distinct(Message.id)))
            .join(Classification, Classification.message_id == Message.id)
            .where(
                Message.source_id == source_id,
                Message.published_at >= cutoff,
                Classification.label.in_(("spam", "service_ad")),
            )
        )
        or 0
    )
    duplicate_count = int(
        await session.scalar(
            select(func.count(Order.id)).where(
                Order.source_id == source_id,
                Order.published_at >= cutoff,
                Order.duplicate_group_id.is_not(None),
            )
        )
        or 0
    )
    return ActivityMetrics(
        msg_count_7d=msg_count,
        order_candidates_7d=order_candidates,
        hours_since_last=hours_since(last_published_at, now),
        active_days_7d=active_days,
        relevant_orders_7d=relevant_orders,
        spam_7d=spam_count,
        dup_7d=duplicate_count,
    )


def calculate_activity_score(metrics: ActivityMetrics) -> int:
    volume = min(metrics.msg_count_7d / 200, 1)
    order_candidates = min(metrics.order_candidates_7d / 40, 1)
    recency = (
        0.0 if metrics.hours_since_last is None else max(0.0, 1 - metrics.hours_since_last / 168)
    )
    regularity = min(metrics.active_days_7d / 7, 1)
    relevance = metrics.relevant_orders_7d / max(metrics.order_candidates_7d, 1)
    noise = min((metrics.spam_7d + metrics.dup_7d) / max(metrics.msg_count_7d, 1), 1)
    raw = (
        0.20 * volume
        + 0.30 * order_candidates
        + 0.15 * recency
        + 0.15 * regularity
        + 0.20 * relevance
        - 0.15 * noise
    )
    return round(max(0.0, min(1.0, raw)) * 100)


def activity_status(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "active"
    if score >= 20:
        return "low"
    return "inactive"


def activity_poll_mode(score: int, source_type: str) -> str:
    if score >= 75:
        return "realtime"
    if score >= 50 and source_type == "megagroup":
        return "realtime"
    return "poll"


def hours_since(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    published_at = normalize_datetime(value)
    return max(0.0, (now - published_at).total_seconds() / 3600)


def normalize_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
