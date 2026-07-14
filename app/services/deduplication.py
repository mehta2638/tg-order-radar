from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import DuplicateGroup, Message, Order
from app.services.audit import add_audit_log


@dataclass(frozen=True)
class OrderDuplicateCandidate:
    order_id: UUID
    published_at: datetime
    completeness: int
    relevance_score: int


@dataclass(frozen=True)
class DeduplicationResult:
    order_id: UUID
    status: str
    is_canonical: bool
    canonical_order_id: UUID
    duplicate_group_id: UUID | None
    duplicate_count: int
    method: str


async def detect_duplicates_for_order(
    order_id: UUID,
    *,
    session: AsyncSession | None = None,
) -> DeduplicationResult:
    if session is not None:
        return await detect_duplicates_in_session(session, order_id)

    async with async_session_factory() as new_session:
        result = await detect_duplicates_in_session(new_session, order_id)
        await new_session.commit()
        return result


async def detect_duplicates_in_session(
    session: AsyncSession,
    order_id: UUID,
) -> DeduplicationResult:
    current = await get_order_with_message(session, order_id)
    if current is None:
        return DeduplicationResult(
            order_id=order_id,
            status="not_found",
            is_canonical=False,
            canonical_order_id=order_id,
            duplicate_group_id=None,
            duplicate_count=0,
            method="none",
        )

    order, message = current
    fingerprint = build_duplicate_fingerprint(order, message)
    order.duplicate_fingerprint = fingerprint
    candidates = await find_duplicate_candidates(session, order, message, fingerprint)
    method = dedupe_method(message, fingerprint, candidates)

    if len(candidates) <= 1:
        order.duplicate_group_id = None
        await session.flush()
        return DeduplicationResult(
            order_id=order.id,
            status="unique",
            is_canonical=True,
            canonical_order_id=order.id,
            duplicate_group_id=None,
            duplicate_count=1,
            method=method,
        )

    canonical_candidate = choose_canonical_order(
        [candidate_from_order(item) for item in candidates]
    )
    duplicate_group = await upsert_duplicate_group(
        session,
        candidates,
        canonical_candidate.order_id,
        method,
    )
    return DeduplicationResult(
        order_id=order.id,
        status="duplicate_grouped",
        is_canonical=order.id == canonical_candidate.order_id,
        canonical_order_id=canonical_candidate.order_id,
        duplicate_group_id=duplicate_group.id,
        duplicate_count=len(candidates),
        method=method,
    )


