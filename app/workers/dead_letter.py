from __future__ import annotations

import json
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import async_session_factory
from app.models import FailedTask


def make_failed_task_dedup_key(task_name: str, task_id: str | None, args: object) -> str:
    if task_id:
        return f"{task_name}:{task_id}"
    return f"{task_name}:{json.dumps(to_jsonable(args), sort_keys=True)}"


async def record_failed_task(
    task_name: str,
    reason: str,
    task_id: str | None = None,
    queue: str | None = None,
    args: object = None,
    kwargs: object = None,
    retries: int = 0,
    correlation_id: str | None = None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> bool:
    dedup_key = make_failed_task_dedup_key(task_name, task_id, args)
    statement = (
        insert(FailedTask)
        .values(
            task_name=task_name,
            task_id=task_id,
            queue=queue,
            dedup_key=dedup_key,
            args=to_jsonable(args),
            kwargs=to_jsonable(kwargs),
            reason=reason,
            retries=retries,
            correlation_id=correlation_id,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(FailedTask.id)
    )
    async with session_factory() as session:
        inserted_id = await session.scalar(statement)
        await session.commit()
    return inserted_id is not None


def to_jsonable(value: object) -> Any:
    return json.loads(json.dumps(value, default=str))
