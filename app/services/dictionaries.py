from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

import redis.asyncio as redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Keyword, NegativeKeyword
from app.processing.keywords import KeywordRule, compile_keyword_rules

DICTIONARY_RELOAD_CHANNEL = "dict:reload"
POSITIVE_CACHE_KEY = "dict:keywords:positive:v1"
NEGATIVE_CACHE_KEY = "dict:keywords:negative:v1"


async def load_compiled_dictionaries(
    session: AsyncSession | None = None,
) -> tuple[list[KeywordRule], list[KeywordRule]]:
    positive_rules = await load_keyword_rules("positive", session=session)
    negative_rules = await load_keyword_rules("negative", session=session)
    compile_keyword_rules(positive_rules)
    compile_keyword_rules(negative_rules)
    return positive_rules, negative_rules


async def load_keyword_rules(
    kind: Literal["positive", "negative"],
    session: AsyncSession | None = None,
) -> list[KeywordRule]:
    cached = await load_cached_rules(kind)
    if cached is not None:
        return cached

    if session is not None:
        rules = await load_rules_from_db(kind, session)
    else:
        async with async_session_factory() as new_session:
            rules = await load_rules_from_db(kind, new_session)

    await cache_rules(kind, rules)
    return rules


async def load_rules_from_db(
    kind: Literal["positive", "negative"],
    session: AsyncSession,
) -> list[KeywordRule]:
    if kind == "positive":
        rows = list(await session.scalars(select(Keyword).where(Keyword.enabled.is_(True))))
        return [
            KeywordRule(
                id=row.id,
                phrase=row.phrase,
                lang=row.lang,
                weight=row.weight,
                category=row.category,
                is_regex=row.is_regex,
            )
            for row in rows
        ]

    rows = list(
        await session.scalars(select(NegativeKeyword).where(NegativeKeyword.enabled.is_(True)))
    )
    return [
        KeywordRule(
            id=row.id,
            phrase=row.phrase,
            lang=row.lang,
            weight=row.weight,
            category="negative",
            is_regex=row.is_regex,
        )
        for row in rows
    ]


async def load_cached_rules(kind: Literal["positive", "negative"]) -> list[KeywordRule] | None:
    client = redis.from_url(get_settings().redis_url)
    try:
        raw_value = await client.get(cache_key(kind))
        if raw_value is None:
            return None
        value = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else str(raw_value)
        return [rule_from_json(item) for item in json.loads(value)]
    finally:
        await client.aclose()


async def cache_rules(kind: Literal["positive", "negative"], rules: list[KeywordRule]) -> None:
    settings = get_settings()
    client = redis.from_url(settings.redis_url)
    try:
        await client.set(
            cache_key(kind),
            json.dumps([rule_to_json(rule) for rule in rules], ensure_ascii=False),
            ex=settings.dictionary_cache_ttl_seconds,
        )
    finally:
        await client.aclose()


async def invalidate_dictionary_cache() -> None:
    client = redis.from_url(get_settings().redis_url)
    try:
        await client.delete(POSITIVE_CACHE_KEY, NEGATIVE_CACHE_KEY)
        await client.publish(DICTIONARY_RELOAD_CHANNEL, "reload")
    except (OSError, RedisError):
        return
    finally:
        await client.aclose()


def cache_key(kind: Literal["positive", "negative"]) -> str:
    return POSITIVE_CACHE_KEY if kind == "positive" else NEGATIVE_CACHE_KEY


def rule_to_json(rule: KeywordRule) -> dict[str, object]:
    return {
        "id": str(rule.id) if rule.id is not None else None,
        "phrase": rule.phrase,
        "lang": rule.lang,
        "weight": rule.weight,
        "category": rule.category,
        "is_regex": rule.is_regex,
    }


def rule_from_json(value: dict[str, object]) -> KeywordRule:
    raw_id = value.get("id")
    raw_weight = value["weight"]
    return KeywordRule(
        id=UUID(raw_id) if isinstance(raw_id, str) else None,
        phrase=str(value["phrase"]),
        lang=str(value["lang"]),
        weight=json_int(raw_weight),
        category=str(value["category"]) if value.get("category") is not None else None,
        is_regex=bool(value["is_regex"]),
    )


def json_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"Expected JSON integer-compatible value, got {type(value).__name__}.")
