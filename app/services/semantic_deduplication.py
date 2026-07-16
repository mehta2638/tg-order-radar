from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol, cast
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import Order
from app.processing.normalization import normalize_text

logger = structlog.get_logger(__name__)


class EmbeddingModel(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class SemanticMetrics:
    comparisons: int = 0
    auto_merge: int = 0
    review_candidates: int = 0
    fallback: int = 0
    model_load_errors: int = 0


_METRICS = SemanticMetrics()


@dataclass(frozen=True)
class SemanticCandidate:
    order_id: UUID
    similarity: float


@dataclass(frozen=True)
class SemanticDedupResult:
    status: str
    candidates: list[SemanticCandidate]
    comparisons: int
    fallback_reason: str | None = None

    @property
    def best_candidate(self) -> SemanticCandidate | None:
        return self.candidates[0] if self.candidates else None


@dataclass(frozen=True)
class SemanticBackfillResult:
    scanned: int
    updated: int
    skipped: int
    fallback: int
    dry_run: bool


def get_semantic_metrics() -> SemanticMetrics:
    return _METRICS


def reset_semantic_metrics() -> None:
    _METRICS.comparisons = 0
    _METRICS.auto_merge = 0
    _METRICS.review_candidates = 0
    _METRICS.fallback = 0
    _METRICS.model_load_errors = 0


async def find_semantic_duplicate(
    session: AsyncSession,
    order: Order,
) -> SemanticDedupResult:
    settings = get_settings()
    if not settings.semantic_dedup_enabled:
        return semantic_fallback("disabled")

    availability = await semantic_storage_available(session)
    if not availability:
        return semantic_fallback("pgvector_unavailable")

    embedding = await ensure_order_embedding(session, order, settings=settings)
    if embedding is None:
        return semantic_fallback("embedding_unavailable")

    candidates = await semantic_search_candidates(session, order, embedding, settings=settings)
    _METRICS.comparisons += len(candidates)
    compatible_candidates = [
        candidate
        for candidate in candidates
        if await candidate_is_compatible(session, order, candidate.order_id)
    ]
    if not compatible_candidates:
        logger.info(
            "semantic_dedup_no_match",
            order_id=str(order.id),
            comparisons=len(candidates),
        )
        return SemanticDedupResult(
            status="no_match",
            candidates=[],
            comparisons=len(candidates),
        )

    best = compatible_candidates[0]
    if best.similarity >= settings.semantic_similarity_threshold:
        _METRICS.auto_merge += 1
        logger.info(
            "semantic_dedup_auto_merge",
            order_id=str(order.id),
            candidate_order_id=str(best.order_id),
            similarity=round(best.similarity, 4),
            comparisons=len(candidates),
        )
        return SemanticDedupResult(
            status="auto_merge",
            candidates=compatible_candidates,
            comparisons=len(candidates),
        )
    if best.similarity >= settings.semantic_review_threshold:
        _METRICS.review_candidates += 1
        logger.info(
            "semantic_dedup_manual_review",
            order_id=str(order.id),
            candidate_order_id=str(best.order_id),
            similarity=round(best.similarity, 4),
            comparisons=len(candidates),
        )
        return SemanticDedupResult(
            status="manual_review",
            candidates=compatible_candidates,
            comparisons=len(candidates),
        )
    logger.info(
        "semantic_dedup_no_match",
        order_id=str(order.id),
        similarity=round(best.similarity, 4),
        comparisons=len(candidates),
    )
    return SemanticDedupResult(
        status="no_match",
        candidates=compatible_candidates,
        comparisons=len(candidates),
    )


async def ensure_order_embedding(
    session: AsyncSession,
    order: Order,
    *,
    settings: Settings | None = None,
) -> list[float] | None:
    active_settings = settings or get_settings()
    try:
        existing = await session.execute(
            text(
                "select semantic_embedding::text from orders "
                "where id = :order_id and semantic_embedding is not null"
            ),
            {"order_id": order.id},
        )
        existing_value = existing.scalar_one_or_none()
        if isinstance(existing_value, str):
            return parse_vector(existing_value)

        embedding = embed_text(order_embedding_text(order), active_settings)
        if len(embedding) != active_settings.semantic_embedding_dimension:
            return None
        await session.execute(
            text(
                "update orders set semantic_embedding = (:embedding)::vector, "
                "semantic_embedding_model = :model, "
                "semantic_embedding_updated_at = now() where id = :order_id"
            ),
            {
                "embedding": vector_literal(embedding),
                "model": active_settings.semantic_model_version,
                "order_id": order.id,
            },
        )
        await session.flush()
        return embedding
    except Exception:
        return None


async def semantic_search_candidates(
    session: AsyncSession,
    order: Order,
    embedding: list[float],
    *,
    settings: Settings | None = None,
) -> list[SemanticCandidate]:
    active_settings = settings or get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=active_settings.semantic_dedup_window_days)
    try:
        result = await session.execute(
            text(
                """
                select o.id, 1 - (o.semantic_embedding <=> (:embedding)::vector) as similarity
                from orders o
                left join duplicate_groups dg on dg.id = o.duplicate_group_id
                where o.id != :order_id
                  and o.published_at >= :cutoff
                  and o.semantic_embedding is not null
                  and (o.duplicate_group_id is null or dg.canonical_order_id = o.id)
                  and (
                      :project_type is null
                      or o.project_type is null
                      or o.project_type = :project_type
                  )
                order by o.semantic_embedding <=> (:embedding)::vector
                limit 20
                """
            ),
            {
                "embedding": vector_literal(embedding),
                "order_id": order.id,
                "cutoff": cutoff,
                "project_type": order.project_type,
            },
        )
        return [
            SemanticCandidate(order_id=row[0], similarity=float(row[1])) for row in result.all()
        ]
    except Exception:
        return []