async def get_order_with_message(
    session: AsyncSession,
    order_id: UUID,
) -> tuple[Order, Message] | None:
    result = await session.execute(
        select(Order, Message)
        .join(Message, Order.message_id == Message.id)
        .where(Order.id == order_id)
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row is not None else None


async def find_duplicate_candidates(
    session: AsyncSession,
    order: Order,
    message: Message,
    fingerprint: str,
) -> list[tuple[Order, Message]]:
    window_start = datetime.now(UTC) - timedelta(days=get_settings().relevance_freshness_days)
    conditions = [Order.duplicate_fingerprint == fingerprint]
    if message.content_hash:
        conditions.append(Message.content_hash == message.content_hash)

    result = await session.execute(
        select(Order, Message)
        .join(Message, Order.message_id == Message.id)
        .where(
            Order.published_at >= window_start,
            or_(*conditions),
        )
    )
    rows = [(row[0], row[1]) for row in result.all()]
    if order.id not in {row_order.id for row_order, _ in rows}:
        rows.append((order, message))
    return rows


def build_duplicate_fingerprint(order: Order, message: Message) -> str:
    payload = {
        "text": message.normalized_text or order.summary or "",
        "contacts": normalize_contacts(order.contacts),
        "budget": {
            "from": decimal_to_string(order.budget_from),
            "to": decimal_to_string(order.budget_to),
            "currency": order.budget_currency,
            "negotiable": order.budget_negotiable,
        },
        "project_type": order.project_type,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_contacts(contacts: dict[str, Any] | None) -> dict[str, list[str]]:
    if not contacts:
        return {}
    normalized: dict[str, list[str]] = {}
    for kind, values in contacts.items():
        if isinstance(values, list):
            normalized[kind] = sorted(str(value).casefold() for value in values)
        else:
            normalized[kind] = [str(values).casefold()]
    return dict(sorted(normalized.items()))


def decimal_to_string(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def dedupe_method(
    message: Message,
    fingerprint: str,
    candidates: list[tuple[Order, Message]],
) -> str:
    if message.content_hash and any(
        candidate_message.content_hash == message.content_hash
        for _, candidate_message in candidates
    ):
        return "content_hash"
    return "fingerprint" if fingerprint else "none"


def candidate_from_order(order_and_message: tuple[Order, Message]) -> OrderDuplicateCandidate:
    order, _ = order_and_message
    return OrderDuplicateCandidate(
        order_id=order.id,
        published_at=order.published_at,
        completeness=order_completeness(order),
        relevance_score=order.relevance_score,
    )


def order_completeness(order: Order) -> int:
    return sum(
        [
            1 if order.budget_from is not None or order.budget_to is not None else 0,
            1 if order.budget_negotiable else 0,
            1 if order.deadline is not None or order.deadline_text else 0,
            1 if order.contacts else 0,
            1 if order.project_type else 0,
            1 if order.summary else 0,
        ]
    )


def choose_canonical_order(
    candidates: list[OrderDuplicateCandidate],
) -> OrderDuplicateCandidate:
    return sorted(
        candidates,
        key=lambda item: (
            normalize_datetime(item.published_at),
            -item.completeness,
            -item.relevance_score,
            str(item.order_id),
        ),
    )[0]


def normalize_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def upsert_duplicate_group(
    session: AsyncSession,
    candidates: list[tuple[Order, Message]],
    canonical_order_id: UUID,
    method: str,
) -> DuplicateGroup:
    existing_groups = [
        order.duplicate_group_id for order, _ in candidates if order.duplicate_group_id is not None
    ]
    duplicate_group = (
        await get_duplicate_group(session, existing_groups[0]) if existing_groups else None
    )
    if duplicate_group is None:
        duplicate_group = DuplicateGroup(method=method, canonical_order_id=canonical_order_id)
        session.add(duplicate_group)
        await session.flush()

    duplicate_group.canonical_order_id = canonical_order_id
    duplicate_group.method = method
    duplicate_group.similarity = Decimal("1.0000")
    duplicate_group.size = len(candidates)
    for order, _ in candidates:
        order.duplicate_group_id = duplicate_group.id
    await session.flush()
    return duplicate_group


async def get_duplicate_group(
    session: AsyncSession,
    duplicate_group_id: UUID,
) -> DuplicateGroup | None:
    result = await session.scalars(
        select(DuplicateGroup).where(DuplicateGroup.id == duplicate_group_id)
    )
    return result.one_or_none()


async def manual_set_canonical_order(
    session: AsyncSession,
    duplicate_group_id: UUID,
    canonical_order_id: UUID,
) -> None:
    duplicate_group = await get_duplicate_group(session, duplicate_group_id)
    if duplicate_group is None:
        raise ValueError("Duplicate group not found.")
    previous_canonical_order_id = duplicate_group.canonical_order_id
    duplicate_group.canonical_order_id = canonical_order_id
    await add_audit_log(
        session,
        action="duplicate_group.set_canonical",
        entity="duplicate_group",
        entity_id=duplicate_group_id,
        payload={
            "previous_canonical_order_id": str(previous_canonical_order_id)
            if previous_canonical_order_id
            else None,
            "canonical_order_id": str(canonical_order_id),
        },
    )


async def manual_assign_order_to_duplicate_group(
    session: AsyncSession,
    order_id: UUID,
    duplicate_group_id: UUID | None,
) -> None:
    result = await session.scalars(select(Order).where(Order.id == order_id))
    order = result.one_or_none()
    if order is None:
        raise ValueError("Order not found.")
    previous_duplicate_group_id = order.duplicate_group_id
    order.duplicate_group_id = duplicate_group_id
    await add_audit_log(
        session,
        action="order.set_duplicate_group",
        entity="order",
        entity_id=order_id,
        payload={
            "previous_duplicate_group_id": str(previous_duplicate_group_id)
            if previous_duplicate_group_id
            else None,
            "duplicate_group_id": str(duplicate_group_id) if duplicate_group_id else None,
        },
    )
