from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classification.ml import MlFallback, MlPrediction, predict_with_ml
from app.classification.rules import (
    ClassificationInput,
    EntityFact,
    RulesClassificationResult,
    classify_rules,
)
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Classification, Message, MessageEntity, Order
from app.monitoring.metrics import (
    CLASSIFICATION_LATENCY_SECONDS,
    observe_duration,
    record_order_found,
)


@dataclass(frozen=True)
class OrderClassificationResult:
    message_id: UUID
    status: str
    label: str
    confidence: float
    manual_review: bool
    relevance_score: int
    order_id: UUID | None = None


@dataclass(frozen=True)
class ClassificationDecision:
    label: str
    confidence: float
    manual_review: bool
    relevance_score: int
    method: str
    explanation: dict[str, Any]
    model_version: str | None = None


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
    with observe_duration(CLASSIFICATION_LATENCY_SECONDS):
        result = await _classify_message_in_session(session, message_id)
    if result.order_id is not None:
        order = await session.get(Order, result.order_id)
        record_order_found(order.project_type if order is not None else None)
    return result


async def _classify_message_in_session(
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
    decision = build_classification_decision(classification_input, rules_result)
    await persist_classification(session, message.id, decision)
    order = await persist_order(session, message, entities, decision)
    await session.flush()

    return OrderClassificationResult(
        message_id=message.id,
        status="classified",
        label=decision.label,
        confidence=decision.confidence,
        manual_review=decision.manual_review,
        relevance_score=decision.relevance_score,
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


def build_classification_decision(
    classification_input: ClassificationInput,
    rules_result: RulesClassificationResult,
) -> ClassificationDecision:
    ml_result = predict_with_ml(classification_input.normalized_text, get_settings())
    if isinstance(ml_result, MlPrediction):
        return ClassificationDecision(
            label=ml_result.label,
            confidence=ml_result.confidence,
            manual_review=False,
            relevance_score=rules_result.relevance_score if ml_result.label == "order" else 0,
            method="ml",
            model_version=ml_result.model_version,
            explanation={
                "ml": ml_result.explanation,
                "rules_shadow": rules_result.explanation,
            },
        )

    return rules_decision(rules_result, ml_result)


def rules_decision(
    rules_result: RulesClassificationResult,
    fallback: MlFallback,
) -> ClassificationDecision:
    explanation = {
        **rules_result.explanation,
        "ml_fallback": {"reason": fallback.reason, "details": fallback.details},
    }
    return ClassificationDecision(
        label=rules_result.label,
        confidence=rules_result.confidence,
        manual_review=rules_result.manual_review,
        relevance_score=rules_result.relevance_score,
        method="rules",
        explanation=explanation,
    )


async def persist_classification(
    session: AsyncSession,
    message_id: UUID,
    result: ClassificationDecision,
) -> None:
    await session.execute(delete(Classification).where(Classification.message_id == message_id))
    session.add(
        Classification(
            message_id=message_id,
            label=result.label,
            confidence=Decimal(str(result.confidence)),
            method=result.method,
            model_version=result.model_version,
            manual_review=result.manual_review,
            explanation=result.explanation,
        )
    )


async def persist_order(
    session: AsyncSession,
    message: Message,
    entities: list[MessageEntity],
    result: ClassificationDecision,
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


def should_create_order(message: Message, result: ClassificationDecision) -> bool:
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
