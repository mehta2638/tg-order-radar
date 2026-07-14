from __future__ import annotations

from types import TracebackType
from uuid import uuid4

import redis.asyncio as redis

from app.core.config import get_settings


class SourceLease:
    async def __aenter__(self) -> bool:
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        raise NotImplementedError


class RedisSourceLease(SourceLease):
    def __init__(self, source_id: str, ttl_seconds: int) -> None:
        settings = get_settings()
        self.redis = redis.from_url(settings.redis_url)
        self.key = f"collector:source:{source_id}:lease"
        self.token = str(uuid4())
        self.ttl_seconds = ttl_seconds
        self.acquired = False

    async def __aenter__(self) -> bool:
        self.acquired = bool(
            await self.redis.set(
                self.key,
                self.token,
                ex=self.ttl_seconds,
                nx=True,
            )
        )
        return self.acquired

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if self.acquired:
                await self.redis.eval(
                    """
                    if redis.call("get", KEYS[1]) == ARGV[1] then
                        return redis.call("del", KEYS[1])
                    end
                    return 0
                    """,
                    1,
                    self.key,
                    self.token,
                )
        finally:
            await self.redis.aclose()
