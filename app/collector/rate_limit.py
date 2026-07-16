"""Conservative per-account request budgeting. Never used to dodge FloodWait."""

from __future__ import annotations

from uuid import UUID

import redis.asyncio as redis

from app.core.config import get_settings


async def acquire_account_request_slot(account_id: UUID) -> bool:
    """Return True when the account may perform one more Telegram request this minute."""
    settings = get_settings()
    limit = max(settings.collector_max_requests_per_minute, 1)
    client = redis.from_url(settings.redis_url)
    key = f"collector:account:{account_id}:rpm"
    try:
        count = int(await client.incr(key))
        if count == 1:
            await client.expire(key, 60)
        return count <= limit
    finally:
        await client.aclose()
