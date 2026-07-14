from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classification.rules import (
    ClassificationInput,
    EntityFact,
    RulesClassificationResult,
    classify_rules,
)
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Classification, Message, MessageEntity, Order


@dataclass(frozen=True)
class OrderClassificationResult:
    message_id: UUID
    status: str
    label: str
    confidence: float
    manual_review: bool
    relevance_score: int
    order_id: UUID | None = None


async def classify_message(
    message_id: UUID,
    *,
    session: AsyncSession | None = None,
) -> OrderClassificationResult:
    if session is not None:
        return await classify_message_in_session(session, message_id)

    async with async_session_factory() as new_session:
        result = await classify_message_in_session(new_session, message_id)
        await new_session.commit()
        return result


async def classify_message_in_session(
    session: AsyncSession,
    message_id: UUID,
) -> OrderClassificationResult:
    message = await get_message(session, message_id)
    if message is None:
        return OrderClassificationResult(
            message_id=message_id,
            status="not_found",
            label="irrelevant",
            confidence=0.0,
            manual_review=False,
            relevance_score=0,
        )

    entities = list(
        await session.scalars(select(MessageEntity).where(MessageEntity.message_id == message.id))
    )
    classification_input = build_classification_input(message, entities)
    rules_result = classify_rules(classification_input)
    await persist_classification(session, message.id, rules_result)
    order = await persist_order(session, message, entities, rules_result)
    await session.flush()

    return OrderClassificationResult(
        message_id=message.id,
        status="classified",
        label=rules_result.label,
        confidence=rules_result.confidence,
        manual_review=rules_result.manual_review,
        relevance_score=rules_result.relevance_score,
        order_id=order.id if order is not None else None,
    )


async def get_message(session: AsyncSession, message_id: UUID) -> Message | None:
    result = await session.scalars(select(Message).where(Message.id == message_id))
    return result.one_or_none()


def build_classification_input(
    message: Message,
    entities: list[MessageEntity],
) -> ClassificationInput:
    facts = [entity_fact(entity) for entity in entities]
    return ClassificationInput(
        normalized_text=message.normalized_text or "",
        published_at=message.published_at,
        passed_prefilter=message.passed_prefilter,
        keyword_hits=[fact for fact in facts if fact.type == "keyword_hit"],
        negative_hits=[fact for fact in facts if fact.type == "negative_keyword_hit"],
        project_types=[fact for fact in facts if fact.type == "project_type"],
        budgets=[fact for fact in facts if fact.type == "budget"],
        deadlines=[fact for fact in facts if fact.type == "deadline"],
        contacts=[fact for fact in facts if fact.type == "contact"],
    )


def entity_fact(entity: MessageEntity) -> EntityFact:
    return EntityFact(
        type=entity.type,
        value_text=entity.value_text,
        value_norm=entity.value_norm or {},
    )


async def persist_classification(
    session: AsyncSession,
    message_id: UUID,
    result: RulesClassificationResult,
) -> None:
    await session.execute(delete(Classification).where(Classification.message_id == message_id))
    session.add(
        Classification(
            message_id=message_id,
            label=result.label,
            confidence=Decimal(str(result.confidence)),
            method="rules",
            manual_review=result.manual_review,
            explanation=result.explanation,
        )
    )


async def persist_order(
    session: AsyncSession,
    message: Message,
    entities: list[MessageEntity],
    result: RulesClassificationResult,
) -> Order | None:
    existing_order = await get_order_by_message(session, message.id)
    if not should_create_order(message, result):
        if existing_order is not None:
            await session.delete(existing_order)
        return None

    payload = build_order_payload(message, entities, result.relevance_score)
    if existing_order is None:
        order = Order(**payload)
        session.add(order)
        return order

    for field_name, value in payload.items():
        setattr(existing_order, field_name, value)
    existing_order.version += 1
    return existing_order


async def get_order_by_message(session: AsyncSession, message_id: UUID) -> Order | None:
    result = await session.scalars(select(Order).where(Order.message_id == message_id))
    return result.one_or_none()


def should_create_order(message: Message, result: RulesClassificationResult) -> bool:
    settings = get_settings()
    if result.label != "order" or result.manual_review:
        return False
    if result.confidence < settings.classification_order_min_confidence:
        return False
    if result.relevance_score < settings.order_min_relevance_score:
        return False
    return is_fresh(message.published_at)


def build_order_payload(
    message: Message,
    entities: list[MessageEntity],
    relevance_score: int,
) -> dict[str, Any]:
    project_type = extract_project_type(entities)
    budget = extract_budget(entities)
    deadline_value, deadline_text = extract_deadline(entities)
    contacts = extract_contacts(entities)
    return {
        "message_id": message.id,
        "source_id": message.source_id,
        "project_type": project_type,
        "title": build_title(message.text),
        "summary": build_summary(message.text),
        "budget_from": decimal_or_none(budget.get("amount_from")),
        "budget_to": decimal_or_none(budget.get("amount_to")),
        "budget_currency": budget.get("currency"),
        "budget_negotiable": bool(budget.get("negotiable", False)),
        "deadline": deadline_value,
        "deadline_text": deadline_text,
        "contacts": contacts or None,
        "published_at": message.published_at,
        "relevance_score": relevance_score,
        "status": "new",
        "is_fresh": is_fresh(message.published_at),
    }


def extract_project_type(entities: list[MessageEntity]) -> str | None:
    for entity in entities:
        if entity.type == "project_type" and entity.value_norm:
            value = entity.value_norm.get("project_type")
            return str(value) if value else None
    return None


def extract_budget(entities: list[MessageEntity]) -> dict[str, Any]:
    for entity in entities:
        if entity.type == "budget":
            return entity.value_norm or {}
    return {}


def extract_deadline(entities: list[MessageEntity]) -> tuple[date | None, str | None]:
    for entity in entities:
        if entity.type != "deadline":
            continue
        value_norm = entity.value_norm or {}
        raw_deadline = value_norm.get("deadline")
        if isinstance(raw_deadline, str):
            return date.fromisoformat(raw_deadline), None
        return None, str(value_norm.get("deadline_text") or entity.value_text)
    return None, None


def extract_contacts(entities: list[MessageEntity]) -> dict[str, list[str]]:
    contacts: dict[str, list[str]] = {}
    for entity in entities:
        if entity.type != "contact" or not entity.value_norm:
            continue
        kind = str(entity.value_norm.get("kind"))
        value = str(entity.value_norm.get("value"))
        contacts.setdefault(kind, [])
        if value not in contacts[kind]:
            contacts[kind].append(value)
    return contacts


def decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def build_title(text: str | None) -> str | None:
    summary = build_summary(text)
    if summary is None:
        return None
    return summary[:80]


def build_summary(text: str | None) -> str | None:
    if not text:
        return None
    compact = " ".join(text.split())
    return compact[:500]


def is_fresh(published_at: Any) -> bool:
    settings = get_settings()
    published = (
        published_at if published_at.tzinfo is not None else published_at.replace(tzinfo=UTC)
    )
    age_days = (datetime.now(UTC) - published.astimezone(UTC)).total_seconds() / 86400
    return bool(age_days <= settings.relevance_freshness_days)
