from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.db.session import async_session_factory
from app.services.semantic_deduplication import (
    backfill_order_embeddings,
    clear_embedding_model_cache,
    cosine_similarity,
    embed_text,
    normalize_embedding_text,
    semantic_storage_available,
    vector_literal,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic dedup utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-pgvector", help="Check CREATE EXTENSION vector and storage.")
    subparsers.add_parser("check-model", help="Load the configured model and embed a sample.")

    embed_parser = subparsers.add_parser("embed", help="Compute an embedding for one text.")
    embed_parser.add_argument("--text", required=True)
    embed_parser.add_argument("--output", type=Path)

    compare_parser = subparsers.add_parser("compare", help="Compare two texts with embeddings.")
    compare_parser.add_argument("--left", required=True)
    compare_parser.add_argument("--right", required=True)

    search_parser = subparsers.add_parser("search", help="Semantic search against existing orders.")
    search_parser.add_argument("--text", required=True)
    search_parser.add_argument("--limit", type=int, default=5)

    backfill_parser = subparsers.add_parser("backfill", help="Backfill canonical order embeddings.")
    backfill_parser.add_argument("--batch-size", type=int)
    backfill_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "check-pgvector":
        emit(asyncio.run(check_pgvector()))
    elif args.command == "check-model":
        emit(check_model())
    elif args.command == "embed":
        payload = compute_embedding(args.text)
        if args.output:
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        emit(payload)
    elif args.command == "compare":
        emit(compare_texts(args.left, args.right))
    elif args.command == "search":
        emit(asyncio.run(search(args.text, args.limit)))
    elif args.command == "backfill":
        emit(asyncio.run(backfill(args.dry_run, args.batch_size)))


def check_model() -> dict[str, Any]:
    clear_embedding_model_cache()
    settings = get_settings()
    try:
        embedding = embed_text("нужен лендинг для курса", settings)
    except Exception as exc:
        return {
            "status": "unavailable",
            "model_name": settings.semantic_model_name,
            "error_type": type(exc).__name__,
        }
    return {
        "status": "ok",
        "model_name": settings.semantic_model_name,
        "model_version": settings.semantic_model_version,
        "dimension": len(embedding),
    }


def compute_embedding(text_value: str) -> dict[str, Any]:
    settings = Settings()
    embedding = embed_text(normalize_embedding_text(text_value), settings)
    return {
        "dimension": len(embedding),
        "model_version": settings.semantic_model_version,
        "embedding_preview": [round(value, 6) for value in embedding[:8]],
    }


def compare_texts(left: str, right: str) -> dict[str, Any]:
    settings = Settings()
    left_embedding = embed_text(normalize_embedding_text(left), settings)
    right_embedding = embed_text(normalize_embedding_text(right), settings)
    similarity = cosine_similarity(left_embedding, right_embedding)
    return {
        "dimension": len(left_embedding),
        "model_version": settings.semantic_model_version,
        "similarity": round(similarity, 4),
    }


async def search(text_value: str, limit: int) -> dict[str, Any]:
    settings = get_settings()
    embedding = embed_text(normalize_embedding_text(text_value), settings)
    async with async_session_factory() as session:
        if not await semantic_storage_available(session):
            return {"status": "fallback", "reason": "pgvector_unavailable", "items": []}
        result = await session.execute(
            text(
                """
                select id, 1 - (semantic_embedding <=> (:embedding)::vector) as similarity
                from orders
                where semantic_embedding is not null
                order by semantic_embedding <=> (:embedding)::vector
                limit :limit
                """
            ),
            {"embedding": vector_literal(embedding), "limit": limit},
        )
        return {
            "status": "ok",
            "items": [
                {"order_id": str(row[0]), "similarity": round(float(row[1]), 4)}
                for row in result.all()
            ],
        }


async def check_pgvector() -> dict[str, Any]:
    async with async_session_factory() as session:
        try:
            await session.execute(text("create extension if not exists vector"))
            await session.commit()
        except Exception as exc:
            await session.rollback()
            return {
                "status": "unavailable",
                "error_type": type(exc).__name__,
                "message": "pgvector extension is not installed in this PostgreSQL image",
            }
        return {
            "status": "ok" if await semantic_storage_available(session) else "extension_only",
            "storage_available": await semantic_storage_available(session),
        }


async def backfill(dry_run: bool, batch_size: int | None) -> dict[str, Any]:
    async with async_session_factory() as session:
        result = await backfill_order_embeddings(
            session,
            dry_run=dry_run,
            batch_size=batch_size,
        )
    return result.__dict__


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
