from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import Message, Order
from app.services.audit import add_audit_log

ALLOWED_STATUS_TRANSITIONS = {
    "new": {"viewed", "contacted", "irrelevant", "archived"},
    "viewed": {"contacted", "irrelevant", "archived"},
    "contacted": {"archived", "irrelevant"},
    "irrelevant": {"archived"},
    "archived": set(),
}


@dataclass(frozen=True)
class OrderRow:
    order: Order
    message_url: str | None


@dataclass(frozen=True)
class OrderFilters:
    date_from: date | None = None
    date_to: date | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    project_type: Sequence[str] | None = None
    relevance_min: int | None = None
    source_id: UUID | None = None
    status: Sequence[str] | None = None
    q: str | None = None


async def list_orders(
    session: AsyncSession,
    filters: OrderFilters,
    *,
    page: int,
    size: int,
) -> tuple[list[OrderRow], int]:
    statement = apply_order_filters(base_order_query(), filters)
    total_statement = select(func.count()).select_from(statement.subquery())
    total = int(await session.scalar(total_statement) or 0)
    rows = (
        await session.execute(
            statement.order_by(Order.published_at.desc(), Order.relevance_score.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return [OrderRow(order=row[0], message_url=row[1]) for row in rows], total


async def get_order_row(session: AsyncSession, order_id: UUID) -> OrderRow:
    row = (await session.execute(base_order_query().where(Order.id == order_id))).one_or_none()
    if row is None:
        raise ApiError(
            code="ORDER_NOT_FOUND",
            message="Order was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return OrderRow(order=row[0], message_url=row[1])


async def update_order_status(
    session: AsyncSession,
    order_id: UUID,
    next_status: str,
    version: int,
) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise ApiError(
            code="ORDER_NOT_FOUND",
            message="Order was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if order.version != version:
        raise ApiError(
            code="ORDER_VERSION_CONFLICT",
            message="Order version is stale.",
            status_code=status.HTTP_409_CONFLICT,
            details={"current_version": order.version},
        )
    allowed = ALLOWED_STATUS_TRANSITIONS.get(order.status, set())
    if next_status not in allowed:
        raise ApiError(
            code="INVALID_ORDER_STATUS_TRANSITION",
            message="Order status transition is not allowed.",
            status_code=status.HTTP_409_CONFLICT,
            details={"from": order.status, "to": next_status},
        )

    previous_status = order.status
    order.status = next_status
    order.version += 1
    await add_audit_log(
        session,
        action="order.status.update",
        entity="order",
        entity_id=order.id,
        payload={"from": previous_status, "to": next_status, "version": version},
    )
    await session.commit()
    await session.refresh(order)
    return order


async def export_orders(
    session: AsyncSession,
    filters: OrderFilters,
    *,
    limit: int,
) -> list[OrderRow]:
    rows = (
        await session.execute(
            apply_order_filters(base_order_query(), filters)
            .order_by(Order.published_at.desc(), Order.relevance_score.desc())
            .limit(limit)
        )
    ).all()
    return [OrderRow(order=row[0], message_url=row[1]) for row in rows]


def base_order_query() -> Select[tuple[Order, str | None]]:
    return select(Order, Message.message_url).join(Message, Order.message_id == Message.id)


def apply_order_filters(
    statement: Select[tuple[Order, str | None]],
    filters: OrderFilters,
) -> Select[tuple[Order, str | None]]:
    if filters.date_from is not None:
        statement = statement.where(func.date(Order.published_at) >= filters.date_from)
    if filters.date_to is not None:
        statement = statement.where(func.date(Order.published_at) <= filters.date_to)
    if filters.budget_min is not None:
        statement = statement.where(
            or_(Order.budget_from >= filters.budget_min, Order.budget_to >= filters.budget_min)
        )
    if filters.budget_max is not None:
        statement = statement.where(
            or_(Order.budget_from <= filters.budget_max, Order.budget_to <= filters.budget_max)
        )
    if filters.project_type:
        statement = statement.where(Order.project_type.in_(filters.project_type))
    if filters.relevance_min is not None:
        statement = statement.where(Order.relevance_score >= filters.relevance_min)
    if filters.source_id is not None:
        statement = statement.where(Order.source_id == filters.source_id)
    if filters.status:
        statement = statement.where(Order.status.in_(filters.status))
    if filters.q:
        pattern = f"%{escape_like(filters.q)}%"
        statement = statement.where(
            or_(
                Order.title.ilike(pattern, escape="\\"),
                Order.summary.ilike(pattern, escape="\\"),
            )
        )
    return statement


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def order_to_response_payload(row: OrderRow) -> dict[str, Any]:
    data = {
        column.name: getattr(row.order, column.name)
        for column in Order.__table__.columns
        if column.name != "duplicate_fingerprint"
    }
    data["message_url"] = row.message_url
    return data