async def semantic_storage_available(session: AsyncSession) -> bool:
    try:
        result = await session.execute(
            text(
                """
                select exists (select 1 from pg_type where typname = 'vector')
                   and exists (
                       select 1 from information_schema.columns
                       where table_name = 'orders'
                         and column_name = 'semantic_embedding'
                   )
                """
            )
        )
        return bool(result.scalar_one())
    except Exception:
        return False


async def candidate_is_compatible(
    session: AsyncSession,
    order: Order,
    candidate_order_id: UUID,
) -> bool:
    candidate = await session.get(Order, candidate_order_id)
    if candidate is None:
        return False
    if has_strong_contradictions(order, candidate):
        return False
    return True


def has_strong_contradictions(left: Order, right: Order) -> bool:
    if left.project_type and right.project_type and left.project_type != right.project_type:
        return True
    if incompatible_contacts(left, right):
        return True
    if incompatible_budget(left, right):
        return True
    if incompatible_deadline(left, right):
        return True
    return has_negative_semantic_markers(left) or has_negative_semantic_markers(right)


def incompatible_contacts(left: Order, right: Order) -> bool:
    left_contacts = normalize_order_contacts(left.contacts)
    right_contacts = normalize_order_contacts(right.contacts)
    if not left_contacts or not right_contacts:
        return False
    return left_contacts != right_contacts


def normalize_order_contacts(contacts: dict[str, Any] | None) -> dict[str, list[str]]:
    if not contacts:
        return {}
    normalized: dict[str, list[str]] = {}
    for kind, values in contacts.items():
        if isinstance(values, list):
            normalized[kind] = sorted(str(value).casefold() for value in values)
        else:
            normalized[kind] = [str(values).casefold()]
    return dict(sorted(normalized.items()))


def incompatible_budget(left: Order, right: Order) -> bool:
    if (
        left.budget_currency
        and right.budget_currency
        and left.budget_currency != right.budget_currency
    ):
        return True
    left_amount = representative_budget(left)
    right_amount = representative_budget(right)
    if left_amount is None or right_amount is None:
        return False
    larger = max(left_amount, right_amount)
    smaller = min(left_amount, right_amount)
    if larger == 0:
        return False
    return (larger - smaller) / larger > Decimal("0.35")


def representative_budget(order: Order) -> Decimal | None:
    if order.budget_from is not None and order.budget_to is not None:
        return (order.budget_from + order.budget_to) / Decimal("2")
    return order.budget_from or order.budget_to


def incompatible_deadline(left: Order, right: Order) -> bool:
    if left.deadline is None or right.deadline is None:
        return False
    return abs((left.deadline - right.deadline).days) > 30


def has_negative_semantic_markers(order: Order) -> bool:
    text_value = f"{order.title or ''} {order.summary or ''}".casefold()
    return bool(re.search(r"\b(выполню|портфолио|резюме|ищу работу|казино|ставки)\b", text_value))


