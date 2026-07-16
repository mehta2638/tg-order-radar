from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Message, MessageEntity
from app.monitoring.metrics import (
    MESSAGE_PROCESSING_SECONDS,
    observe_duration,
    record_message_processed,
)
from app.processing.extractors import ExtractedEntity
from app.processing.keywords import KeywordHit, compile_keyword_rules
from app.processing.pipeline import PrefilterResult, process_text
from app.services.dictionaries import load_compiled_dictionaries


@dataclass(frozen=True)
class MessageProcessingResult:
    message_id: UUID
    status: str
    passed_prefilter: bool
    detected_language: str
    keyword_hits: int
    negative_hits: int
    entities: int


async def process_message(
    message_id: UUID,
    *,
    session: AsyncSession | None = None,
) -> MessageProcessingResult:
    if session is not None:
        return await process_message_in_session(session, message_id)

    async with async_session_factory() as new_session:
        result = await process_message_in_session(new_session, message_id)
        await new_session.commit()
        return result


async def process_message_in_session(
    session: AsyncSession,
    message_id: UUID,
) -> MessageProcessingResult:
    with observe_duration(MESSAGE_PROCESSING_SECONDS):
        result = await _process_message_in_session(session, message_id)
    record_message_processed(result.status)
    return result


async def _process_message_in_session(
    session: AsyncSession,
    message_id: UUID,
) -> MessageProcessingResult:
    message = await get_message(session, message_id)
    if message is None:
        return MessageProcessingResult(
            message_id=message_id,
            status="not_found",
            passed_prefilter=False,
            detected_language="unknown",
            keyword_hits=0,
            negative_hits=0,
            entities=0,
        )

    positive_rules, negative_rules = await load_compiled_dictionaries(session=session)
    result = process_text(
        message.text,
        positive_rules=compile_keyword_rules(positive_rules),
        negative_rules=compile_keyword_rules(negative_rules),
        fuzzy_enabled=get_settings().processing_fuzzy_enabled,
    )
    await persist_processing_result(session, message, result)
    return MessageProcessingResult(
        message_id=message.id,
        status="processed",
        passed_prefilter=result.passed_prefilter,
        detected_language=result.detected_language,
        keyword_hits=len(result.keyword_hits),
        negative_hits=len(result.negative_hits),
        entities=len(result.extracted_entities),
    )


async def get_message(session: AsyncSession, message_id: UUID) -> Message | None:
    result = await session.scalars(select(Message).where(Message.id == message_id))
    return result.one_or_none()


async def persist_processing_result(
    session: AsyncSession,
    message: Message,
    result: PrefilterResult,
) -> None:
    message.normalized_text = result.normalized_text
    message.detected_language = result.detected_language
    message.passed_prefilter = result.passed_prefilter

    await session.execute(delete(MessageEntity).where(MessageEntity.message_id == message.id))
    for entity in build_message_entities(message.id, result):
        session.add(entity)
    await session.flush()


def build_message_entities(message_id: UUID, result: PrefilterResult) -> list[MessageEntity]:
    entities: list[MessageEntity] = []
    for hit in result.keyword_hits:
        entities.append(entity_from_keyword_hit(message_id, "keyword_hit", hit))
    for hit in result.negative_hits:
        entities.append(entity_from_keyword_hit(message_id, "negative_keyword_hit", hit))
    for extracted in result.extracted_entities:
        entities.append(entity_from_extracted(message_id, extracted))
    return entities


def entity_from_keyword_hit(message_id: UUID, entity_type: str, hit: KeywordHit) -> MessageEntity:
    return MessageEntity(
        message_id=message_id,
        type=entity_type,
        value_text=hit.matched_text,
        value_norm={
            "phrase": hit.phrase,
            "weight": hit.weight,
            "category": hit.category,
            "is_regex": hit.is_regex,
            "is_fuzzy": hit.is_fuzzy,
            "distance": hit.distance,
        },
        confidence=Decimal("0.90") if not hit.is_fuzzy else Decimal("0.75"),
    )


def entity_from_extracted(message_id: UUID, extracted: ExtractedEntity) -> MessageEntity:
    return MessageEntity(
        message_id=message_id,
        type=extracted.type,
        value_text=extracted.value_text,
        value_norm=extracted.value_norm,
        confidence=Decimal(str(extracted.confidence)),
    )
