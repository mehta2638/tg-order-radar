from __future__ import annotations

from typing import Any, Literal, NoReturn
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import Keyword, NegativeKeyword
from app.processing.keywords import InvalidKeywordRegex, KeywordRule, compile_keyword_rule
from app.services.audit import add_audit_log
from app.services.dictionaries import invalidate_dictionary_cache


async def list_keywords(session: AsyncSession) -> list[Keyword]:
    return list(await session.scalars(select(Keyword).order_by(Keyword.phrase)))


async def list_negative_keywords(session: AsyncSession) -> list[NegativeKeyword]:
    return list(await session.scalars(select(NegativeKeyword).order_by(NegativeKeyword.phrase)))


async def create_keyword(
    session: AsyncSession,
    payload: dict[str, Any],
) -> Keyword:
    validate_regex(payload["phrase"], payload.get("is_regex", False))
    keyword = Keyword(**payload)
    session.add(keyword)
    await commit_dictionary_change(session, "keyword.create", "keyword", keyword)
    return keyword


async def create_negative_keyword(
    session: AsyncSession,
    payload: dict[str, Any],
) -> NegativeKeyword:
    validate_regex(payload["phrase"], payload.get("is_regex", False))
    keyword = NegativeKeyword(**payload)
    session.add(keyword)
    await commit_dictionary_change(session, "negative_keyword.create", "negative_keyword", keyword)
    return keyword


async def update_keyword(
    session: AsyncSession,
    keyword_id: UUID,
    payload: dict[str, Any],
) -> Keyword:
    keyword = await get_keyword(session, keyword_id)
    update_model(keyword, payload)
    validate_regex(keyword.phrase, keyword.is_regex)
    await commit_dictionary_change(session, "keyword.update", "keyword", keyword)
    return keyword


async def update_negative_keyword(
    session: AsyncSession,
    keyword_id: UUID,
    payload: dict[str, Any],
) -> NegativeKeyword:
    keyword = await get_negative_keyword(session, keyword_id)
    update_model(keyword, payload)
    validate_regex(keyword.phrase, keyword.is_regex)
    await commit_dictionary_change(session, "negative_keyword.update", "negative_keyword", keyword)
    return keyword


async def delete_keyword(
    session: AsyncSession,
    keyword_id: UUID,
    kind: Literal["positive", "negative"],
) -> None:
    model = (
        await get_keyword(session, keyword_id)
        if kind == "positive"
        else await get_negative_keyword(session, keyword_id)
    )
    await session.delete(model)
    await add_audit_log(
        session,
        action=f"{'keyword' if kind == 'positive' else 'negative_keyword'}.delete",
        entity="keyword" if kind == "positive" else "negative_keyword",
        entity_id=keyword_id,
    )
    await session.commit()
    await invalidate_dictionary_cache()


async def get_keyword(session: AsyncSession, keyword_id: UUID) -> Keyword:
    keyword = await session.get(Keyword, keyword_id)
    if keyword is None:
        raise_dictionary_not_found()
    return keyword


async def get_negative_keyword(session: AsyncSession, keyword_id: UUID) -> NegativeKeyword:
    keyword = await session.get(NegativeKeyword, keyword_id)
    if keyword is None:
        raise_dictionary_not_found()
    return keyword


async def commit_dictionary_change(
    session: AsyncSession,
    action: str,
    entity: str,
    keyword: Keyword | NegativeKeyword,
) -> None:
    await add_audit_log(session, action=action, entity=entity, entity_id=keyword.id)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            code="DUPLICATE_KEYWORD",
            message="Keyword already exists for this language.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    await session.refresh(keyword)
    await invalidate_dictionary_cache()


def update_model(model: Keyword | NegativeKeyword, payload: dict[str, Any]) -> None:
    for field_name, value in payload.items():
        if value is not None:
            setattr(model, field_name, value)


def validate_regex(phrase: str, is_regex: bool) -> None:
    if not is_regex:
        return
    try:
        compile_keyword_rule(KeywordRule(None, phrase, "ru", 1, is_regex=True))
    except InvalidKeywordRegex as exc:
        raise ApiError(
            code="INVALID_REGEX",
            message="Keyword regex is invalid.",
            status_code=422,
            details={"phrase": phrase},
        ) from exc


def raise_dictionary_not_found() -> NoReturn:
    raise ApiError(
        code="KEYWORD_NOT_FOUND",
        message="Keyword was not found.",
        status_code=status.HTTP_404_NOT_FOUND,
    )