async def backfill_order_embeddings(
    session: AsyncSession,
    *,
    dry_run: bool,
    batch_size: int | None = None,
) -> SemanticBackfillResult:
    settings = get_settings()
    active_batch_size = batch_size or settings.semantic_batch_size
    if not settings.semantic_dedup_enabled or not await semantic_storage_available(session):
        return SemanticBackfillResult(0, 0, 0, 1, dry_run)

    result = await session.execute(
        text(
            """
            select o.id
            from orders o
            left join duplicate_groups dg on dg.id = o.duplicate_group_id
            where o.semantic_embedding is null
              and (o.duplicate_group_id is null or dg.canonical_order_id = o.id)
            order by o.published_at desc, o.id
            limit :batch_size
            """
        ),
        {"batch_size": active_batch_size},
    )
    order_ids = [row[0] for row in result.all()]
    updated = 0
    skipped = 0
    for order_id in order_ids:
        order = await session.get(Order, order_id)
        if order is None:
            skipped += 1
            continue
        if dry_run:
            skipped += 1
            continue
        if await ensure_order_embedding(session, order, settings=settings) is None:
            skipped += 1
        else:
            updated += 1
    if not dry_run:
        await session.commit()
    return SemanticBackfillResult(
        scanned=len(order_ids),
        updated=updated,
        skipped=skipped,
        fallback=0,
        dry_run=dry_run,
    )


def embed_text(text_value: str, settings: Settings | None = None) -> list[float]:
    active_settings = settings or get_settings()
    try:
        model = get_embedding_model(
            active_settings.semantic_model_name,
            active_settings.semantic_device,
            active_settings.semantic_embedding_dimension,
        )
        return [float(value) for value in model.encode([text_value])[0]]
    except Exception as exc:
        _METRICS.model_load_errors += 1
        logger.warning(
            "semantic_model_load_error",
            error_type=type(exc).__name__,
            model_name=active_settings.semantic_model_name,
        )
        raise


@lru_cache(maxsize=2)
def get_embedding_model(
    model_name: str,
    device: str | None,
    dimension: int,
) -> EmbeddingModel:
    if model_name == "test://hash-embedding":
        return HashEmbeddingModel(dimension)

    from sentence_transformers import SentenceTransformer

    kwargs: dict[str, str] = {}
    if device:
        kwargs["device"] = device
    return cast(EmbeddingModel, SentenceTransformer(model_name, **kwargs))


def clear_embedding_model_cache() -> None:
    get_embedding_model.cache_clear()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(
        left_value * right_value for left_value, right_value in zip(left, right, strict=True)
    )


class HashEmbeddingModel:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [hash_embedding(text_value, self.dimension) for text_value in texts]


def hash_embedding(text_value: str, dimension: int) -> list[float]:
    tokens = semantic_tokens(text_value)
    vector = [0.0] * dimension
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def semantic_tokens(text_value: str) -> list[str]:
    normalized = normalize_embedding_text(text_value)
    aliases = {
        "лендинг": "landing",
        "посадочную": "landing",
        "посадочная": "landing",
        "страница": "landing",
        "страницу": "landing",
        "одностраничник": "landing",
        "курс": "course",
        "курса": "course",
        "онлайн-курса": "course",
        "сайт": "site",
        "магазин": "shop",
        "интернет-магазин": "shop",
        "оплата": "payment",
        "платеж": "payment",
        "crm": "crm",
        "бот": "bot",
    }
    tokens = re.findall(r"[\w-]+", normalized, flags=re.UNICODE)
    return [aliases.get(token, token) for token in tokens]


def order_embedding_text(order: Order) -> str:
    return normalize_embedding_text(
        " ".join(
            value
            for value in [
                order.project_type or "",
                order.title or "",
                order.summary or "",
                order.deadline_text or "",
            ]
            if value
        )
    )


def normalize_embedding_text(text_value: str) -> str:
    normalized = normalize_text(text_value)
    normalized = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", " email ", normalized)
    normalized = re.sub(r"@[a-zA-Z][\w\d_]{4,31}", " username ", normalized)
    normalized = re.sub(r"https?://\S+|t\.me/\S+", " url ", normalized)
    normalized = re.sub(r"\+?\d[\d\s()\-]{7,}\d", " phone ", normalized)
    return " ".join(normalized.split())


def vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def parse_vector(value: str) -> list[float]:
    stripped = value.strip().strip("[]")
    if not stripped:
        return []
    return [float(item) for item in stripped.split(",")]


def semantic_fallback(reason: str) -> SemanticDedupResult:
    _METRICS.fallback += 1
    logger.info("semantic_dedup_fallback", reason=reason)
    return SemanticDedupResult(
        status="fallback",
        candidates=[],
        comparisons=0,
        fallback_reason=reason,
    )
